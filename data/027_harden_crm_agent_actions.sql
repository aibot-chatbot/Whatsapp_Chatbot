/*
STAGING-VERIFIED MIGRATION - PRODUCTION NOT APPLIED

Phase 1-5 hardening for public.agent_actions and public.crm_leads.

Approval gates:
  1. Export/backup both tables and capture the preflight results.
  2. Review every orphan identifier and approve a separate disposition.
  3. Re-run preflight and confirm every precondition below is zero.
  4. Apply to staging first, then run the verification script.

Staging verification completed successfully on 2026-07-25 after migration 028
removed the exact approved orphans. The deployed staging copy included the
required END; terminators for both PL/pgSQL blocks. Production remains unchanged.
*/

BEGIN;

-- Phase 2: the only permitted historical ownership repair.
-- Ownership is derived exclusively from the authoritative chatbot row.
UPDATE public.agent_actions AS aa
SET company_id = bot.company_id
FROM public.chatbots AS bot
WHERE aa.company_id IS NULL
  AND aa.chatbot_id = bot.id
  AND bot.company_id IS NOT NULL;

-- Phase 2 approval gate: stop before any DDL or grant changes if historical
-- integrity, compatible values, or required operational assumptions are unmet.
DO $preconditions$
DECLARE
    violation_count bigint;
BEGIN
    SELECT count(*) INTO violation_count
    FROM public.agent_actions AS aa
    LEFT JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
    WHERE bot.id IS NULL;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % agent_actions rows reference missing chatbots. Review and approve a separate disposition.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    WHERE bot.id IS NULL;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % crm_leads rows reference missing chatbots. Review and approve a separate disposition.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.agent_actions AS aa
    LEFT JOIN public.conversations AS conv ON conv.id = aa.conversation_id
    WHERE aa.conversation_id IS NOT NULL
      AND conv.id IS NULL;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % agent_actions rows reference missing conversations. No automatic nulling is permitted.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.crm_leads AS lead
    LEFT JOIN public.conversations AS conv ON conv.id = lead.conversation_id
    WHERE lead.conversation_id IS NOT NULL
      AND conv.id IS NULL;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % crm_leads rows reference missing conversations. No automatic nulling is permitted.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.agent_actions
    WHERE company_id IS NULL;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % agent_actions rows still have null company_id after authoritative backfill.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.agent_actions AS aa
    JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
    WHERE aa.company_id IS DISTINCT FROM bot.company_id;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % agent_actions rows disagree with chatbot company ownership.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.crm_leads AS lead
    JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    WHERE lead.company_id IS DISTINCT FROM bot.company_id;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % crm_leads rows disagree with chatbot company ownership.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.agent_actions AS aa
    JOIN public.conversations AS conv ON conv.id = aa.conversation_id
    WHERE conv.chatbot_id IS DISTINCT FROM aa.chatbot_id;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % agent_actions conversations belong to another chatbot.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.crm_leads AS lead
    JOIN public.conversations AS conv ON conv.id = lead.conversation_id
    WHERE conv.chatbot_id IS DISTINCT FROM lead.chatbot_id;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % crm_leads conversations belong to another chatbot.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.agent_actions AS aa
    LEFT JOIN public.companies AS company ON company.id = aa.company_id
    WHERE company.id IS NULL;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % agent_actions rows reference missing companies.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.crm_leads AS lead
    LEFT JOIN public.companies AS company ON company.id = lead.company_id
    WHERE company.id IS NULL;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % crm_leads rows reference missing companies.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.agent_actions
    WHERE status IS NULL
       OR status NOT IN ('detected', 'resolved')
       OR intent IS NULL
       OR intent NOT IN (
           'greeting',
           'general_question',
           'lead_interest',
           'handoff_request',
           'complaint',
           'knowledge_gap',
           'unknown'
       )
       OR action_type IS NULL
       OR action_type NOT IN (
           'answer',
           'ask_follow_up',
           'create_lead',
           'request_handoff',
           'escalate',
           'log_knowledge_gap',
           'none'
       )
       OR (confidence IS NOT NULL AND (confidence < 0 OR confidence > 1));
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % agent_actions rows would fail the proposed value checks.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM public.crm_leads
    WHERE status IS NULL
       OR status NOT IN ('new', 'in_progress', 'contacted', 'closed')
       OR priority IS NULL
       OR priority NOT IN ('low', 'medium', 'high')
       OR lead_type IS NULL
       OR lead_type NOT IN ('follow_up', 'staff_attention', 'negative_feedback');
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % crm_leads rows would fail the proposed value checks.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM (
        SELECT chatbot_id, conversation_id
        FROM public.crm_leads
        WHERE conversation_id IS NOT NULL
          AND status IN ('new', 'in_progress', 'contacted')
        GROUP BY chatbot_id, conversation_id
        HAVING count(*) > 1
    ) AS duplicate_open_leads;
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: % duplicate open CRM lead keys require review.',
            violation_count;
    END IF;

    SELECT count(*) INTO violation_count
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename IN ('agent_actions', 'crm_leads');
    IF violation_count <> 0 THEN
        RAISE EXCEPTION
            'Hardening stopped: unexpected existing RLS policies must be reviewed before service-role-only enforcement.';
    END IF;

    IF to_regprocedure(
        'public.permanently_delete_archived_chatbot(bigint,bigint,text)'
    ) IS NULL THEN
        RAISE EXCEPTION
            'Hardening stopped: expected permanent chatbot deletion RPC signature is missing.';
    END IF;

    IF NOT has_function_privilege(
        'service_role',
        'public.permanently_delete_archived_chatbot(bigint,bigint,text)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION
            'Hardening stopped: service_role lacks EXECUTE on the permanent chatbot deletion RPC.';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'service_role'
          AND (rolbypassrls OR rolsuper)
    ) THEN
        RAISE EXCEPTION
            'Hardening stopped: service_role does not bypass RLS; no service-role policy is included in this migration.';
    END IF;
