/*
READ-ONLY POST-MIGRATION VERIFICATION

Run only after an approved staging application of
data/027_harden_crm_agent_actions.sql. This script contains only SELECT/WITH
catalog and aggregate queries and does not change schema, privileges, policies,
functions, or data.
*/

-- 1. Required ownership and nullability outcomes.
SELECT
    count(*) AS total_agent_actions,
    count(*) FILTER (WHERE company_id IS NULL) AS null_company_id_count,
    count(*) FILTER (WHERE chatbot_id IS NULL) AS null_chatbot_id_count
FROM public.agent_actions;

SELECT
    cols.table_name,
    cols.column_name,
    cols.is_nullable
FROM information_schema.columns AS cols
WHERE cols.table_schema = 'public'
  AND (
      (cols.table_name = 'agent_actions'
       AND cols.column_name IN ('company_id', 'chatbot_id', 'conversation_id', 'message_id'))
      OR
      (cols.table_name = 'crm_leads'
       AND cols.column_name IN ('company_id', 'chatbot_id', 'conversation_id'))
  )
ORDER BY cols.table_name, cols.ordinal_position;

-- 2. Zero ownership mismatches and invalid relationship references.
-- Direct company foreign keys are deferred, but company existence remains an
-- expected application/data invariant and is verified here.
SELECT
    'agent_actions_missing_company' AS check_name,
    count(*) AS failure_count
FROM public.agent_actions AS aa
LEFT JOIN public.companies AS company ON company.id = aa.company_id
WHERE company.id IS NULL
UNION ALL
SELECT
    'agent_actions_missing_chatbot',
    count(*)
FROM public.agent_actions AS aa
LEFT JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
WHERE bot.id IS NULL
UNION ALL
SELECT
    'agent_actions_missing_conversation',
    count(*)
FROM public.agent_actions AS aa
LEFT JOIN public.conversations AS conv ON conv.id = aa.conversation_id
WHERE aa.conversation_id IS NOT NULL
  AND conv.id IS NULL
UNION ALL
SELECT
    'agent_actions_company_vs_chatbot',
    count(*)
FROM public.agent_actions AS aa
JOIN public.chatbots AS bot ON bot.id = aa.chatbot_id
WHERE aa.company_id IS DISTINCT FROM bot.company_id
UNION ALL
SELECT
    'agent_actions_conversation_vs_chatbot',
    count(*)
FROM public.agent_actions AS aa
JOIN public.conversations AS conv ON conv.id = aa.conversation_id
WHERE conv.chatbot_id IS DISTINCT FROM aa.chatbot_id
UNION ALL
SELECT
    'crm_leads_missing_company',
    count(*)
FROM public.crm_leads AS lead
LEFT JOIN public.companies AS company ON company.id = lead.company_id
WHERE company.id IS NULL
UNION ALL
SELECT
    'crm_leads_missing_chatbot',
    count(*)
FROM public.crm_leads AS lead
LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
WHERE bot.id IS NULL
UNION ALL
SELECT
    'crm_leads_missing_conversation',
    count(*)
FROM public.crm_leads AS lead
LEFT JOIN public.conversations AS conv ON conv.id = lead.conversation_id
WHERE lead.conversation_id IS NOT NULL
  AND conv.id IS NULL
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

-- 3. Every expected final hardening constraint exists and is validated.
WITH expected_constraints(table_name, constraint_name) AS (
    VALUES
        ('agent_actions', 'agent_actions_chatbot_id_fkey'),
        ('agent_actions', 'agent_actions_conversation_id_fkey'),
        ('agent_actions', 'agent_actions_status_check'),
        ('agent_actions', 'agent_actions_intent_check'),
        ('agent_actions', 'agent_actions_action_type_check'),
        ('agent_actions', 'agent_actions_confidence_check'),
        ('crm_leads', 'crm_leads_chatbot_id_fkey'),
        ('crm_leads', 'crm_leads_conversation_id_fkey'),
        ('crm_leads', 'crm_leads_status_check'),
        ('crm_leads', 'crm_leads_priority_check'),
        ('crm_leads', 'crm_leads_lead_type_check')
)
SELECT
    expected.table_name,
    expected.constraint_name,
    (con.oid IS NOT NULL) AS exists,
    con.contype AS constraint_type,
    con.convalidated AS is_validated,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM expected_constraints AS expected
LEFT JOIN (
    SELECT
        constraint_row.*,
        table_class.relname AS table_name
    FROM pg_constraint AS constraint_row
    JOIN pg_class AS table_class ON table_class.oid = constraint_row.conrelid
    JOIN pg_namespace AS table_ns ON table_ns.oid = table_class.relnamespace
    WHERE table_ns.nspname = 'public'
) AS con
  ON con.table_name = expected.table_name
 AND con.conname = expected.constraint_name
ORDER BY expected.table_name, expected.constraint_name;

-- Option C expects no direct target-table company foreign keys in migration 027.
-- Any returned row requires review before staging approval.
SELECT
    child.relname AS table_name,
    con.conname AS constraint_name,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS child ON child.oid = con.conrelid
JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
JOIN pg_class AS parent ON parent.oid = con.confrelid
JOIN pg_namespace AS parent_ns ON parent_ns.oid = parent.relnamespace
WHERE con.contype = 'f'
  AND child_ns.nspname = 'public'
  AND child.relname IN ('agent_actions', 'crm_leads')
  AND parent_ns.nspname = 'public'
  AND parent.relname = 'companies'
ORDER BY child.relname, con.conname;

