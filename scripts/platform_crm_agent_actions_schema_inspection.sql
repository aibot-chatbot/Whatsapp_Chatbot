-- READ-ONLY INSPECTION PACKAGE
-- Purpose: inspect public.agent_actions and public.crm_leads in Supabase.
-- Every executable statement in this file is a SELECT or WITH ... SELECT.
-- Run each result section separately if the SQL Editor does not retain multiple grids.


-- ============================================================================
-- 1. TABLE EXISTENCE AND OWNERSHIP
-- Missing target tables simply do not produce a row in this catalog result.
-- ============================================================================
WITH target_tables(table_name) AS (
    VALUES ('agent_actions'), ('crm_leads')
)
SELECT
    '1. table existence and ownership' AS inspection_section,
    'public' AS schema_name,
    targets.table_name,
    cls.oid IS NOT NULL AS table_exists,
    pg_get_userbyid(cls.relowner) AS table_owner,
    CASE cls.relpersistence
        WHEN 'p' THEN 'permanent'
        WHEN 'u' THEN 'unlogged'
        WHEN 't' THEN 'temporary'
        ELSE cls.relpersistence::text
    END AS persistence_type,
    cls.reltuples::bigint AS estimated_row_count,
    cls.relrowsecurity AS rls_enabled,
    cls.relforcerowsecurity AS rls_forced
FROM target_tables AS targets
LEFT JOIN pg_namespace AS ns
  ON ns.nspname = 'public'
LEFT JOIN pg_class AS cls
  ON cls.relnamespace = ns.oid
 AND cls.relname = targets.table_name
 AND cls.relkind IN ('r', 'p')
ORDER BY targets.table_name;


-- ============================================================================
-- 2. COLUMN DEFINITIONS
-- ============================================================================
SELECT
    '2. column definitions' AS inspection_section,
    cols.table_schema AS schema_name,
    cols.table_name,
    cols.ordinal_position,
    cols.column_name,
    cols.data_type,
    format_type(attr.atttypid, attr.atttypmod) AS underlying_postgresql_type,
    cols.udt_schema AS underlying_type_schema,
    cols.udt_name AS underlying_type_name,
    cols.is_nullable,
    cols.column_default,
    cols.is_identity,
    cols.identity_generation,
    cols.is_generated,
    cols.generation_expression,
    cols.character_maximum_length
FROM information_schema.columns AS cols
JOIN pg_namespace AS ns
  ON ns.nspname = cols.table_schema
JOIN pg_class AS cls
  ON cls.relnamespace = ns.oid
 AND cls.relname = cols.table_name
JOIN pg_attribute AS attr
  ON attr.attrelid = cls.oid
 AND attr.attname = cols.column_name
 AND attr.attnum > 0
 AND NOT attr.attisdropped
WHERE cols.table_schema = 'public'
  AND cols.table_name IN ('agent_actions', 'crm_leads')
ORDER BY cols.table_name, cols.ordinal_position;


-- ============================================================================
-- 3. PRIMARY KEYS AND CONSTRAINTS
-- Includes primary, foreign, unique, check, and exclusion constraints.
-- ============================================================================
SELECT
    '3. primary keys and constraints' AS inspection_section,
    ns.nspname AS schema_name,
    cls.relname AS table_name,
    con.conname AS constraint_name,
    CASE con.contype
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'u' THEN 'UNIQUE'
        WHEN 'c' THEN 'CHECK'
        WHEN 'x' THEN 'EXCLUSION'
        ELSE con.contype::text
    END AS constraint_type,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS cls
  ON cls.oid = con.conrelid
JOIN pg_namespace AS ns
  ON ns.oid = cls.relnamespace
WHERE ns.nspname = 'public'
  AND cls.relname IN ('agent_actions', 'crm_leads')
  AND con.contype IN ('p', 'f', 'u', 'c', 'x')
ORDER BY cls.relname, constraint_type, con.conname;


-- ============================================================================
-- 4. FOREIGN-KEY ACTIONS
-- Composite keys produce one row per paired source/reference column.
-- ============================================================================
SELECT
    '4. foreign-key actions' AS inspection_section,
    src_ns.nspname AS source_schema,
    src.relname AS source_table,
    con.conname AS constraint_name,
    src_col.attname AS source_column,
    ref_ns.nspname AS referenced_schema,
    ref.relname AS referenced_table,
    ref_col.attname AS referenced_column,
    CASE con.confupdtype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
        ELSE con.confupdtype::text
    END AS on_update_action,
    CASE con.confdeltype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
        ELSE con.confdeltype::text
    END AS on_delete_action,
    src_key.position AS column_position
FROM pg_constraint AS con
JOIN pg_class AS src
  ON src.oid = con.conrelid
JOIN pg_namespace AS src_ns
  ON src_ns.oid = src.relnamespace
JOIN pg_class AS ref
  ON ref.oid = con.confrelid
JOIN pg_namespace AS ref_ns
  ON ref_ns.oid = ref.relnamespace
JOIN LATERAL unnest(con.conkey)
    WITH ORDINALITY AS src_key(attnum, position)
  ON true
JOIN LATERAL unnest(con.confkey)
    WITH ORDINALITY AS ref_key(attnum, position)
  ON ref_key.position = src_key.position