END;
$preconditions$;

-- Phase 3: service-role-only browser access boundary.
-- RLS is intentionally not forced. service_role may BYPASSRLS, so backend
-- chatbot and tenant checks remain mandatory.
ALTER TABLE public.agent_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_leads ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public.agent_actions FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.crm_leads FROM PUBLIC, anon, authenticated;

REVOKE ALL PRIVILEGES ON TABLE public.agent_actions FROM service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.agent_actions TO service_role;

REVOKE ALL PRIVILEGES ON TABLE public.crm_leads FROM service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.crm_leads TO service_role;

-- Normalize privileges only on sequences owned by identity/serial columns on
-- these two tables. The browser roles do not need direct sequence access.
DO $sequence_grants$
DECLARE
    sequence_name text;
BEGIN
    FOR sequence_name IN
        SELECT DISTINCT pg_get_serial_sequence(
            format('%I.%I', cols.table_schema, cols.table_name),
            cols.column_name
        )
        FROM information_schema.columns AS cols
        WHERE cols.table_schema = 'public'
          AND cols.table_name IN ('agent_actions', 'crm_leads')
          AND (
              cols.is_identity = 'YES'
              OR cols.column_default LIKE 'nextval(%'
          )
    LOOP
        IF sequence_name IS NOT NULL THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM PUBLIC, anon, authenticated',
                sequence_name
            );
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM service_role',
                sequence_name
            );
            EXECUTE format(
                'GRANT USAGE, SELECT ON SEQUENCE %s TO service_role',
                sequence_name
            );
        END IF;
    END LOOP;
END;
$sequence_grants$;

-- Phase 4: referential integrity.
--
-- Direct company_id foreign keys are intentionally deferred. The repository
-- has no company-deletion workflow, and the available schema evidence does not
-- confirm how chatbots.company_id behaves when a company is deleted. Adding
-- RESTRICT or CASCADE here would therefore bake in an unresolved blocking or
-- destructive tenant-deletion policy. The authoritative backfill, company_id
-- NOT NULL enforcement, company existence checks, ownership mismatch checks,
-- and backend tenant validation remain in force.
--
-- Simple chatbot and conversation foreign keys are used because the inspected
-- schema has not yet confirmed a unique chatbots(id, company_id) parent key.
-- Application ownership checks remain required.
ALTER TABLE public.agent_actions
    ADD CONSTRAINT agent_actions_chatbot_id_fkey
    FOREIGN KEY (chatbot_id)
    REFERENCES public.chatbots(id)
    ON UPDATE NO ACTION
    ON DELETE CASCADE
    NOT VALID,
    ADD CONSTRAINT agent_actions_conversation_id_fkey
    FOREIGN KEY (conversation_id)
    REFERENCES public.conversations(id)
    ON UPDATE NO ACTION
    ON DELETE SET NULL
    NOT VALID;