-- 4. Expected indexes and predicates.
SELECT
    table_class.relname AS table_name,
    index_class.relname AS index_name,
    idx.indisvalid AS is_valid,
    idx.indisready AS is_ready,
    idx.indisunique AS is_unique,
    pg_get_indexdef(idx.indexrelid) AS index_definition,
    pg_get_expr(idx.indpred, idx.indrelid) AS partial_predicate
FROM pg_index AS idx
JOIN pg_class AS table_class ON table_class.oid = idx.indrelid
JOIN pg_class AS index_class ON index_class.oid = idx.indexrelid
JOIN pg_namespace AS n ON n.oid = table_class.relnamespace
WHERE n.nspname = 'public'
  AND index_class.relname IN (
      'agent_actions_chatbot_status_created_at_idx',
      'crm_leads_one_open_per_conversation_idx'
  )
ORDER BY index_class.relname;

-- 5. RLS enabled, not forced, with no client policies.
SELECT
    c.relname AS table_name,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('agent_actions', 'crm_leads')
  AND c.relkind IN ('r', 'p')
ORDER BY c.relname;

SELECT
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual,
    with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('agent_actions', 'crm_leads')
ORDER BY tablename, policyname;

-- 6. Explicit table privileges. anon/authenticated/PUBLIC should return no rows.
SELECT
    table_name,
    grantee,
    privilege_type,
    is_grantable
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name IN ('agent_actions', 'crm_leads')
ORDER BY table_name, grantee, privilege_type;

SELECT
    grantee,
    table_name,
    privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name IN ('agent_actions', 'crm_leads')
  AND grantee IN ('anon', 'authenticated', 'PUBLIC')
ORDER BY grantee, table_name, privilege_type;

-- 7. Related sequence privileges. Browser roles should return no rows.
WITH related_sequences AS (
    SELECT DISTINCT
        pg_get_serial_sequence(
            format('%I.%I', cols.table_schema, cols.table_name),
            cols.column_name
        ) AS qualified_sequence_name
    FROM information_schema.columns AS cols
    WHERE cols.table_schema = 'public'
      AND cols.table_name IN ('agent_actions', 'crm_leads')
      AND (
          cols.is_identity = 'YES'
          OR cols.column_default LIKE 'nextval(%'
      )
)
SELECT
    seq.qualified_sequence_name,
    role_name.rolname AS role_name,
    has_sequence_privilege(
        role_name.rolname,
        seq.qualified_sequence_name,
        'USAGE'
    ) AS has_usage,
    has_sequence_privilege(
        role_name.rolname,
        seq.qualified_sequence_name,
        'SELECT'
    ) AS has_select
FROM related_sequences AS seq
CROSS JOIN (
    SELECT rolname
    FROM pg_roles
    WHERE rolname IN ('service_role', 'authenticated', 'anon')
) AS role_name
WHERE seq.qualified_sequence_name IS NOT NULL
ORDER BY seq.qualified_sequence_name, role_name.rolname;

-- 8. service_role RLS behavior and permanent chatbot deletion RPC access.
SELECT
    rolname AS role_name,
    rolsuper AS is_superuser,
    rolbypassrls AS bypasses_rls
FROM pg_roles
WHERE rolname = 'service_role';

SELECT
    n.nspname AS function_schema,
    p.proname AS function_name,
    pg_get_function_identity_arguments(p.oid) AS identity_arguments,
    p.prosecdef AS is_security_definer,
    pg_get_userbyid(p.proowner) AS function_owner,
    has_function_privilege(
        'service_role',
        p.oid,
        'EXECUTE'
    ) AS service_role_can_execute
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname = 'permanently_delete_archived_chatbot'
ORDER BY identity_arguments;

-- 9. No duplicate open CRM lead keys.
SELECT
    chatbot_id,
    conversation_id,
    count(*) AS open_lead_count
FROM public.crm_leads
WHERE conversation_id IS NOT NULL
  AND status IN ('new', 'in_progress', 'contacted')
GROUP BY chatbot_id, conversation_id
HAVING count(*) > 1
ORDER BY open_lead_count DESC, chatbot_id, conversation_id;

-- 10. No rows outside the validated value domains.
SELECT
    count(*) FILTER (
        WHERE status NOT IN ('detected', 'resolved')
    ) AS invalid_status_count,
    count(*) FILTER (
        WHERE intent NOT IN (
            'greeting',
            'general_question',
            'lead_interest',
            'handoff_request',
            'complaint',
            'knowledge_gap',
            'unknown'
        )
    ) AS invalid_intent_count,
    count(*) FILTER (
        WHERE action_type NOT IN (
            'answer',
            'ask_follow_up',
            'create_lead',
            'request_handoff',
            'escalate',
            'log_knowledge_gap',
            'none'
        )
    ) AS invalid_action_type_count,
    count(*) FILTER (
        WHERE confidence IS NOT NULL AND (confidence < 0 OR confidence > 1)
    ) AS invalid_confidence_count
FROM public.agent_actions;

SELECT
    count(*) FILTER (
        WHERE status NOT IN ('new', 'in_progress', 'contacted', 'closed')
    ) AS invalid_status_count,
    count(*) FILTER (
        WHERE priority NOT IN ('low', 'medium', 'high')
    ) AS invalid_priority_count,
    count(*) FILTER (
        WHERE lead_type NOT IN ('follow_up', 'staff_attention', 'negative_feedback')
    ) AS invalid_lead_type_count
FROM public.crm_leads;