JOIN pg_attribute AS src_col
  ON src_col.attrelid = src.oid
 AND src_col.attnum = src_key.attnum
JOIN pg_attribute AS ref_col
  ON ref_col.attrelid = ref.oid
 AND ref_col.attnum = ref_key.attnum
WHERE con.contype = 'f'
  AND src_ns.nspname = 'public'
  AND src.relname IN ('agent_actions', 'crm_leads')
ORDER BY src.relname, con.conname, src_key.position;


-- ============================================================================
-- 5. INDEXES
-- ============================================================================
SELECT
    '5. indexes' AS inspection_section,
    ns.nspname AS schema_name,
    tbl.relname AS table_name,
    idx.relname AS index_name,
    ind.indisunique AS is_unique,
    ind.indisprimary AS is_primary,
    pg_get_indexdef(ind.indexrelid) AS index_definition,
    pg_get_expr(ind.indpred, ind.indrelid, true) AS partial_predicate
FROM pg_index AS ind
JOIN pg_class AS tbl
  ON tbl.oid = ind.indrelid
JOIN pg_namespace AS ns
  ON ns.oid = tbl.relnamespace
JOIN pg_class AS idx
  ON idx.oid = ind.indexrelid
WHERE ns.nspname = 'public'
  AND tbl.relname IN ('agent_actions', 'crm_leads')
ORDER BY tbl.relname, idx.relname;


-- ============================================================================
-- 6. TRIGGERS
-- Internal constraint triggers are excluded.
-- ============================================================================
SELECT
    '6. triggers' AS inspection_section,
    tbl_ns.nspname AS schema_name,
    tbl.relname AS table_name,
    trg.tgname AS trigger_name,
    CASE trg.tgenabled
        WHEN 'O' THEN 'enabled'
        WHEN 'D' THEN 'disabled'
        WHEN 'R' THEN 'replica'
        WHEN 'A' THEN 'always'
        ELSE trg.tgenabled::text
    END AS enabled_status,
    CASE
        WHEN (trg.tgtype & 2) = 2 THEN 'BEFORE'
        WHEN (trg.tgtype & 64) = 64 THEN 'INSTEAD OF'
        ELSE 'AFTER'
    END AS trigger_timing,
    concat_ws(
        ', ',
        CASE WHEN (trg.tgtype & 4) = 4 THEN 'INSERT' END,
        CASE WHEN (trg.tgtype & 8) = 8 THEN 'DELETE' END,
        CASE WHEN (trg.tgtype & 16) = 16 THEN 'UPDATE' END,
        CASE WHEN (trg.tgtype & 32) = 32 THEN 'TRUNCATE' END
    ) AS trigger_events,
    pg_get_triggerdef(trg.oid, true) AS trigger_definition,
    fn_ns.nspname AS trigger_function_schema,
    fn.proname AS trigger_function_name
FROM pg_trigger AS trg
JOIN pg_class AS tbl
  ON tbl.oid = trg.tgrelid
JOIN pg_namespace AS tbl_ns
  ON tbl_ns.oid = tbl.relnamespace
JOIN pg_proc AS fn
  ON fn.oid = trg.tgfoid
JOIN pg_namespace AS fn_ns
  ON fn_ns.oid = fn.pronamespace
WHERE tbl_ns.nspname = 'public'
  AND tbl.relname IN ('agent_actions', 'crm_leads')
  AND NOT trg.tgisinternal
ORDER BY tbl.relname, trg.tgname;


-- ============================================================================
-- 7. TRIGGER-FUNCTION DEFINITIONS
-- Definitions are displayed only; functions are not invoked.
-- ============================================================================
SELECT DISTINCT
    '7. trigger-function definitions' AS inspection_section,
    fn_ns.nspname AS function_schema,
    fn.proname AS function_name,
    pg_get_function_identity_arguments(fn.oid) AS arguments,
    pg_get_userbyid(fn.proowner) AS function_owner,
    CASE WHEN fn.prosecdef THEN 'security definer' ELSE 'security invoker' END
        AS security_mode,
    pg_get_functiondef(fn.oid) AS function_definition
FROM pg_trigger AS trg
JOIN pg_class AS tbl
  ON tbl.oid = trg.tgrelid
JOIN pg_namespace AS tbl_ns
  ON tbl_ns.oid = tbl.relnamespace
JOIN pg_proc AS fn
  ON fn.oid = trg.tgfoid
JOIN pg_namespace AS fn_ns
  ON fn_ns.oid = fn.pronamespace
WHERE tbl_ns.nspname = 'public'
  AND tbl.relname IN ('agent_actions', 'crm_leads')
  AND NOT trg.tgisinternal
ORDER BY function_schema, function_name, arguments;


-- ============================================================================
-- 8. RLS POLICIES
-- ============================================================================
SELECT
    '8. RLS policies' AS inspection_section,
    pol.schemaname AS schema_name,
    pol.tablename AS table_name,
    pol.policyname AS policy_name,
    pol.permissive,
    pol.cmd AS command,
    pol.roles,
    pol.qual AS using_expression,
    pol.with_check AS with_check_expression
FROM pg_policies AS pol
WHERE pol.schemaname = 'public'
  AND pol.tablename IN ('agent_actions', 'crm_leads')