ALTER TABLE public.crm_leads
    ADD CONSTRAINT crm_leads_chatbot_id_fkey
    FOREIGN KEY (chatbot_id)
    REFERENCES public.chatbots(id)
    ON UPDATE NO ACTION
    ON DELETE CASCADE
    NOT VALID,
    ADD CONSTRAINT crm_leads_conversation_id_fkey
    FOREIGN KEY (conversation_id)
    REFERENCES public.conversations(id)
    ON UPDATE NO ACTION
    ON DELETE SET NULL
    NOT VALID;

ALTER TABLE public.agent_actions
    VALIDATE CONSTRAINT agent_actions_chatbot_id_fkey,
    VALIDATE CONSTRAINT agent_actions_conversation_id_fkey;

ALTER TABLE public.crm_leads
    VALIDATE CONSTRAINT crm_leads_chatbot_id_fkey,
    VALIDATE CONSTRAINT crm_leads_conversation_id_fkey;

-- Validate a temporary check before taking the stronger catalog lock needed to
-- set NOT NULL. conversation_id and message_id intentionally remain nullable.
ALTER TABLE public.agent_actions
    ADD CONSTRAINT agent_actions_company_id_not_null_check
    CHECK (company_id IS NOT NULL)
    NOT VALID;

ALTER TABLE public.agent_actions
    VALIDATE CONSTRAINT agent_actions_company_id_not_null_check;

ALTER TABLE public.agent_actions
    ALTER COLUMN company_id SET NOT NULL;

ALTER TABLE public.agent_actions
    DROP CONSTRAINT agent_actions_company_id_not_null_check;

-- Phase 5: compatible domain checks. Historical general_question and escalate
-- values are intentionally included.
ALTER TABLE public.agent_actions
    ADD CONSTRAINT agent_actions_status_check
    CHECK (status IN ('detected', 'resolved'))
    NOT VALID,
    ADD CONSTRAINT agent_actions_intent_check
    CHECK (
        intent IN (
            'greeting',
            'general_question',
            'lead_interest',
            'handoff_request',
            'complaint',
            'knowledge_gap',
            'unknown'
        )
    )
    NOT VALID,
    ADD CONSTRAINT agent_actions_action_type_check
    CHECK (
        action_type IN (
            'answer',
            'ask_follow_up',
            'create_lead',
            'request_handoff',
            'escalate',
            'log_knowledge_gap',
            'none'
        )
    )
    NOT VALID,
    ADD CONSTRAINT agent_actions_confidence_check
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
    NOT VALID;

ALTER TABLE public.crm_leads
    ADD CONSTRAINT crm_leads_status_check
    CHECK (status IN ('new', 'in_progress', 'contacted', 'closed'))
    NOT VALID,
    ADD CONSTRAINT crm_leads_priority_check
    CHECK (priority IN ('low', 'medium', 'high'))
    NOT VALID,
    ADD CONSTRAINT crm_leads_lead_type_check
    CHECK (lead_type IN ('follow_up', 'staff_attention', 'negative_feedback'))
    NOT VALID;

ALTER TABLE public.agent_actions
    VALIDATE CONSTRAINT agent_actions_status_check,
    VALIDATE CONSTRAINT agent_actions_intent_check,
    VALIDATE CONSTRAINT agent_actions_action_type_check,
    VALIDATE CONSTRAINT agent_actions_confidence_check;

ALTER TABLE public.crm_leads
    VALIDATE CONSTRAINT crm_leads_status_check,
    VALIDATE CONSTRAINT crm_leads_priority_check,
    VALIDATE CONSTRAINT crm_leads_lead_type_check;

-- Existing (chatbot_id, created_at) does not efficiently satisfy the equality
-- predicate on status used by pending-action queries.
CREATE INDEX agent_actions_chatbot_status_created_at_idx
    ON public.agent_actions (chatbot_id, status, created_at DESC);

-- Enforce at most one open lead for a non-null chatbot/conversation key.
-- Closed leads and leads without a conversation remain outside this rule.
CREATE UNIQUE INDEX crm_leads_one_open_per_conversation_idx
    ON public.crm_leads (chatbot_id, conversation_id)
    WHERE conversation_id IS NOT NULL
      AND status IN ('new', 'in_progress', 'contacted');

COMMIT;
