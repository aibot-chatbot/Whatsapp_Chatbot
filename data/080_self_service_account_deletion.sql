-- 080: self-service workspace deletion (Profile > Delete workspace).
--
--   account_deletion_codes        the emailed 6-digit confirmation code, hash only. Its own table on
--                                 purpose: users.otp_code and password_reset_otps are login / reset
--                                 codes, and a code issued for one purpose must never confirm another.
--   account_deletion_blocker()    the single source of truth for "may this user delete this
--                                 workspace?". NULL = yes; otherwise a stable code the UI can explain:
--                                 not_found, not_owner, protected, payment_history, support_records.
--   delete_company_account()      re-runs the blocker under a company row lock, deletes the whole
--                                 workspace in one transaction, then proves nothing was left behind.
--
-- Owner = the person who registered the workspace: its earliest-created user, and only while that
-- user is still an active admin. Deliberately NOT "the earliest active admin" (the billing-contact
-- rule): with that rule a second admin could deactivate or demote the registrant and inherit the
-- right to delete everything. A registrant who was deactivated or demoted leaves nobody able to
-- self-delete, and support handles it. Payment history, protected companies,
-- platform staff and retained platform / support records are refused, never deleted: this
-- function does not touch ai_credit_topup_orders, company_subscription_orders or any platform or
-- tenant_support_* table. company_subscription_orders carries company_id with no foreign key,
-- so a concurrent checkout could insert a row after the guard ran; it is deliberately NOT
-- deleted here, so the orphan check below rolls the whole deletion back instead of destroying
-- a payment record.
--
-- Not applied by this file's author. Apply BEFORE deploying the code that calls it, in
-- off-peak hours (the function takes row locks, not table locks). Rollback:
-- 080_self_service_account_deletion_rollback.sql.
--
-- Why the delete list is long. A cascade from companies/chatbots only reaches tables with a foreign
-- key. Verified against pg_constraint (2026-10-17), these have none and would be left behind
-- silently:
--   company_id : agent_actions, ai_usage_logs, billing_notifications, bot_media_attachments,
--                chatbot_web_widgets, company_subscription_orders, crm_leads, invites, wasender_channels
--   chatbot_id : ai_usage_logs, knowledge_chunks, knowledge_graph_edges, knowledge_graph_nodes,
--                wasender_channels
-- password_reset_otps and pending_registrations are keyed by email with no foreign key at all. They
-- hold the deleted people's reset codes and unfinished sign-ups, so they are deleted by email.
-- ai_credit_transactions and company_ai_credit_balances have NO ACTION foreign keys that block
-- the final delete. messages.actor_user_id references users ON DELETE RESTRICT, and messages sit
-- two cascade levels below the company (chatbots -> conversations -> messages), which the users
-- delete does not wait for: so the chatbots go on their own, before the company. The other
-- RESTRICT-to-users tables (conversation_internal_notes, conversation_handoff_controls,
-- analysis_reports, analysis_schedules, geo_analyses) cascade straight from companies and would be
-- gone in time; they are deleted explicitly as a safety net.
--
-- booking_closures, booking_schedules and booking_slots reference booking_packages through a
-- composite (package_id, company_id, chatbot_id) foreign key. booking_slots has a BEFORE DELETE
-- trigger (073) that refuses a direct delete of a slot holding seats at trigger depth 1; a cascade
-- from booking_packages runs at depth 2 and is allowed. So the packages go first and take their
-- schedules, closures and slots with them; the explicit booking deletes after that are a safety net.
--
-- The list cannot be trusted to stay complete, so the function ends with a dynamic check: any
-- public table whose company / chatbot / user-reference column has no foreign key to companies,
-- chatbots or users, and still holds this company_id, one of its chatbot ids, or one of its user
-- ids, aborts the transaction and the deletion rolls back as a whole. A table added later without
-- a foreign key therefore fails safe instead of leaving orphans. Columns WITH such a foreign key are
-- skipped: the cascade emptied them, or the delete would already have raised.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

-- plpgsql resolves table names lazily, so a missing or renamed table would only surface when a
-- customer tried to delete their workspace. Fail the migration instead.
DO $$
DECLARE
  missing text;