ORDER BY pol.tablename, pol.policyname;


-- ============================================================================
-- 9A. EXPLICIT TABLE PRIVILEGES
-- Includes PUBLIC, owners/default ACLs, named Supabase roles, and other grantees.
-- ============================================================================
SELECT
    '9A. explicit table privileges' AS inspection_section,
    ns.nspname AS schema_name,
    cls.relname AS table_name,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    pg_get_userbyid(acl.grantor) AS grantor,
    acl.privilege_type,
    acl.is_grantable
FROM pg_class AS cls
JOIN pg_namespace AS ns
  ON ns.oid = cls.relnamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(cls.relacl, '{}'::aclitem[])
) AS acl
WHERE ns.nspname = 'public'
  AND cls.relname IN ('agent_actions', 'crm_leads')
  AND cls.relkind IN ('r', 'p')
ORDER BY cls.relname, grantee, acl.privilege_type;


-- ============================================================================
-- 9B. EFFECTIVE TABLE PRIVILEGES FOR PRESENT SUPABASE ROLES
-- Roles absent from the live cluster do not produce rows.
-- ============================================================================
SELECT
    '9B. effective table privileges' AS inspection_section,
    ns.nspname AS schema_name,
    cls.relname AS table_name,
    roles.rolname AS role_name,
    has_table_privilege(roles.oid, cls.oid, 'SELECT') AS can_select,
    has_table_privilege(roles.oid, cls.oid, 'INSERT') AS can_insert,
    has_table_privilege(roles.oid, cls.oid, 'UPDATE') AS can_update,
    has_table_privilege(roles.oid, cls.oid, 'DELETE') AS can_delete,
    has_table_privilege(roles.oid, cls.oid, 'TRUNCATE') AS can_truncate,
    has_table_privilege(roles.oid, cls.oid, 'REFERENCES') AS can_reference,
    has_table_privilege(roles.oid, cls.oid, 'TRIGGER') AS can_trigger
FROM pg_class AS cls
JOIN pg_namespace AS ns
  ON ns.oid = cls.relnamespace
CROSS JOIN pg_roles AS roles
WHERE ns.nspname = 'public'
  AND cls.relname IN ('agent_actions', 'crm_leads')
  AND cls.relkind IN ('r', 'p')
  AND roles.rolname IN ('postgres', 'anon', 'authenticated', 'service_role')
ORDER BY cls.relname, roles.rolname;


-- ============================================================================
-- 9C. RELATED SEQUENCE PRIVILEGES
-- Finds sequences owned by columns on either target table.
-- ============================================================================
WITH target_tables AS (
    SELECT cls.oid
    FROM pg_class AS cls
    JOIN pg_namespace AS ns
      ON ns.oid = cls.relnamespace
    WHERE ns.nspname = 'public'
      AND cls.relname IN ('agent_actions', 'crm_leads')
), related_sequences AS (
    SELECT DISTINCT seq.oid, seq.relname, seq.relowner, seq.relacl, seq_ns.nspname
    FROM pg_depend AS dep
    JOIN target_tables AS tbl
      ON tbl.oid = dep.refobjid
    JOIN pg_class AS seq
      ON seq.oid = dep.objid
     AND seq.relkind = 'S'
    JOIN pg_namespace AS seq_ns
      ON seq_ns.oid = seq.relnamespace
    WHERE dep.deptype IN ('a', 'i')
)
SELECT
    '9C. explicit related sequence privileges' AS inspection_section,
    seq.nspname AS sequence_schema,
    seq.relname AS sequence_name,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    pg_get_userbyid(acl.grantor) AS grantor,
    acl.privilege_type,
    acl.is_grantable
FROM related_sequences AS seq
CROSS JOIN LATERAL aclexplode(
    COALESCE(seq.relacl, '{}'::aclitem[])
) AS acl
ORDER BY seq.relname, grantee, acl.privilege_type;


WITH target_tables AS (
    SELECT cls.oid
    FROM pg_class AS cls
    JOIN pg_namespace AS ns
      ON ns.oid = cls.relnamespace
    WHERE ns.nspname = 'public'
      AND cls.relname IN ('agent_actions', 'crm_leads')
), related_sequences AS (
    SELECT DISTINCT seq.oid, seq.relname, seq_ns.nspname
    FROM pg_depend AS dep
    JOIN target_tables AS tbl
      ON tbl.oid = dep.refobjid
    JOIN pg_class AS seq
      ON seq.oid = dep.objid
     AND seq.relkind = 'S'
    JOIN pg_namespace AS seq_ns
      ON seq_ns.oid = seq.relnamespace
    WHERE dep.deptype IN ('a', 'i')
)
SELECT
    '9C. effective related sequence privileges' AS inspection_section,
    seq.nspname AS sequence_schema,
    seq.relname AS sequence_name,
    roles.rolname AS role_name,
    has_sequence_privilege(roles.oid, seq.oid, 'USAGE') AS can_use,
    has_sequence_privilege(roles.oid, seq.oid, 'SELECT') AS can_select,
    has_sequence_privilege(roles.oid, seq.oid, 'UPDATE') AS can_update
FROM related_sequences AS seq
CROSS JOIN pg_roles AS roles
WHERE roles.rolname IN ('postgres', 'anon', 'authenticated', 'service_role')
ORDER BY seq.relname, roles.rolname;


