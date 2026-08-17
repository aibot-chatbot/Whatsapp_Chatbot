/*
READ-ONLY REVIEW SCRIPT

Purpose: preflight public.chatbots and public.conversations before applying
data/041_conversation_graph_nodes.sql. Run this file in the Supabase SQL Editor
and attach every result set to the change record.

Why this file exists: 033 declares two inline foreign keys against tables that
have NO CREATE TABLE anywhere in this repository. Their column types, parent
keys and ON DELETE behaviour are assumed from the 029/030 convention, not
observed. Migrations here are applied through the Supabase SQL Editor
(docs/PHASE_4F_OPERATIONS_RUNBOOK.md:21,
docs/PLATFORM_ADMIN_PRODUCTION_DEPLOYMENT_RUNBOOK.md:223), which cannot run psql
meta-commands, so `\d+ public.conversations` is not available. This script is the
SELECT-only equivalent, following the precedent set by
scripts/bot_configs_persona_unification_preflight.sql.

This script contains only SELECT/WITH catalog queries. It does not change schema,
privileges, policies, functions, or data. It returns no customer content: every
result set is identifiers, types and counts.

Uses to_regclass() rather than ::regclass throughout so a missing relation
returns NULL instead of aborting the run.

WHAT MUST BE TRUE BEFORE 033 IS APPLIED
  A. Section 2: chatbots.id and conversations.id must both exist and must be an
     integer type (int2/int4/int8). 033 declares its FK columns as bigint.
     bigint referencing integer is legal -- PostgreSQL only requires an equality
     operator between the types, not identical types -- so int4 parents are fine.
     A uuid or text parent is NOT: 033 then fails at apply with 42804
     "foreign key constraint cannot be implemented / incompatible types".
  B. Section 3: each parent column must be covered by a PRIMARY KEY or UNIQUE
     constraint. Without one the FK fails with 42830 "there is no unique
     constraint matching given keys".
  C. Section 1: conversation_graph_nodes must NOT already exist. 033 uses
     CREATE TABLE IF NOT EXISTS, so a pre-existing relation of a different shape
     makes the whole statement a silent no-op and every CHECK, the UNIQUE key
     and both FKs are then absent while the migration reports success.
  D. Section 4: record conversations.chatbot_id's real name, type and
     nullability. This is the input to the composite foreign key that 033
     documents but deliberately does not create (see its "TENANCY IS NOT
     ENFORCED BY THIS SCHEMA" section). Note whether
     UNIQUE (id, chatbot_id) already exists on conversations.
  E. Section 6: record estimated row counts for conversations and chatbots.
     033's inline FKs take SHARE ROW EXCLUSIVE on both, which blocks writes for
     the duration of CREATE TABLE. The hold is instant, but the size tells you
     how much traffic is at stake if the lock has to wait.
  F. Section 7 must be empty, or apply in a window where it is. Any transaction
     older than a few seconds holding a lock on either parent will make 033's
     SET LOCAL lock_timeout = '5s' abort the migration -- which is the intended
     behaviour, not a failure. Re-run when this section is clear.
  G. Section 8: service_role must exist and must have rolbypassrls or rolsuper.
     033 enables RLS with no policies; if service_role does not bypass RLS the
     backend loses all access to the table the moment 033 is applied.
  H. Section 9: confirms whether Supabase's default privileges grant new public
     tables to anon and authenticated. 033 now revokes explicitly, so this is
     evidence for the change record rather than a gate.

NOTHING IN THIS SCRIPT NEEDS TO PASS FOR THE ROLLBACK. Rolling 033 back is
unconditional.
*/

-- 1. Do the three relations of interest exist, and what kind are they?
--    conversation_graph_nodes MUST come back NULL (gate C).
SELECT
    candidate.relation_name,
    to_regclass(candidate.relation_name)                    AS resolved_oid,
    c.relkind                                               AS relation_kind,
    c.relpersistence                                        AS persistence_type,
    c.relrowsecurity                                        AS rls_enabled,
    c.relforcerowsecurity                                   AS rls_forced,
    pg_get_userbyid(c.relowner)                             AS relation_owner
