/*
READ-ONLY REVIEW SCRIPT

Purpose: preflight public.agent_actions and public.crm_leads before the proposed
Phase 1-5 hardening migration. Run this file in the Supabase SQL Editor and
retain every result set and error for review.

This script contains only SELECT/WITH catalog and aggregate queries. It does not
change schema, privileges, policies, functions, or data. Identifier-only samples
exclude customer content, notes, reasons, payloads, and message text.
*/

-- 1. Table ownership, persistence, estimated rows, and RLS state.
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    pg_get_userbyid(c.relowner) AS table_owner,
    c.relpersistence AS persistence_type,
    c.reltuples::bigint AS estimated_row_count,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('agent_actions', 'crm_leads')
  AND c.relkind IN ('r', 'p')
ORDER BY c.relname;

-- 2. Authoritative agent_actions.company_id backfill counts.
SELECT
    count(*) FILTER (
        WHERE aa.company_id IS NULL
          AND bot.id IS NOT NULL
          AND bot.company_id IS NOT NULL
    ) AS safely_backfillable_from_chatbot,
    count(*) FILTER (
        WHERE aa.company_id IS NULL
          AND (bot.id IS NULL OR bot.company_id IS NULL)
    ) AS not_backfillable_from_chatbot,
    count(*) FILTER (WHERE aa.company_id IS NOT NULL) AS already_populated,
    count(*) AS total_rows
FROM public.agent_actions AS aa
LEFT JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id;

-- 3. Identifier-only rows eligible for the authoritative ownership backfill.
SELECT
    aa.id,
    aa.company_id,
    aa.chatbot_id,
    aa.conversation_id,
    aa.message_id,
    aa.status,
    aa.intent,
    aa.created_at
FROM public.agent_actions AS aa
JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
WHERE aa.company_id IS NULL
  AND bot.company_id IS NOT NULL
ORDER BY aa.created_at, aa.id
LIMIT 250;

-- 4. Identifier-only agent actions whose chatbot is missing.
SELECT
    aa.id,
    aa.company_id,
    aa.chatbot_id,
    aa.conversation_id,
    aa.message_id,
    aa.status,
    aa.intent,
    aa.created_at
FROM public.agent_actions AS aa
LEFT JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
WHERE bot.id IS NULL
ORDER BY aa.created_at, aa.id
LIMIT 250;

-- 5. Identifier-only agent actions whose non-null conversation is missing.
SELECT
    aa.id,
    aa.company_id,
    aa.chatbot_id,
    aa.conversation_id,
    aa.message_id,
    aa.status,
    aa.intent,
    aa.created_at
FROM public.agent_actions AS aa
LEFT JOIN public.conversations AS conv ON conv.id = aa.conversation_id
WHERE aa.conversation_id IS NOT NULL
  AND conv.id IS NULL
ORDER BY aa.created_at, aa.id
LIMIT 250;

-- 6. Identifier-only CRM leads whose chatbot is missing.
SELECT
    lead.id,
    lead.company_id,
    lead.chatbot_id,
    lead.conversation_id,
    lead.status,
    lead.lead_type,
    lead.created_at
FROM public.crm_leads AS lead
LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
WHERE bot.id IS NULL
ORDER BY lead.created_at, lead.id
LIMIT 250;

-- 7. Identifier-only CRM leads whose non-null conversation is missing.
SELECT
    lead.id,
    lead.company_id,
    lead.chatbot_id,
    lead.conversation_id,
    lead.status,
    lead.lead_type,
    lead.created_at
FROM public.crm_leads AS lead
LEFT JOIN public.conversations AS conv ON conv.id = lead.conversation_id
WHERE lead.conversation_id IS NOT NULL
  AND conv.id IS NULL
ORDER BY lead.created_at, lead.id
LIMIT 250;

-- 8. Aggregate ownership and relationship mismatches.
SELECT
    'agent_actions_company_vs_chatbot' AS check_name,
    count(*) AS mismatch_count