-- ============================================================================
-- 9D AND 10. FUNCTIONS OR RPCS REFERENCING EITHER TARGET TABLE
-- The definition text is inspected but never executed.
-- ============================================================================
WITH function_definitions AS (
    SELECT
        fn.oid,
        fn.pronamespace,
        fn.proname,
        fn.proowner,
        fn.prosecdef,
        fn.proacl,
        pg_get_function_identity_arguments(fn.oid) AS arguments,
        pg_get_function_result(fn.oid) AS return_type,
        pg_get_functiondef(fn.oid) AS function_definition
    FROM pg_proc AS fn
    WHERE fn.prokind IN ('f', 'p')
), referencing_functions AS (
    SELECT defs.*
    FROM function_definitions AS defs
    WHERE defs.function_definition ILIKE '%agent_actions%'
       OR defs.function_definition ILIKE '%crm_leads%'
)
SELECT
    '10. functions referencing target tables' AS inspection_section,
    ns.nspname AS function_schema,
    refs.proname AS function_name,
    refs.arguments,
    refs.return_type,
    CASE WHEN refs.prosecdef THEN 'security definer' ELSE 'security invoker' END
        AS security_mode,
    pg_get_userbyid(refs.proowner) AS function_owner,
    refs.function_definition
FROM referencing_functions AS refs
JOIN pg_namespace AS ns
  ON ns.oid = refs.pronamespace
ORDER BY ns.nspname, refs.proname, refs.arguments;


WITH function_definitions AS (
    SELECT
        fn.oid,
        fn.pronamespace,
        fn.proname,
        fn.proowner,
        fn.proacl,
        pg_get_function_identity_arguments(fn.oid) AS arguments,
        pg_get_functiondef(fn.oid) AS function_definition
    FROM pg_proc AS fn
    WHERE fn.prokind IN ('f', 'p')
), referencing_functions AS (
    SELECT defs.*
    FROM function_definitions AS defs
    WHERE defs.function_definition ILIKE '%agent_actions%'
       OR defs.function_definition ILIKE '%crm_leads%'
)
SELECT
    '9D. explicit privileges on referencing functions' AS inspection_section,
    ns.nspname AS function_schema,
    refs.proname AS function_name,
    refs.arguments,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    pg_get_userbyid(acl.grantor) AS grantor,
    acl.privilege_type,
    acl.is_grantable
FROM referencing_functions AS refs
JOIN pg_namespace AS ns
  ON ns.oid = refs.pronamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(refs.proacl, '{}'::aclitem[])
) AS acl
ORDER BY ns.nspname, refs.proname, refs.arguments, grantee;


WITH function_definitions AS (
    SELECT
        fn.oid,
        fn.pronamespace,
        fn.proname,
        pg_get_function_identity_arguments(fn.oid) AS arguments,
        pg_get_functiondef(fn.oid) AS function_definition
    FROM pg_proc AS fn
    WHERE fn.prokind IN ('f', 'p')
), referencing_functions AS (
    SELECT defs.*
    FROM function_definitions AS defs
    WHERE defs.function_definition ILIKE '%agent_actions%'
       OR defs.function_definition ILIKE '%crm_leads%'
)
SELECT
    '9D. effective privileges on referencing functions' AS inspection_section,
    ns.nspname AS function_schema,
    refs.proname AS function_name,
    refs.arguments,
    roles.rolname AS role_name,
    has_function_privilege(roles.oid, refs.oid, 'EXECUTE') AS can_execute
FROM referencing_functions AS refs
JOIN pg_namespace AS ns
  ON ns.oid = refs.pronamespace
CROSS JOIN pg_roles AS roles
WHERE roles.rolname IN ('postgres', 'anon', 'authenticated', 'service_role')
ORDER BY ns.nspname, refs.proname, refs.arguments, roles.rolname;