BEGIN
  SELECT string_agg(t, ', ') INTO missing
    FROM unnest(ARRAY[
      'agent_actions', 'ai_credit_topup_orders', 'ai_credit_transactions', 'ai_usage_logs',
      'analysis_reports', 'analysis_schedules', 'billing_notifications', 'booking_closures',
      'booking_packages', 'booking_schedules', 'booking_slots', 'bot_media_attachments',
      'chatbot_web_widgets', 'chatbots', 'companies', 'company_ai_credit_balances',
      'company_subscription_orders', 'company_subscriptions', 'conversation_handoff_controls',
      'conversation_internal_notes', 'crm_leads', 'geo_analyses', 'invites', 'knowledge_chunks',
      'knowledge_graph_edges', 'knowledge_graph_nodes', 'password_reset_otps', 'pending_registrations',
      'platform_admin_protected_companies',
      'platform_admin_users', 'platform_approval_requests', 'platform_support_cases',
      'tenant_support_audit_events', 'tenant_support_replies', 'tenant_support_reply_notifications',
      'tenant_support_request_events', 'tenant_support_requests', 'users', 'wasender_channels'
    ]) AS t
   WHERE to_regclass('public.' || t) IS NULL;
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION '080 aborted: tables the deletion function needs do not exist: %', missing;
  END IF;

  -- Columns are resolved lazily too.
  SELECT string_agg(v.tbl || '.' || v.col, ', ') INTO missing
    FROM (VALUES ('users', 'created_at'), ('users', 'status'), ('users', 'role'), ('users', 'email'),
                 ('company_subscriptions', 'payment_gateway'), ('company_subscriptions', 'external_subscription_id'),
                 ('tenant_support_request_events', 'actor_user_id'), ('platform_admin_users', 'user_id'),
                 ('password_reset_otps', 'email'), ('pending_registrations', 'email')) AS v(tbl, col)
   WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a
                      WHERE a.attrelid = to_regclass('public.' || v.tbl) AND a.attname = v.col
                        AND a.attnum > 0 AND NOT a.attisdropped);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION '080 aborted: columns the deletion function needs do not exist: %', missing;
  END IF;
END
$$;

-- Every deleted user's RESTRICT check scans messages.actor_user_id, and messages grows with chat
-- volume: without this index a deletion would eventually outlast PostgREST's 8s statement timeout.
-- Plain CREATE INDEX (this file is one transaction); messages is small today, so the SHARE lock is
-- momentary. Use CREATE INDEX CONCURRENTLY outside a transaction if this is ever re-run on a big table.
CREATE INDEX IF NOT EXISTS messages_actor_user_id_idx
    ON public.messages (actor_user_id) WHERE actor_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.account_deletion_codes(
    user_id bigint PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    -- HMAC-SHA256 under the server secret, bound to the user. A 6-digit code has only a million
    -- values, so a bare hash would be reversible from a leaked row; this is not.
    code_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- The production project auto-grants anon and authenticated on every new public table.
ALTER TABLE public.account_deletion_codes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.account_deletion_codes FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.account_deletion_codes TO service_role;

CREATE OR REPLACE FUNCTION public.account_deletion_blocker(p_company_id bigint, p_user_id bigint)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_user_ids bigint[];
BEGIN
    IF p_company_id IS NULL OR p_user_id IS NULL THEN
        RETURN 'invalid_request';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.companies WHERE id = p_company_id)
       OR NOT EXISTS (SELECT 1 FROM public.users WHERE id = p_user_id AND company_id = p_company_id) THEN
        RETURN 'not_found';
    END IF;

    -- The registrant (earliest-created user, id tie-break so two accounts created in the same
    -- instant cannot both be "first"), and only while still an active admin. No role or status
    -- filter on the first query: a demoted or deactivated registrant must not pass the title on.
    IF p_user_id IS DISTINCT FROM (
        SELECT u.id
        FROM public.users u
        WHERE u.company_id = p_company_id
        ORDER BY u.created_at ASC, u.id ASC LIMIT 1
    ) OR NOT EXISTS (
        SELECT 1
        FROM public.users u
        WHERE u.id = p_user_id
          AND u.role IN ('admin', 'owner')
          AND u.status = 'active'
    ) THEN
        RETURN 'not_owner';
    END IF;

    SELECT COALESCE(array_agg(id), ARRAY[]::bigint[]) INTO v_user_ids
    FROM public.users WHERE company_id = p_company_id;

    IF EXISTS (SELECT 1 FROM public.platform_admin_protected_companies WHERE company_id = p_company_id)
       OR EXISTS (SELECT 1 FROM public.platform_admin_users WHERE user_id = ANY(v_user_ids)) THEN
        RETURN 'protected';
    END IF;

    IF EXISTS (SELECT 1 FROM public.ai_credit_topup_orders WHERE company_id = p_company_id)
       OR EXISTS (SELECT 1 FROM public.company_subscription_orders WHERE company_id = p_company_id)
       OR EXISTS (SELECT 1 FROM public.company_subscriptions WHERE company_id = p_company_id AND (payment_gateway IS NOT NULL OR external_subscription_id IS NOT NULL)) THEN
        RETURN 'payment_history';
    END IF;

    -- Retained platform records: all reference companies or users ON DELETE RESTRICT, and the
    -- platform keeps them on purpose. Request events carry no company_id, so they are matched
    -- through the people being deleted.
    IF EXISTS (SELECT 1 FROM public.platform_approval_requests WHERE company_id = p_company_id)
       OR EXISTS (SELECT 1 FROM public.platform_support_cases WHERE company_id = p_company_id)
       OR EXISTS (SELECT 1 FROM public.tenant_support_requests WHERE company_id = p_company_id OR requester_user_id = ANY(v_user_ids))
       OR EXISTS (SELECT 1 FROM public.tenant_support_replies WHERE company_id = p_company_id)
       OR EXISTS (SELECT 1 FROM public.tenant_support_reply_notifications WHERE company_id = p_company_id)
       OR EXISTS (SELECT 1 FROM public.tenant_support_audit_events WHERE company_id = p_company_id OR requester_user_id = ANY(v_user_ids))
       OR EXISTS (SELECT 1 FROM public.tenant_support_request_events WHERE actor_user_id = ANY(v_user_ids)) THEN
        RETURN 'support_records';
    END IF;

    RETURN NULL;