FROM public.agent_actions AS aa
JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
WHERE aa.company_id IS DISTINCT FROM bot.company_id
  AND aa.company_id IS NOT NULL
UNION ALL
SELECT
    'agent_actions_conversation_vs_chatbot',
    count(*)
FROM public.agent_actions AS aa
JOIN public.conversations AS conv ON conv.id = aa.conversation_id
WHERE conv.chatbot_id IS DISTINCT FROM aa.chatbot_id
UNION ALL
SELECT
    'crm_leads_company_vs_chatbot',
    count(*)
FROM public.crm_leads AS lead
JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
WHERE lead.company_id IS DISTINCT FROM bot.company_id
UNION ALL
SELECT
    'crm_leads_conversation_vs_chatbot',
    count(*)
FROM public.crm_leads AS lead
JOIN public.conversations AS conv ON conv.id = lead.conversation_id
WHERE conv.chatbot_id IS DISTINCT FROM lead.chatbot_id
ORDER BY check_name;

-- 9. Identifier-only ownership mismatch samples.
SELECT
    aa.id,
    aa.company_id,
    aa.chatbot_id,
    aa.conversation_id,
    aa.message_id,
    aa.status,
    aa.intent,
    aa.created_at
FROM public.agent_actions AS aa
JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
WHERE aa.company_id IS NOT NULL
  AND aa.company_id IS DISTINCT FROM bot.company_id
ORDER BY aa.created_at, aa.id
LIMIT 25;

SELECT
    lead.id,
    lead.company_id,
    lead.chatbot_id,
    lead.conversation_id,
    lead.status,
    lead.lead_type,
    lead.created_at
FROM public.crm_leads AS lead
JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
WHERE lead.company_id IS DISTINCT FROM bot.company_id
ORDER BY lead.created_at, lead.id
LIMIT 25;

-- 10. Duplicate open CRM lead candidates. NULL conversations are excluded by design.
SELECT
    chatbot_id,
    conversation_id,
    count(*) AS open_lead_count,
    min(created_at) AS first_created_at,
    max(created_at) AS last_created_at
FROM public.crm_leads
WHERE conversation_id IS NOT NULL
  AND status IN ('new', 'in_progress', 'contacted')
GROUP BY chatbot_id, conversation_id
HAVING count(*) > 1
ORDER BY open_lead_count DESC, chatbot_id, conversation_id;

-- 11. Values that would fail the proposed compatible checks.
SELECT 'agent_actions.status' AS checked_column, status::text AS unexpected_value, count(*) AS row_count
FROM public.agent_actions
WHERE status IS NULL OR status NOT IN ('detected', 'resolved')
GROUP BY status
UNION ALL
SELECT 'agent_actions.intent', intent::text, count(*)
FROM public.agent_actions
WHERE intent IS NULL
   OR intent NOT IN (
       'greeting',
       'general_question',
       'lead_interest',
       'handoff_request',
       'complaint',
       'knowledge_gap',
       'unknown'
   )
GROUP BY intent
UNION ALL
SELECT 'agent_actions.action_type', action_type::text, count(*)
FROM public.agent_actions
WHERE action_type IS NULL
   OR action_type NOT IN (
       'answer',
       'ask_follow_up',
       'create_lead',
       'request_handoff',
       'escalate',
       'log_knowledge_gap',
       'none'
   )
GROUP BY action_type
UNION ALL
SELECT 'crm_leads.status', status::text, count(*)
FROM public.crm_leads
WHERE status IS NULL OR status NOT IN ('new', 'in_progress', 'contacted', 'closed')
GROUP BY status
UNION ALL
SELECT 'crm_leads.priority', priority::text, count(*)
FROM public.crm_leads
WHERE priority IS NULL OR priority NOT IN ('low', 'medium', 'high')
GROUP BY priority
UNION ALL
SELECT 'crm_leads.lead_type', lead_type::text, count(*)
FROM public.crm_leads
WHERE lead_type IS NULL OR lead_type NOT IN ('follow_up', 'staff_attention', 'negative_feedback')
GROUP BY lead_type
ORDER BY checked_column, unexpected_value;