-- ============================================================================
-- 11A. AGENT_ACTIONS AGGREGATE DATA QUALITY
-- Dependency: public.agent_actions, public.chatbots, and public.conversations.
-- Optional fields are read through to_jsonb; absent keys are treated as NULL.
-- No customer content, reason text, or payload content is selected.
-- ============================================================================
WITH actions AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'company_id' AS company_id_text,
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text,
        to_jsonb(row_data)->>'message_id' AS message_id_text,
        to_jsonb(row_data)->>'status' AS status_text,
        to_jsonb(row_data)->>'intent' AS intent_text,
        to_jsonb(row_data)->>'action_type' AS action_type_text,
        to_jsonb(row_data)->>'created_at' AS created_at_text
    FROM public.agent_actions AS row_data
), chatbots AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'company_id' AS company_id_text
    FROM public.chatbots AS row_data
), conversations AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text
    FROM public.conversations AS row_data
), conversation_chatbots AS (
    SELECT
        conv.id_text AS conversation_id_text,
        conv.chatbot_id_text,
        bot.company_id_text
    FROM conversations AS conv
    LEFT JOIN chatbots AS bot
      ON bot.id_text = conv.chatbot_id_text
)
SELECT
    '11A. agent_actions ownership and reference quality' AS inspection_section,
    count(*) AS total_rows,
    count(*) FILTER (
        WHERE act.company_id_text IS NULL OR btrim(act.company_id_text) = ''
    ) AS null_company_id_count,
    count(*) FILTER (
        WHERE act.company_id_text IS NOT NULL
          AND btrim(act.company_id_text) <> ''
          AND act.company_id_text !~ '^[1-9][0-9]*$'
    ) AS invalid_company_id_count,
    count(*) FILTER (
        WHERE act.chatbot_id_text IS NULL OR btrim(act.chatbot_id_text) = ''
    ) AS null_chatbot_id_count,
    count(*) FILTER (
        WHERE act.conversation_id_text IS NULL
           OR btrim(act.conversation_id_text) = ''
    ) AS null_conversation_id_count,
    count(*) FILTER (
        WHERE act.message_id_text IS NULL OR btrim(act.message_id_text) = ''
    ) AS null_message_id_count,
    count(*) FILTER (
        WHERE act.chatbot_id_text IS NOT NULL
          AND bot.id_text IS NULL
    ) AS chatbot_id_without_matching_chatbot_count,
    count(*) FILTER (
        WHERE bot.id_text IS NOT NULL
          AND act.company_id_text IS DISTINCT FROM bot.company_id_text
    ) AS company_id_not_matching_chatbot_count,
    count(*) FILTER (
        WHERE act.conversation_id_text IS NOT NULL
          AND conv.id_text IS NULL
    ) AS conversation_id_without_matching_conversation_count,
    count(*) FILTER (
        WHERE conv.id_text IS NOT NULL
          AND act.chatbot_id_text IS DISTINCT FROM conv.chatbot_id_text
    ) AS conversation_belongs_to_different_chatbot_count,
    count(*) FILTER (
        WHERE
            (
                bot.id_text IS NOT NULL
                AND act.company_id_text IS DISTINCT FROM bot.company_id_text
            )
            OR (
                conv_bot.conversation_id_text IS NOT NULL
                AND act.company_id_text IS DISTINCT FROM conv_bot.company_id_text
            )
            OR (
                bot.id_text IS NOT NULL
                AND conv_bot.conversation_id_text IS NOT NULL
                AND bot.company_id_text IS DISTINCT FROM conv_bot.company_id_text
            )
    ) AS company_mismatch_between_action_chatbot_conversation_count
FROM actions AS act
LEFT JOIN chatbots AS bot
  ON bot.id_text = act.chatbot_id_text
LEFT JOIN conversations AS conv
  ON conv.id_text = act.conversation_id_text
LEFT JOIN conversation_chatbots AS conv_bot
  ON conv_bot.conversation_id_text = act.conversation_id_text;


WITH actions AS (
    SELECT to_jsonb(row_data)->>'status' AS value
    FROM public.agent_actions AS row_data
)
SELECT
    '11A. agent_actions grouped by status' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(value)), ''), '<NULL_OR_EMPTY>') AS status,
    count(*) AS row_count
FROM actions
GROUP BY COALESCE(NULLIF(lower(btrim(value)), ''), '<NULL_OR_EMPTY>')
ORDER BY row_count DESC, status;


WITH actions AS (
    SELECT to_jsonb(row_data)->>'intent' AS value
    FROM public.agent_actions AS row_data
)
SELECT
    '11A. agent_actions grouped by intent' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(value)), ''), '<NULL_OR_EMPTY>') AS intent,
    count(*) AS row_count
FROM actions
GROUP BY COALESCE(NULLIF(lower(btrim(value)), ''), '<NULL_OR_EMPTY>')
ORDER BY row_count DESC, intent;


WITH actions AS (
    SELECT to_jsonb(row_data)->>'action_type' AS value
    FROM public.agent_actions AS row_data
)
SELECT
    '11A. agent_actions grouped by action_type' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(value)), ''), '<NULL_OR_EMPTY>') AS action_type,
    count(*) AS row_count
FROM actions
GROUP BY COALESCE(NULLIF(lower(btrim(value)), ''), '<NULL_OR_EMPTY>')
ORDER BY row_count DESC, action_type;


-- Dependency: agent_actions.created_at must be timestamp-compatible when present.
WITH actions AS (
    SELECT to_jsonb(row_data)->>'created_at' AS created_at_text
    FROM public.agent_actions AS row_data
)
SELECT
    '11A. agent_actions grouped by created month' AS inspection_section,
    date_trunc('month', created_at_text::timestamptz) AS created_month,
    count(*) AS row_count
FROM actions
WHERE created_at_text IS NOT NULL
  AND btrim(created_at_text) <> ''
GROUP BY date_trunc('month', created_at_text::timestamptz)
ORDER BY created_month;


WITH actions AS (
    SELECT
        to_jsonb(row_data)->>'status' AS status_text,
        to_jsonb(row_data)->>'intent' AS intent_text
    FROM public.agent_actions AS row_data
)
SELECT
    '11A. agent_actions unexpected status values' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>')
        AS unexpected_value,
    count(*) AS row_count
FROM actions
WHERE COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>')
      NOT IN ('detected', 'resolved')
GROUP BY COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>')
UNION ALL
SELECT
    '11A. agent_actions unexpected intent values' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(intent_text)), ''), '<NULL_OR_EMPTY>')
        AS unexpected_value,
    count(*) AS row_count