END;
$function$;

CREATE OR REPLACE FUNCTION public.delete_company_account(p_company_id bigint, p_user_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_blocker text;
    v_chatbot_ids bigint[];
    v_user_ids bigint[];
    v_emails text[];
    v_table text;
    v_column text;
    v_found boolean;
BEGIN
    IF p_company_id IS NULL OR p_user_id IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'error',
            'code', 'invalid_request',
            'message', 'company_id and user_id are required'
        );
    END IF;

    -- A second concurrent call waits here and then finds no company. A payment row that
    -- references the company by foreign key takes a key-share lock on this row, so it waits too.
    PERFORM 1 FROM public.companies WHERE id = p_company_id FOR UPDATE;
    -- And its people: a role or status change landing mid-call must not change who the owner is.
    PERFORM 1 FROM public.users WHERE company_id = p_company_id ORDER BY id FOR UPDATE;

    v_blocker := public.account_deletion_blocker(p_company_id, p_user_id);
    IF v_blocker IS NOT NULL THEN
        RETURN jsonb_build_object(
            'status', 'error',
            'code', v_blocker,
            'message', 'Workspace cannot be deleted (' || v_blocker || ')'
        );
    END IF;

    SELECT COALESCE(array_agg(id), ARRAY[]::bigint[]) INTO v_chatbot_ids
    FROM public.chatbots WHERE company_id = p_company_id;
    SELECT COALESCE(array_agg(id), ARRAY[]::bigint[]),
           COALESCE(array_agg(lower(btrim(email))) FILTER (WHERE email IS NOT NULL), ARRAY[]::text[])
      INTO v_user_ids, v_emails
    FROM public.users WHERE company_id = p_company_id;

    -- 1. NO ACTION foreign keys to companies / company_subscriptions.
    DELETE FROM public.ai_credit_transactions WHERE company_id = p_company_id;
    DELETE FROM public.company_ai_credit_balances WHERE company_id = p_company_id;

    -- 2. company_id with no foreign key. company_subscription_orders is NOT here: see the header.
    DELETE FROM public.ai_usage_logs WHERE company_id = p_company_id;
    DELETE FROM public.billing_notifications WHERE company_id = p_company_id;
    DELETE FROM public.invites WHERE company_id = p_company_id;
    DELETE FROM public.wasender_channels WHERE company_id = p_company_id;
    DELETE FROM public.agent_actions WHERE company_id = p_company_id;
    DELETE FROM public.crm_leads WHERE company_id = p_company_id;
    DELETE FROM public.chatbot_web_widgets WHERE company_id = p_company_id;
    DELETE FROM public.bot_media_attachments WHERE company_id = p_company_id;
    -- Packages first: their cascade removes booked slots at trigger depth 2 (see the header); the
    -- three booking deletes after it are a safety net.
    DELETE FROM public.booking_packages WHERE company_id = p_company_id;
    DELETE FROM public.booking_closures WHERE company_id = p_company_id;
    DELETE FROM public.booking_schedules WHERE company_id = p_company_id;
    DELETE FROM public.booking_slots WHERE company_id = p_company_id;

    -- 3. chatbot_id with no foreign key (edges before nodes).
    DELETE FROM public.knowledge_graph_edges WHERE chatbot_id = ANY(v_chatbot_ids);
    DELETE FROM public.knowledge_graph_nodes WHERE chatbot_id = ANY(v_chatbot_ids);
    DELETE FROM public.knowledge_chunks WHERE chatbot_id = ANY(v_chatbot_ids);
    DELETE FROM public.ai_usage_logs WHERE chatbot_id = ANY(v_chatbot_ids);
    DELETE FROM public.wasender_channels WHERE chatbot_id = ANY(v_chatbot_ids);
    DELETE FROM public.booking_schedules WHERE chatbot_id = ANY(v_chatbot_ids);
    DELETE FROM public.booking_slots WHERE chatbot_id = ANY(v_chatbot_ids);

    -- 3b. Keyed by email with no foreign key: the deleted people's reset codes and unfinished sign-ups.
    DELETE FROM public.password_reset_otps WHERE lower(btrim(email)) = ANY(v_emails);
    DELETE FROM public.pending_registrations WHERE lower(btrim(email)) = ANY(v_emails);

    -- 4. Foreign key to users is RESTRICT. These cascade straight from companies anyway; explicit as
    --    a safety net. (The real RESTRICT hazard is messages, handled by step 5.)
    DELETE FROM public.conversation_internal_notes WHERE company_id = p_company_id;
    DELETE FROM public.conversation_handoff_controls WHERE company_id = p_company_id;
    DELETE FROM public.analysis_reports WHERE company_id = p_company_id;
    DELETE FROM public.analysis_schedules WHERE company_id = p_company_id;
    DELETE FROM public.geo_analyses WHERE company_id = p_company_id;

    -- 5. The chatbots cascade conversations, messages, configs, knowledge files and the rest. Must run
    --    before the company: messages.actor_user_id is RESTRICT and two cascade levels deep.
    DELETE FROM public.chatbots WHERE company_id = p_company_id;

    -- 6. The company cascades its users (and their confirmation codes), subscriptions, channels,
    --    bookings and every other table that holds a foreign key to it.
    DELETE FROM public.companies WHERE id = p_company_id;

    -- Nothing may remain. Only columns WITHOUT a foreign key to companies / chatbots / users are
    -- scanned: one with such a key was emptied by the cascade or the delete would have raised.
    -- Compared as bigint[]: an int[] argument would not match bigint columns.
    -- shortcut: the whole deletion is one transaction under PostgREST's 8s authenticator
    -- statement_timeout, and its cost grows with the tenant's rows (about 4s for 1.2M rows on a
    -- laptop). A timeout rolls everything back, which is safe. Upgrade to chunked or background
    -- deletion when a tenant passes roughly 500k rows.
    FOR v_table, v_column IN
        SELECT cls.relname::text, att.attname::text
        FROM pg_catalog.pg_attribute att
        JOIN pg_catalog.pg_class cls ON cls.oid = att.attrelid
        WHERE cls.relnamespace = 'public'::regnamespace
          AND cls.relkind IN ('r', 'p')
          AND att.attnum > 0 AND NOT att.attisdropped
          AND att.atttypid IN ('int8'::regtype, 'int4'::regtype, 'int2'::regtype)
          AND att.attname IN (
              'company_id', 'chatbot_id', 'user_id', 'actor_user_id', 'author_user_id',
              'assignee_user_id', 'requester_user_id', 'created_by_user_id'
          )
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_constraint k
              WHERE k.contype = 'f' AND k.conrelid = cls.oid AND att.attnum = ANY (k.conkey)
                AND k.confrelid IN ('public.companies'::regclass, 'public.chatbots'::regclass,
                                    'public.users'::regclass)
          )
        ORDER BY 1, 2
    LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I WHERE %I = ANY($1))', v_table, v_column)
            INTO v_found
            USING CASE v_column
                      WHEN 'company_id' THEN ARRAY[p_company_id]::bigint[]
                      WHEN 'chatbot_id' THEN v_chatbot_ids
                      ELSE v_user_ids
                  END;
        IF v_found THEN
            RAISE EXCEPTION 'account_deletion_incomplete: %.% still references the deleted workspace',
                v_table, v_column USING ERRCODE = 'P0001';
        END IF;
    END LOOP;

    RETURN jsonb_build_object(
        'status', 'success',
        'code', 'deleted',
        'message', 'Workspace permanently deleted',
        'company_id', p_company_id,
        -- For the audit log line, so storage left behind by an interrupted cleanup can be swept.
        'chatbot_ids', to_jsonb(v_chatbot_ids),
        'deleted_counts', jsonb_build_object(
            'users', cardinality(v_user_ids),
            'chatbots', cardinality(v_chatbot_ids)
        )
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.account_deletion_blocker(bigint, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.account_deletion_blocker(bigint, bigint) TO service_role;
REVOKE ALL ON FUNCTION public.delete_company_account(bigint, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.delete_company_account(bigint, bigint) TO service_role;

COMMENT ON FUNCTION public.account_deletion_blocker(bigint, bigint)
IS 'NULL when the user may delete the workspace, otherwise not_found | not_owner | protected | payment_history | support_records.';
COMMENT ON FUNCTION public.delete_company_account(bigint, bigint)
IS 'Permanently deletes a whole workspace in one transaction after re-checking every guard, then rolls back if any row still references it.';

COMMIT;