FROM (
    VALUES
        ('public.chatbots'),
        ('public.conversations'),
        ('public.conversation_graph_nodes')
) AS candidate(relation_name)
LEFT JOIN pg_class AS c ON c.oid = to_regclass(candidate.relation_name)
ORDER BY candidate.relation_name;

-- 2. Parent column types (gate A). data_type must be an integer type for both
--    id columns. Also captures conversations.chatbot_id for gate D.
SELECT
    target.relation_name,
    a.attname                                               AS column_name,
    format_type(a.atttypid, a.atttypmod)                    AS data_type,
    t.typname                                               AS base_type_name,
    a.attnotnull                                            AS is_not_null,
    a.attidentity                                           AS identity_kind,
    a.attgenerated                                          AS generated_kind,
    pg_get_expr(d.adbin, d.adrelid)                         AS column_default
FROM (
    VALUES
        ('public.chatbots',      'id'),
        ('public.conversations', 'id'),
        ('public.conversations', 'chatbot_id')
) AS target(relation_name, column_name)
JOIN pg_attribute AS a
       ON a.attrelid = to_regclass(target.relation_name)
      AND a.attname = target.column_name
      AND NOT a.attisdropped
JOIN pg_type AS t ON t.oid = a.atttypid
LEFT JOIN pg_attrdef AS d
       ON d.adrelid = a.attrelid
      AND d.adnum = a.attnum
ORDER BY target.relation_name, target.column_name;

-- 3. Parent keys (gate B). There must be a row here whose constrained_columns is
--    exactly {id} for each of chatbots and conversations.
SELECT
    n.nspname || '.' || rel.relname                         AS relation_name,
    con.conname                                             AS constraint_name,
    con.contype                                             AS constraint_type,
    pg_get_constraintdef(con.oid)                           AS constraint_definition,
    (
        SELECT array_agg(att.attname ORDER BY att.attnum)
        FROM pg_attribute AS att
        WHERE att.attrelid = con.conrelid
          AND att.attnum = ANY (con.conkey)
    )                                                       AS constrained_columns
FROM pg_constraint AS con
JOIN pg_class AS rel ON rel.oid = con.conrelid
JOIN pg_namespace AS n ON n.oid = rel.relnamespace
WHERE con.conrelid IN (
        to_regclass('public.chatbots'),
        to_regclass('public.conversations')
      )
  AND con.contype IN ('p', 'u')
ORDER BY relation_name, con.conname;

-- 4. Gate D: does UNIQUE (id, chatbot_id) already exist on conversations? If it
--    does, the composite tenancy foreign key documented in 033 costs nothing to
--    add and should be scheduled immediately. If not, it needs its own migration
--    and its own window (ACCESS EXCLUSIVE + full index build).
SELECT
    i.relname                                               AS index_name,
    x.indisunique                                           AS is_unique,
    x.indisvalid                                            AS is_valid,
    pg_get_indexdef(x.indexrelid)                           AS index_definition
FROM pg_index AS x
JOIN pg_class AS i ON i.oid = x.indexrelid
WHERE x.indrelid = to_regclass('public.conversations')
ORDER BY i.relname;

-- 5. Existing foreign keys ON public.conversations. Specifically: does
--    conversations.chatbot_id already cascade from chatbots? If it does, a
--    chatbot delete removes conversations first and 033's own chatbot_id cascade
--    usually finds nothing -- but the referential action still runs, which is
--    why idx_conversation_graph_nodes_chatbot exists. If it does NOT cascade,
--    conversation facts outlive nothing and the index matters more.
SELECT
    con.conname                                             AS constraint_name,
    pg_get_constraintdef(con.oid)                           AS constraint_definition,
    con.confdeltype                                         AS on_delete_action,
    con.convalidated                                        AS is_validated