FROM actions
WHERE COALESCE(NULLIF(lower(btrim(intent_text)), ''), '<NULL_OR_EMPTY>')
      NOT IN (
          'greeting',
          'general_question',
          'lead_interest',
          'handoff_request',
          'complaint',
          'knowledge_gap',
          'unknown'
      )
GROUP BY COALESCE(NULLIF(lower(btrim(intent_text)), ''), '<NULL_OR_EMPTY>')
ORDER BY inspection_section, row_count DESC, unexpected_value;


-- Duplicate-looking means the same chatbot, conversation, intent, and action
-- type within the same one-minute bucket. This does not prove duplication.
WITH actions AS (
    SELECT
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text,
        to_jsonb(row_data)->>'intent' AS intent_text,
        to_jsonb(row_data)->>'action_type' AS action_type_text,
        to_jsonb(row_data)->>'created_at' AS created_at_text
    FROM public.agent_actions AS row_data
)
SELECT
    '11A. duplicate-looking agent_actions' AS inspection_section,
    chatbot_id_text AS chatbot_id,
    conversation_id_text AS conversation_id,
    intent_text AS intent,
    action_type_text AS action_type,
    date_trunc('minute', created_at_text::timestamptz) AS created_minute,
    count(*) AS row_count
FROM actions
WHERE chatbot_id_text IS NOT NULL
  AND conversation_id_text IS NOT NULL
  AND created_at_text IS NOT NULL
  AND btrim(created_at_text) <> ''
GROUP BY
    chatbot_id_text,
    conversation_id_text,
    intent_text,
    action_type_text,
    date_trunc('minute', created_at_text::timestamptz)
HAVING count(*) > 1
ORDER BY row_count DESC, created_minute DESC
LIMIT 100;


-- ============================================================================
-- 11B. CRM_LEADS AGGREGATE DATA QUALITY
-- Dependency: public.crm_leads, public.chatbots, and public.conversations.
-- Optional fields are read through to_jsonb; absent keys are treated as NULL.
-- No customer names, phones, notes, summaries, or other content is selected.
-- ============================================================================
WITH leads AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'company_id' AS company_id_text,
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text
    FROM public.crm_leads AS row_data
), chatbots AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'company_id' AS company_id_text
    FROM public.chatbots AS row_data
), conversations AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text
    FROM public.conversations AS row_data
), conversation_chatbots AS (
    SELECT
        conv.id_text AS conversation_id_text,
        conv.chatbot_id_text,
        bot.company_id_text
    FROM conversations AS conv
    LEFT JOIN chatbots AS bot
      ON bot.id_text = conv.chatbot_id_text
)
SELECT
    '11B. crm_leads ownership and reference quality' AS inspection_section,
    count(*) AS total_rows,
    count(*) FILTER (
        WHERE lead.company_id_text IS NULL OR btrim(lead.company_id_text) = ''
    ) AS null_company_id_count,
    count(*) FILTER (
        WHERE lead.chatbot_id_text IS NULL OR btrim(lead.chatbot_id_text) = ''
    ) AS null_chatbot_id_count,
    count(*) FILTER (
        WHERE lead.conversation_id_text IS NULL
           OR btrim(lead.conversation_id_text) = ''
    ) AS null_conversation_id_count,
    count(*) FILTER (
        WHERE lead.chatbot_id_text IS NOT NULL
          AND bot.id_text IS NULL
    ) AS chatbot_id_without_matching_chatbot_count,
    count(*) FILTER (
        WHERE bot.id_text IS NOT NULL
          AND lead.company_id_text IS DISTINCT FROM bot.company_id_text
    ) AS company_id_not_matching_chatbot_count,
    count(*) FILTER (
        WHERE lead.conversation_id_text IS NOT NULL
          AND conv.id_text IS NULL
    ) AS conversation_id_without_matching_conversation_count,
    count(*) FILTER (
        WHERE conv.id_text IS NOT NULL
          AND lead.chatbot_id_text IS DISTINCT FROM conv.chatbot_id_text
    ) AS conversation_belongs_to_different_chatbot_count,
    count(*) FILTER (
        WHERE
            (
                bot.id_text IS NOT NULL
                AND lead.company_id_text IS DISTINCT FROM bot.company_id_text
            )
            OR (
                conv_bot.conversation_id_text IS NOT NULL
                AND lead.company_id_text IS DISTINCT FROM conv_bot.company_id_text
            )
            OR (
                bot.id_text IS NOT NULL
                AND conv_bot.conversation_id_text IS NOT NULL
                AND bot.company_id_text IS DISTINCT FROM conv_bot.company_id_text
            )
    ) AS company_mismatch_between_lead_chatbot_conversation_count
FROM leads AS lead
LEFT JOIN chatbots AS bot
  ON bot.id_text = lead.chatbot_id_text
LEFT JOIN conversations AS conv
  ON conv.id_text = lead.conversation_id_text
LEFT JOIN conversation_chatbots AS conv_bot
  ON conv_bot.conversation_id_text = lead.conversation_id_text;


WITH leads AS (
    SELECT
        to_jsonb(row_data)->>'status' AS status_text,
        to_jsonb(row_data)->>'lead_type' AS lead_type_text,
        to_jsonb(row_data)->>'priority' AS priority_text
    FROM public.crm_leads AS row_data
)
SELECT
    '11B. crm_leads grouped by status' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>') AS value,
    count(*) AS row_count