SELECT
    count(*) FILTER (WHERE confidence IS NOT NULL AND (confidence < 0 OR confidence > 1))
        AS invalid_agent_action_confidence_count
FROM public.agent_actions;

-- 12. Current constraints and validation state.
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    con.conname AS constraint_name,
    con.contype AS constraint_type,
    con.convalidated AS is_validated,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS c ON c.oid = con.conrelid
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('agent_actions', 'crm_leads')
ORDER BY c.relname, con.contype, con.conname;

-- 13. Current indexes and predicates.
SELECT
    n.nspname AS schema_name,
    table_class.relname AS table_name,
    index_class.relname AS index_name,
    idx.indisunique AS is_unique,
    idx.indisprimary AS is_primary,
    pg_get_indexdef(idx.indexrelid) AS index_definition,
    pg_get_expr(idx.indpred, idx.indrelid) AS partial_predicate
FROM pg_index AS idx
JOIN pg_class AS table_class ON table_class.oid = idx.indrelid
JOIN pg_class AS index_class ON index_class.oid = idx.indexrelid
JOIN pg_namespace AS n ON n.oid = table_class.relnamespace
WHERE n.nspname = 'public'
  AND table_class.relname IN ('agent_actions', 'crm_leads')
ORDER BY table_class.relname, index_class.relname;

-- 14. Current RLS policies. No rows are expected under the approved model.
SELECT
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual AS using_expression,
    with_check AS with_check_expression
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('agent_actions', 'crm_leads')
ORDER BY tablename, policyname;

-- 15. Explicit table grants for all grantees.
SELECT
    table_schema,
    table_name,
    grantee,
    privilege_type,
    is_grantable
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name IN ('agent_actions', 'crm_leads')
ORDER BY table_name, grantee, privilege_type;

-- 16. Related sequence names and explicit sequence grants.
SELECT
    table_name,
    column_name,
    pg_get_serial_sequence(format('%I.%I', table_schema, table_name), column_name)
        AS related_sequence
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('agent_actions', 'crm_leads')
  AND (
      is_identity = 'YES'
      OR column_default LIKE 'nextval(%'
  )
ORDER BY table_name, ordinal_position;

SELECT
    object_schema AS sequence_schema,
    object_name AS sequence_name,
    grantee,
    privilege_type,
    is_grantable
FROM information_schema.usage_privileges
WHERE object_schema = 'public'
  AND object_type = 'SEQUENCE'
ORDER BY sequence_name, grantee, privilege_type;

-- 17. Role RLS-bypass capability. service_role is expected to bypass RLS.
SELECT
    rolname AS role_name,
    rolsuper AS is_superuser,
    rolbypassrls AS bypasses_rls
FROM pg_roles
WHERE rolname IN ('postgres', 'service_role', 'authenticated', 'anon')
ORDER BY rolname;

-- 18. Permanent chatbot deletion RPC identity, security mode, owner, and execute grants.
SELECT
    n.nspname AS function_schema,
    p.proname AS function_name,
    pg_get_function_identity_arguments(p.oid) AS identity_arguments,
    p.prosecdef AS is_security_definer,
    pg_get_userbyid(p.proowner) AS function_owner
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname = 'permanently_delete_archived_chatbot'
ORDER BY identity_arguments;

SELECT
    routine_schema,
    routine_name,
    grantee,
    privilege_type,
    is_grantable
FROM information_schema.role_routine_grants
WHERE routine_schema = 'public'
  AND routine_name = 'permanently_delete_archived_chatbot'
ORDER BY grantee, privilege_type;