FROM pg_constraint AS con
WHERE con.conrelid = to_regclass('public.conversations')
  AND con.contype = 'f'
ORDER BY con.conname;

-- 6. Gate E: how much traffic is behind the SHARE ROW EXCLUSIVE lock that 033's
--    inline foreign keys take on these two tables.
SELECT
    n.nspname || '.' || c.relname                           AS relation_name,
    c.reltuples::bigint                                     AS estimated_row_count,
    pg_size_pretty(pg_total_relation_size(c.oid))           AS total_size
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE c.oid IN (
        to_regclass('public.chatbots'),
        to_regclass('public.conversations')
      )
ORDER BY relation_name;

-- 7. Gate F: transactions currently holding a lock on either parent table. Any
--    row here older than a few seconds will make 033 abort on lock_timeout.
--    Re-run this section immediately before applying, not just once.
SELECT
    a.pid,
    a.state,
    now() - a.xact_start                                    AS transaction_age,
    now() - a.state_change                                  AS state_age,
    l.locktype,
    l.mode                                                  AS lock_mode,
    l.granted,
    n.nspname || '.' || c.relname                           AS locked_relation,
    left(a.query, 200)                                      AS query_prefix
FROM pg_locks AS l
JOIN pg_class AS c ON c.oid = l.relation
JOIN pg_namespace AS n ON n.oid = c.relnamespace
JOIN pg_stat_activity AS a ON a.pid = l.pid
WHERE l.relation IN (
        to_regclass('public.chatbots'),
        to_regclass('public.conversations')
      )
  AND a.pid <> pg_backend_pid()
ORDER BY transaction_age DESC NULLS LAST;

-- 8. Gate G: RLS bypass. 033 enables RLS and creates no policy, exactly as 030
--    does. That is only safe because service_role bypasses RLS.
SELECT
    rolname,
    rolsuper,
    rolbypassrls,
    rolcanlogin
FROM pg_roles
WHERE rolname IN ('service_role', 'authenticated', 'anon', 'postgres')
ORDER BY rolname;

-- 9. Gate H: default privileges on new objects in schema public. This is the
--    reason 033 revokes from anon/authenticated instead of relying on a new
--    table being private by default.
SELECT
    pg_get_userbyid(d.defaclrole)                           AS granting_role,
    n.nspname                                               AS schema_name,
    d.defaclobjtype                                         AS object_type,
    d.defaclacl                                             AS default_acl
FROM pg_default_acl AS d
LEFT JOIN pg_namespace AS n ON n.oid = d.defaclnamespace
WHERE n.nspname = 'public' OR n.nspname IS NULL
ORDER BY granting_role, object_type;

-- 10. Name collisions. All three must come back with a NULL/zero result, or 033
--     is not creating what it thinks it is creating.
SELECT
    'trigger function' AS object_kind,
    to_regprocedure('public.touch_conversation_graph_nodes_updated_at()')::text
                                                            AS existing_object
UNION ALL
SELECT
    'sequence',
    to_regclass('public.conversation_graph_nodes_id_seq')::text
UNION ALL
SELECT
    'index',
    to_regclass('public.idx_conversation_graph_nodes_chatbot')::text;

-- 11. Informational only: installed extensions and their schema. 033 depends on
--     none of these by design -- the keyword predicate is btree equality, never
--     LIKE/ILIKE -- so this exists to record whether pg_trgm happens to be
--     present, not to gate anything. If it is present, note that Supabase
--     installs extensions into the "extensions" schema, so any future operator
--     class reference needs that schema on the search_path.
SELECT
    e.extname                                               AS extension_name,
    n.nspname                                               AS installed_schema,
    e.extversion                                            AS installed_version
FROM pg_extension AS e
JOIN pg_namespace AS n ON n.oid = e.extnamespace
ORDER BY e.extname;