FROM leads
GROUP BY COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>')
UNION ALL
SELECT
    '11B. crm_leads grouped by lead_type' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(lead_type_text)), ''), '<NULL_OR_EMPTY>') AS value,
    count(*) AS row_count
FROM leads
GROUP BY COALESCE(NULLIF(lower(btrim(lead_type_text)), ''), '<NULL_OR_EMPTY>')
UNION ALL
SELECT
    '11B. crm_leads grouped by priority' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(priority_text)), ''), '<NULL_OR_EMPTY>') AS value,
    count(*) AS row_count
FROM leads
GROUP BY COALESCE(NULLIF(lower(btrim(priority_text)), ''), '<NULL_OR_EMPTY>')
ORDER BY inspection_section, row_count DESC, value;


-- Dependency: crm_leads.created_at must be timestamp-compatible when present.
WITH leads AS (
    SELECT to_jsonb(row_data)->>'created_at' AS created_at_text
    FROM public.crm_leads AS row_data
)
SELECT
    '11B. crm_leads grouped by created month' AS inspection_section,
    date_trunc('month', created_at_text::timestamptz) AS created_month,
    count(*) AS row_count
FROM leads
WHERE created_at_text IS NOT NULL
  AND btrim(created_at_text) <> ''
GROUP BY date_trunc('month', created_at_text::timestamptz)
ORDER BY created_month;


WITH leads AS (
    SELECT
        to_jsonb(row_data)->>'status' AS status_text,
        to_jsonb(row_data)->>'priority' AS priority_text,
        to_jsonb(row_data)->>'lead_type' AS lead_type_text
    FROM public.crm_leads AS row_data
)
SELECT
    '11B. crm_leads unexpected status values' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>')
        AS unexpected_value,
    count(*) AS row_count
FROM leads
WHERE COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>')
      NOT IN ('new', 'in_progress', 'contacted', 'closed')
GROUP BY COALESCE(NULLIF(lower(btrim(status_text)), ''), '<NULL_OR_EMPTY>')
UNION ALL
SELECT
    '11B. crm_leads unexpected priority values' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(priority_text)), ''), '<NULL_OR_EMPTY>')
        AS unexpected_value,
    count(*) AS row_count
FROM leads
WHERE COALESCE(NULLIF(lower(btrim(priority_text)), ''), '<NULL_OR_EMPTY>')
      NOT IN ('low', 'medium', 'high')
GROUP BY COALESCE(NULLIF(lower(btrim(priority_text)), ''), '<NULL_OR_EMPTY>')
UNION ALL
SELECT
    '11B. crm_leads unexpected lead_type values' AS inspection_section,
    COALESCE(NULLIF(lower(btrim(lead_type_text)), ''), '<NULL_OR_EMPTY>')
        AS unexpected_value,
    count(*) AS row_count
FROM leads
WHERE COALESCE(NULLIF(lower(btrim(lead_type_text)), ''), '<NULL_OR_EMPTY>')
      NOT IN ('follow_up', 'staff_attention', 'negative_feedback')
GROUP BY COALESCE(NULLIF(lower(btrim(lead_type_text)), ''), '<NULL_OR_EMPTY>')
ORDER BY inspection_section, row_count DESC, unexpected_value;


WITH leads AS (
    SELECT
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text,
        lower(btrim(to_jsonb(row_data)->>'status')) AS status_text
    FROM public.crm_leads AS row_data
)
SELECT
    '11B. open duplicate crm_leads' AS inspection_section,
    chatbot_id_text AS chatbot_id,
    conversation_id_text AS conversation_id,
    count(*) AS open_lead_count
FROM leads
WHERE status_text IN ('new', 'in_progress', 'contacted')
  AND chatbot_id_text IS NOT NULL
  AND conversation_id_text IS NOT NULL
GROUP BY chatbot_id_text, conversation_id_text
HAVING count(*) > 1
ORDER BY open_lead_count DESC, chatbot_id, conversation_id
LIMIT 100;


-- ============================================================================
-- 12. CROSS-TABLE RELATIONSHIP CHECKS
-- These are inferred matches on chatbot_id plus conversation_id. This section
-- does not assert that a direct foreign key exists between the two tables.
-- Dependencies: both target tables and created_at/status/intent keys.
-- ============================================================================
WITH actions AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text,
        lower(btrim(to_jsonb(row_data)->>'status')) AS status_text,
        lower(btrim(to_jsonb(row_data)->>'intent')) AS intent_text,
        to_jsonb(row_data)->>'created_at' AS created_at_text
    FROM public.agent_actions AS row_data
), leads AS (
    SELECT
        to_jsonb(row_data)->>'id' AS id_text,
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text,
        lower(btrim(to_jsonb(row_data)->>'status')) AS status_text,
        to_jsonb(row_data)->>'created_at' AS created_at_text,
        COALESCE(
            to_jsonb(row_data)->>'updated_at',
            to_jsonb(row_data)->>'created_at'
        ) AS closed_reference_at_text
    FROM public.crm_leads AS row_data
), action_conversations AS (
    SELECT DISTINCT chatbot_id_text, conversation_id_text
    FROM actions
    WHERE chatbot_id_text IS NOT NULL
      AND conversation_id_text IS NOT NULL
), lead_conversations AS (
    SELECT DISTINCT chatbot_id_text, conversation_id_text
    FROM leads
    WHERE chatbot_id_text IS NOT NULL
      AND conversation_id_text IS NOT NULL
), open_leads AS (
    SELECT *
    FROM leads
    WHERE status_text IN ('new', 'in_progress', 'contacted')
)
SELECT
    '12. conversations with both agent actions and CRM leads' AS inspection_section,
    count(*) AS aggregate_count