-- 19. Unique keys on public.chatbots and composite ownership-key readiness.
WITH chatbot_unique_indexes AS (
    SELECT
        index_class.relname AS index_name,
        idx.indisprimary AS is_primary,
        idx.indisunique AS is_unique,
        array_agg(att.attname ORDER BY keys.ordinality)
            FILTER (WHERE att.attname IS NOT NULL) AS key_columns,
        pg_get_expr(idx.indpred, idx.indrelid) AS partial_predicate
    FROM pg_index AS idx
    JOIN pg_class AS table_class ON table_class.oid = idx.indrelid
    JOIN pg_namespace AS n ON n.oid = table_class.relnamespace
    JOIN pg_class AS index_class ON index_class.oid = idx.indexrelid
    CROSS JOIN LATERAL unnest(idx.indkey) WITH ORDINALITY AS keys(attnum, ordinality)
    LEFT JOIN pg_attribute AS att
      ON att.attrelid = table_class.oid
     AND att.attnum = keys.attnum
    WHERE n.nspname = 'public'
      AND table_class.relname = 'chatbots'
      AND idx.indisunique
    GROUP BY index_class.relname, idx.indisprimary, idx.indisunique, idx.indpred, idx.indrelid
)
SELECT
    index_name,
    is_primary,
    is_unique,
    key_columns,
    partial_predicate,
    (
        key_columns = ARRAY['id', 'company_id']::name[]
        AND partial_predicate IS NULL
    ) AS supports_chatbot_company_composite_fk
FROM chatbot_unique_indexes
ORDER BY index_name;

-- 20. Exact chatbots.company_id -> companies.id foreign-key semantics.
-- No row means the expected ownership foreign key is absent from the live schema.
SELECT
    child_ns.nspname AS source_schema,
    child.relname AS source_table,
    con.conname AS constraint_name,
    source_att.attname AS source_column,
    parent_ns.nspname AS referenced_schema,
    parent.relname AS referenced_table,
    parent_att.attname AS referenced_column,
    CASE con.confupdtype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_update_action,
    CASE con.confdeltype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_delete_action,
    con.convalidated AS is_validated,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS child ON child.oid = con.conrelid
JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
JOIN pg_class AS parent ON parent.oid = con.confrelid
JOIN pg_namespace AS parent_ns ON parent_ns.oid = parent.relnamespace
CROSS JOIN LATERAL unnest(con.conkey, con.confkey)
    WITH ORDINALITY AS key_pair(source_attnum, parent_attnum, position)
JOIN pg_attribute AS source_att
  ON source_att.attrelid = child.oid
 AND source_att.attnum = key_pair.source_attnum
JOIN pg_attribute AS parent_att
  ON parent_att.attrelid = parent.oid
 AND parent_att.attnum = key_pair.parent_attnum
WHERE con.contype = 'f'
  AND child_ns.nspname = 'public'
  AND child.relname = 'chatbots'
  AND source_att.attname = 'company_id'
  AND parent_ns.nspname = 'public'
  AND parent.relname = 'companies'
  AND parent_att.attname = 'id'
ORDER BY con.conname, key_pair.position;

-- 21. All direct public-table foreign keys into companies, including actions.
SELECT
    child_ns.nspname AS source_schema,
    child.relname AS source_table,
    con.conname AS constraint_name,
    source_att.attname AS source_column,
    parent_att.attname AS referenced_column,
    CASE con.confupdtype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_update_action,
    CASE con.confdeltype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_delete_action,
    con.convalidated AS is_validated,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS child ON child.oid = con.conrelid
JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
JOIN pg_class AS parent ON parent.oid = con.confrelid
JOIN pg_namespace AS parent_ns ON parent_ns.oid = parent.relnamespace
CROSS JOIN LATERAL unnest(con.conkey, con.confkey)
    WITH ORDINALITY AS key_pair(source_attnum, parent_attnum, position)
JOIN pg_attribute AS source_att
  ON source_att.attrelid = child.oid
 AND source_att.attnum = key_pair.source_attnum
JOIN pg_attribute AS parent_att
  ON parent_att.attrelid = parent.oid
 AND parent_att.attnum = key_pair.parent_attnum
