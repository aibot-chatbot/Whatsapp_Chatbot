-- 060: persistence for the human-handoff control core (HO-2).
--
-- Applied with the user's authorization on 2026-09-22 to
-- parjsxypengvubziwwjp. The core, actor column, and NOT VALID foreign key
-- were applied as three separate migrations, then the FK was validated.
-- See docs/HANDOFF_PHASE_AB_RELEASE.md for the ledger and verification.
--
-- WHY A SEPARATE TABLE, NOT COLUMNS ON conversations
-- 058 records that public.conversations is the largest table here and that a
-- single transaction over it is a locking event. Six new columns plus a
-- backfill would repeat that for no gain, because the domain already has an
-- answer for "no row yet": handoff_service.initial_control() returns
-- ai_active / open / version 0 for a conversation that was never escalated.
-- An absent row IS that state, so this table needs no backfill at all and
-- existing conversations keep working untouched.
--
-- WHAT THIS DOES NOT CHANGE
-- agent_actions and is_conversation_escalated() stay authoritative while
-- HANDOFF_CONTROL_ENABLED is off. Nothing here makes the new path live.
--
-- RE-APPLYING AN EARLIER DRAFT
-- Every CREATE below is IF NOT EXISTS, which means a name left over from an
-- earlier iteration is kept with its OLD shape and the run
-- still reports success. This project has been bitten by exactly that with
-- index predicates. On an iterated target, compare the live shape and prepare
-- a forward migration. The DROP example at the tail is destructive and is
-- not a production rollback procedure.
--
-- ISOLATION ASSUMPTION
-- The compare-and-set below is correct under READ COMMITTED, which is what
-- psycopg and Supabase use. Under REPEATABLE READ the losing UPDATE would
-- raise a serialization error instead of losing cleanly.

-- A queued ACCESS EXCLUSIVE request blocks every later reader behind it, so
-- a lock we cannot take promptly must fail rather than stall the app.
SET lock_timeout = '3s';

BEGIN;