FROM action_conversations AS act
JOIN lead_conversations AS lead
  ON lead.chatbot_id_text = act.chatbot_id_text
 AND lead.conversation_id_text = act.conversation_id_text
UNION ALL
SELECT
    '12. agent-action conversations with no CRM lead',
    count(*)
FROM action_conversations AS act
LEFT JOIN lead_conversations AS lead
  ON lead.chatbot_id_text = act.chatbot_id_text
 AND lead.conversation_id_text = act.conversation_id_text
WHERE lead.conversation_id_text IS NULL
UNION ALL
SELECT
    '12. CRM-lead conversations with no agent action',
    count(*)
FROM lead_conversations AS lead
LEFT JOIN action_conversations AS act
  ON act.chatbot_id_text = lead.chatbot_id_text
 AND act.conversation_id_text = lead.conversation_id_text
WHERE act.conversation_id_text IS NULL
UNION ALL
SELECT
    '12. agent actions on conversations with an open CRM lead',
    count(*)
FROM actions AS act
WHERE EXISTS (
    SELECT 1
    FROM open_leads AS lead
    WHERE lead.chatbot_id_text = act.chatbot_id_text
      AND lead.conversation_id_text = act.conversation_id_text
)
UNION ALL
SELECT
    '12. lead-interest or negative-feedback signals with an inferred CRM lead',
    count(*)
FROM actions AS act
WHERE act.intent_text IN ('lead_interest', 'complaint')
  AND EXISTS (
      SELECT 1
      FROM leads AS lead
      WHERE lead.chatbot_id_text = act.chatbot_id_text
        AND lead.conversation_id_text = act.conversation_id_text
  )
UNION ALL
SELECT
    '12. detected handoff or knowledge-gap signals with an inferred CRM lead',
    count(*)
FROM actions AS act
WHERE act.status_text = 'detected'
  AND act.intent_text IN ('handoff_request', 'knowledge_gap')
  AND EXISTS (
      SELECT 1
      FROM leads AS lead
      WHERE lead.chatbot_id_text = act.chatbot_id_text
        AND lead.conversation_id_text = act.conversation_id_text
  )
UNION ALL
SELECT
    '12. closed leads with later detected signals',
    count(*)
FROM leads AS lead
WHERE lead.status_text = 'closed'
  AND EXISTS (
      SELECT 1
      FROM actions AS act
      WHERE act.chatbot_id_text = lead.chatbot_id_text
        AND act.conversation_id_text = lead.conversation_id_text
        AND act.status_text = 'detected'
        AND act.created_at_text::timestamptz
            > lead.closed_reference_at_text::timestamptz
  )
UNION ALL
SELECT
    '12. unresolved signals linked by conversation to closed leads',
    count(*)
FROM actions AS act
WHERE act.status_text = 'detected'
  AND EXISTS (
      SELECT 1
      FROM leads AS lead
      WHERE lead.chatbot_id_text = act.chatbot_id_text
        AND lead.conversation_id_text = act.conversation_id_text
        AND lead.status_text = 'closed'
  )
ORDER BY inspection_section;


-- Multiple actions associated with one open lead, grouped without row content.
WITH actions AS (
    SELECT
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text
    FROM public.agent_actions AS row_data
), open_leads AS (
    SELECT
        to_jsonb(row_data)->>'id' AS lead_id_text,
        to_jsonb(row_data)->>'chatbot_id' AS chatbot_id_text,
        to_jsonb(row_data)->>'conversation_id' AS conversation_id_text
    FROM public.crm_leads AS row_data
    WHERE lower(btrim(to_jsonb(row_data)->>'status'))
          IN ('new', 'in_progress', 'contacted')
)
SELECT
    '12. multiple agent actions associated with one open CRM lead'
        AS inspection_section,
    lead.chatbot_id_text AS chatbot_id,
    lead.conversation_id_text AS conversation_id,
    lead.lead_id_text AS lead_id,
    count(*) AS agent_action_count
FROM open_leads AS lead
JOIN actions AS act
  ON act.chatbot_id_text = lead.chatbot_id_text
 AND act.conversation_id_text = lead.conversation_id_text
GROUP BY lead.chatbot_id_text, lead.conversation_id_text, lead.lead_id_text
HAVING count(*) > 1
ORDER BY agent_action_count DESC, chatbot_id, conversation_id
LIMIT 100;


-- ============================================================================
-- 13. ROW-LEVEL SAMPLE IDENTIFIERS
-- Omitted intentionally. Aggregate output should be reviewed first. If a
-- later investigation needs identifiers, use a separately reviewed query
-- limited to the non-sensitive identifier fields approved in the runbook.
-- ============================================================================