WHERE con.contype = 'f'
  AND child_ns.nspname = 'public'
  AND parent_ns.nspname = 'public'
  AND parent.relname = 'companies'
ORDER BY child.relname, con.conname, key_pair.position;

-- 22. Functions/procedures that may delete companies.
-- This searches both names and stored definitions; it does not execute them.
WITH candidate_company_delete_functions AS (
    SELECT
        p.oid,
        n.nspname AS function_schema,
        p.proname AS function_name,
        pg_get_function_identity_arguments(p.oid) AS identity_arguments,
        pg_get_function_result(p.oid) AS return_type,
        p.prosecdef AS is_security_definer,
        pg_get_userbyid(p.proowner) AS function_owner,
        pg_get_functiondef(p.oid) AS function_definition
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND p.prokind IN ('f', 'p')
      AND (
          p.proname ~* '(delete|remove|purge).*(company|tenant|account)'
          OR p.proname ~* '(company|tenant|account).*(delete|remove|purge)'
          OR pg_get_functiondef(p.oid)
              ~* 'delete[[:space:]]+from[[:space:]]+(public[.])?companies'
      )
)
SELECT
    function_schema,
    function_name,
    identity_arguments,
    return_type,
    is_security_definer,
    function_owner,
    function_definition
FROM candidate_company_delete_functions
ORDER BY function_schema, function_name, identity_arguments;

-- 23. Effective ACL entries for the company-deletion candidates above.
WITH candidate_company_delete_functions AS (
    SELECT
        p.oid,
        p.proowner,
        p.proacl,
        n.nspname AS function_schema,
        p.proname AS function_name,
        pg_get_function_identity_arguments(p.oid) AS identity_arguments
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND p.prokind IN ('f', 'p')
      AND (
          p.proname ~* '(delete|remove|purge).*(company|tenant|account)'
          OR p.proname ~* '(company|tenant|account).*(delete|remove|purge)'
          OR pg_get_functiondef(p.oid)
              ~* 'delete[[:space:]]+from[[:space:]]+(public[.])?companies'
      )
)
SELECT
    candidate.function_schema,
    candidate.function_name,
    candidate.identity_arguments,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE grantee_role.rolname
    END AS grantee,
    grantor_role.rolname AS grantor,
    acl.privilege_type,
    acl.is_grantable
FROM candidate_company_delete_functions AS candidate
CROSS JOIN LATERAL aclexplode(
    COALESCE(candidate.proacl, acldefault('f', candidate.proowner))
) AS acl
LEFT JOIN pg_roles AS grantee_role ON grantee_role.oid = acl.grantee
LEFT JOIN pg_roles AS grantor_role ON grantor_role.oid = acl.grantor
ORDER BY
    candidate.function_schema,
    candidate.function_name,
    candidate.identity_arguments,
    grantee,
    acl.privilege_type;

-- 24. Triggers directly attached to companies. These can reveal hidden cleanup
-- or deletion-blocking behavior even when no explicitly named RPC exists.
SELECT
    trigger_ns.nspname AS table_schema,
    table_class.relname AS table_name,
    trigger_row.tgname AS trigger_name,
    trigger_row.tgenabled AS enabled_status,
    function_ns.nspname AS function_schema,
    function_row.proname AS function_name,
    pg_get_triggerdef(trigger_row.oid, true) AS trigger_definition,
    pg_get_functiondef(function_row.oid) AS trigger_function_definition
FROM pg_trigger AS trigger_row
JOIN pg_class AS table_class ON table_class.oid = trigger_row.tgrelid
JOIN pg_namespace AS trigger_ns ON trigger_ns.oid = table_class.relnamespace
JOIN pg_proc AS function_row ON function_row.oid = trigger_row.tgfoid
JOIN pg_namespace AS function_ns ON function_ns.oid = function_row.pronamespace
WHERE trigger_ns.nspname = 'public'
  AND table_class.relname = 'companies'
  AND NOT trigger_row.tgisinternal
ORDER BY trigger_row.tgname;