-- ── Control state ────────────────────────────────────────────────────────
-- handling_mode and resolution_status are deliberately two columns. Folding
-- them into one is the bug HO-1 exists to fix: resolving a ticket must leave
-- the conversation human_active, so that closing it cannot hand the customer
-- back to the model.
CREATE TABLE IF NOT EXISTS public.conversation_handoff_controls (
    conversation_id BIGINT PRIMARY KEY
        REFERENCES public.conversations(id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL
        REFERENCES public.companies(id) ON DELETE CASCADE,
    chatbot_id BIGINT NOT NULL
        REFERENCES public.chatbots(id) ON DELETE CASCADE,
    handling_mode TEXT NOT NULL DEFAULT 'ai_active'
        CHECK (handling_mode IN ('ai_active', 'waiting_human', 'human_active')),
    resolution_status TEXT NOT NULL DEFAULT 'open'
        CHECK (resolution_status IN ('open', 'resolved')),
    -- RESTRICT, not SET NULL. SET NULL would turn a staff member's
    -- exclusively-held escalation into an unowned human_active row that any
    -- member can assign to themselves, bypassing the audited
    -- supervisor_override path -- and it would do so without bumping
    -- `version`, so optimistic concurrency would never see it happen.
    -- The application never hard-deletes users (deactivation is a status
    -- update), so RESTRICT costs nothing operationally.
    assignee_user_id BIGINT NULL
        REFERENCES public.users(id) ON DELETE RESTRICT,
    episode_id INTEGER NOT NULL DEFAULT 0 CHECK (episode_id >= 0),
    -- Starts at 1, never 0. `p_expected_version = 0` is the RPC's sentinel
    -- for "no row yet", so a row that actually exists at version 0 would send
    -- every later call down the insert branch, hit ON CONFLICT DO NOTHING,
    -- and return VERSION_CONFLICT forever -- freezing that conversation with
    -- no command able to move it. The CHECK makes version 0 mean "absent"
    -- structurally, instead of by the RPC's good behaviour alone.
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    automation_epoch INTEGER NOT NULL DEFAULT 0 CHECK (automation_epoch >= 0),
    -- The domain rejects an unknown source and load() turns that into None,
    -- which every command treats as a refusal -- so one stray string would
    -- brick the conversation permanently, fail-closed and hard to diagnose.
    -- Postgres should refuse the bad write instead. Keep in step with
    -- _SOURCES in app/services/handoff_service.py.
    source TEXT NULL CHECK (
        source IS NULL
        OR source IN ('customer_request', 'staff_takeover', 'automation_rule')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One-directional on purpose. It forbids an assignee on a conversation no
    -- human holds. It deliberately does NOT also require an assignee whenever
    -- the mode is human_active: that stricter form is only safe because the
    -- service happens never to produce that state today, and a CHECK that
    -- depends on current application behaviour turns a future refactor into a
    -- hard database error instead of a test failure.
    CONSTRAINT handoff_control_assignee_requires_human CHECK (
        assignee_user_id IS NULL OR handling_mode = 'human_active'
    )
);

-- The queue read: "everything in this company still waiting for a person".
CREATE INDEX IF NOT EXISTS idx_handoff_controls_company_waiting
    ON public.conversation_handoff_controls(company_id, handling_mode)
    WHERE handling_mode <> 'ai_active';

-- The staff read: "what is assigned to me". company_id leads the index so the
-- query that uses it is pushed towards being company-scoped; an
-- assignee-only lookup across tenants is the shape to avoid.
CREATE INDEX IF NOT EXISTS idx_handoff_controls_assignee
    ON public.conversation_handoff_controls(company_id, assignee_user_id)
    WHERE assignee_user_id IS NOT NULL;

-- ── Internal notes ───────────────────────────────────────────────────────
-- A separate table from messages, on purpose. A note that lives in messages
-- is one wrong filter away from being delivered to the customer, and the
-- outbound path reads messages. Notes have no delivery_status and no
-- platform_message_id because they are never sent.
CREATE TABLE IF NOT EXISTS public.conversation_internal_notes (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    conversation_id BIGINT NOT NULL
        REFERENCES public.conversations(id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL
        REFERENCES public.companies(id) ON DELETE CASCADE,
    author_user_id BIGINT NOT NULL
        REFERENCES public.users(id) ON DELETE RESTRICT,
    note_text TEXT NOT NULL CHECK (length(btrim(note_text)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_internal_notes_conversation
    ON public.conversation_internal_notes(conversation_id, created_at DESC);

-- ── Atomic compare-and-set ───────────────────────────────────────────────
-- The claim race is decided here or not at all. A read-then-write in Python
-- lets two staff both win; a single conditional UPDATE lets exactly one.
-- No FOR UPDATE is needed, unlike 058's resolve function: that one reads,
-- decides, then writes across several statements, while this write is one
-- conditional statement that is its own lock.
--
-- Tenancy is re-derived here rather than trusted from the caller -- for the
-- conversation AND for the assignee. A CHECK cannot express "this user
-- belongs to this company", and the FK only proves the user exists.
CREATE OR REPLACE FUNCTION public.handoff_control_compare_and_set(
    p_conversation_id BIGINT,
    p_company_id BIGINT,
    p_chatbot_id BIGINT,
    p_expected_version INTEGER,
    p_handling_mode TEXT,
    p_resolution_status TEXT,
    p_assignee_user_id BIGINT,
    p_episode_id INTEGER,
    p_automation_epoch INTEGER,
    p_source TEXT
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $function$
DECLARE
    v_row public.conversation_handoff_controls%ROWTYPE;
    v_owns boolean;
BEGIN
    -- The conversation must belong to this chatbot, and the chatbot to this
    -- company. Note this returns CROSS_TENANT identically for "belongs to
    -- someone else" and "does not exist", so it is not an enumeration oracle.
    SELECT EXISTS (
        SELECT 1
        FROM public.conversations c
        JOIN public.chatbots b ON b.id = c.chatbot_id
        WHERE c.id = p_conversation_id
          AND c.chatbot_id = p_chatbot_id
          AND b.company_id = p_company_id
    ) INTO v_owns;

    IF NOT v_owns THEN
        RETURN jsonb_build_object('won', false, 'reason', 'CROSS_TENANT', 'control', NULL);
    END IF;

    -- Same refusal shape for a foreign assignee: without this, company A can
    -- durably write a company B user as the holder of its conversation, and
    -- any "assigned to me" query that forgets a company filter then reads
    -- across the tenant boundary.
    IF p_assignee_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.users
        WHERE id = p_assignee_user_id AND company_id = p_company_id
    ) THEN
        RETURN jsonb_build_object('won', false, 'reason', 'CROSS_TENANT', 'control', NULL);
    END IF;

    IF p_expected_version = 0 THEN
        -- First write for a conversation that has never been escalated.
        -- ON CONFLICT DO NOTHING makes a simultaneous first escalation a
        -- loser rather than an overwrite: it affects 0 rows, so FOUND is
        -- false and the loser path below runs.
        INSERT INTO public.conversation_handoff_controls AS ctl (
            conversation_id, company_id, chatbot_id, handling_mode,
            resolution_status, assignee_user_id, episode_id, version,
            automation_epoch, source
        ) VALUES (
            p_conversation_id, p_company_id, p_chatbot_id, p_handling_mode,
            p_resolution_status, p_assignee_user_id, p_episode_id, 1,
            p_automation_epoch, p_source
        )
        ON CONFLICT (conversation_id) DO NOTHING
        RETURNING ctl.* INTO v_row;
    ELSE
        UPDATE public.conversation_handoff_controls AS ctl
           SET handling_mode = p_handling_mode,
               resolution_status = p_resolution_status,
               assignee_user_id = p_assignee_user_id,
               episode_id = p_episode_id,
               version = p_expected_version + 1,
               automation_epoch = p_automation_epoch,
               source = p_source,
               updated_at = now()
         WHERE ctl.conversation_id = p_conversation_id
           AND ctl.version = p_expected_version
           -- automation_epoch is the staleness token that decides whether a
           -- queued automated message may still reach a customer. Rewinding
           -- it would re-admit a task dispatched before the takeover, so a
           -- rewind simply loses the CAS. The domain layer only ever
           -- increments; this is the guard against a buggy caller.
           AND ctl.automation_epoch <= p_automation_epoch
           AND ctl.episode_id <= p_episode_id
        RETURNING ctl.* INTO v_row;
    END IF;

    IF FOUND THEN
        RETURN jsonb_build_object('won', true, 'control', to_jsonb(v_row));
    END IF;

    -- Lost the race. Return what is actually stored so the caller can show
    -- the winner instead of guessing, and never overwrite them. Reachable
    -- only after the ownership guard passed, so every column here is the
    -- caller's own tenant.
    SELECT * INTO v_row
      FROM public.conversation_handoff_controls
     WHERE conversation_id = p_conversation_id;

    RETURN jsonb_build_object(
        'won', false,
        'reason', 'VERSION_CONFLICT',
        'control', CASE WHEN v_row.conversation_id IS NULL THEN NULL ELSE to_jsonb(v_row) END
    );
END;
$function$;

-- ── Internal note writer ─────────────────────────────────────────────────
-- Notes are written only through this function, never by a direct INSERT.
-- public.conversations has no company_id column, so a caller-supplied
-- company_id cannot be checked against the row it points at -- a mismatch
-- would be silently accepted and a company-scoped listing would then surface
-- or hide the wrong tenant's note. Deriving it here removes the parameter
-- entirely, which is the only way to make the mistake unrepresentable.
CREATE OR REPLACE FUNCTION public.create_conversation_internal_note(
    p_conversation_id BIGINT,
    p_chatbot_id BIGINT,
    p_author_user_id BIGINT,
    p_note_text TEXT
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $function$
DECLARE
    v_company_id BIGINT;
    v_row public.conversation_internal_notes%ROWTYPE;
BEGIN
    SELECT b.company_id INTO v_company_id
      FROM public.conversations c
      JOIN public.chatbots b ON b.id = c.chatbot_id
     WHERE c.id = p_conversation_id
       AND c.chatbot_id = p_chatbot_id;

    IF v_company_id IS NULL THEN
        RETURN jsonb_build_object('created', false, 'reason', 'CROSS_TENANT', 'note', NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.users
        WHERE id = p_author_user_id AND company_id = v_company_id
    ) THEN
        RETURN jsonb_build_object('created', false, 'reason', 'CROSS_TENANT', 'note', NULL);
    END IF;

    IF p_note_text IS NULL OR length(btrim(p_note_text)) = 0 THEN
        RETURN jsonb_build_object('created', false, 'reason', 'NOTE_EMPTY', 'note', NULL);
    END IF;

    INSERT INTO public.conversation_internal_notes AS n (
        conversation_id, company_id, author_user_id, note_text
    ) VALUES (
        p_conversation_id, v_company_id, p_author_user_id, btrim(p_note_text)
    )
    RETURNING n.* INTO v_row;

    RETURN jsonb_build_object('created', true, 'note', to_jsonb(v_row));
END;
$function$;

-- ── Access ───────────────────────────────────────────────────────────────
-- Same posture as 030: RLS on, direct table access revoked from the API
-- roles, and only service_role reaches these through the application. RLS
-- carries no policies because service_role bypasses it and anon/authenticated
-- are denied twice over; that is the dominant pattern in this repo's live
-- migrations, not an oversight.
ALTER TABLE public.conversation_handoff_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_internal_notes ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.conversation_handoff_controls FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.conversation_internal_notes FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.conversation_internal_notes_id_seq
    FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE ON public.conversation_handoff_controls TO service_role;
-- INSERT stays granted even though the writer function above is the only
-- intended path: that function is SECURITY INVOKER, so it runs as
-- service_role and revoking INSERT here would stop the function itself from
-- writing. 030 makes the same trade -- the function is the convention, not
-- the boundary.
GRANT SELECT, INSERT ON public.conversation_internal_notes TO service_role;
-- Supabase's bootstrap grants ALL on public tables to service_role by
-- default, so the narrower GRANT above adds nothing on its own. A note is a
-- permanent record of what staff said about a customer: revoke the rest
-- explicitly, the way 030 does, so the table is genuinely append-only.
REVOKE UPDATE, DELETE ON public.conversation_internal_notes FROM service_role;

REVOKE ALL ON FUNCTION public.handoff_control_compare_and_set(
    BIGINT, BIGINT, BIGINT, INTEGER, TEXT, TEXT, BIGINT, INTEGER, INTEGER, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.handoff_control_compare_and_set(
    BIGINT, BIGINT, BIGINT, INTEGER, TEXT, TEXT, BIGINT, INTEGER, INTEGER, TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.create_conversation_internal_note(
    BIGINT, BIGINT, BIGINT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_conversation_internal_note(
    BIGINT, BIGINT, BIGINT, TEXT
) TO service_role;

COMMIT;

-- ── messages.actor_user_id: separate transactions, on purpose ────────────
-- public.messages is the hot path: message_repository inserts on every
-- inbound and outbound message. ADD COLUMN takes ACCESS EXCLUSIVE on it, and
-- adding the foreign key takes a lock on public.users as well -- which stalls
-- the login path. Held inside the big transaction above, both locks would be
-- held through the function creation and every GRANT. Each statement below
-- therefore runs and commits on its own, and the constraint is added
-- NOT VALID so it never scans the table. 058 structured its own conversations
-- change the same way for the same reason.
--
-- Today a staff reply is saved as sender_type='bot' with no actor, so it is
-- unattributable. This column is the record of who actually typed it, and
-- RESTRICT keeps it that way: SET NULL would silently un-attribute every
-- reply a departing staff member ever sent.
--
-- NOTE FOR WHOEVER INTRODUCES sender_type='human':
-- chat_history_repository.py maps roles with
--   role = "assistant" if sender_type == "bot" else "user"
-- an inverted allowlist. A message stored as 'human' is fed to the model as
-- if the CUSTOMER wrote it. That line must be fixed in the same change, or
-- every resume-to-AI corrupts the transcript the model reads.

BEGIN;
ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS actor_user_id BIGINT NULL;
COMMIT;

BEGIN;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.messages'::regclass
          AND conname = 'messages_actor_user_id_fkey'
    ) THEN
        ALTER TABLE public.messages
            ADD CONSTRAINT messages_actor_user_id_fkey
            FOREIGN KEY (actor_user_id) REFERENCES public.users(id)
            ON DELETE RESTRICT NOT VALID;
    END IF;
END $$;
COMMIT;

-- Run AFTER the transaction above has committed. VALIDATE takes only SHARE
-- UPDATE EXCLUSIVE, so message writes keep flowing while it scans.
-- ALTER TABLE public.messages VALIDATE CONSTRAINT messages_actor_user_id_fkey;

-- ── Rollback / re-apply preamble ─────────────────────────────────────────
-- Dropping these does NOT return escalated conversations to the model: the
-- legacy agent_actions pause is independent and keeps working. Run only with
-- HANDOFF_CONTROL_ENABLED off.
--
-- DROP FUNCTION IF EXISTS public.create_conversation_internal_note(
--     BIGINT, BIGINT, BIGINT, TEXT);
-- DROP FUNCTION IF EXISTS public.handoff_control_compare_and_set(
--     BIGINT, BIGINT, BIGINT, INTEGER, TEXT, TEXT, BIGINT, INTEGER, INTEGER, TEXT);
-- DROP TABLE IF EXISTS public.conversation_internal_notes;
-- DROP TABLE IF EXISTS public.conversation_handoff_controls;
-- ALTER TABLE public.messages DROP CONSTRAINT IF EXISTS messages_actor_user_id_fkey;
-- ALTER TABLE public.messages DROP COLUMN IF EXISTS actor_user_id;
