/*
READ-ONLY REVIEW SCRIPT

Purpose: preflight public.bot_configs before applying
data/039_unify_bot_config_persona_fields.sql. Run this file in the Supabase SQL
Editor and attach every result set to the change record.

Why this file exists: 031's prerequisite was written as `\d+ public.bot_configs`,
which is a psql meta-command. Migrations in this repository are applied through
the Supabase SQL Editor (docs/PHASE_4F_OPERATIONS_RUNBOOK.md:21,
docs/PLATFORM_ADMIN_PRODUCTION_DEPLOYMENT_RUNBOOK.md:223), which cannot run
meta-commands. Sections 1-4 below reproduce everything `\d+` would have shown,
plus the dependency evidence `\d+` does NOT show.

There is no CREATE TABLE for public.bot_configs anywhere in this repository, so
this script is the only way to learn the relation's real shape.

This script contains only SELECT/WITH catalog and aggregate queries. It does not
change schema, privileges, policies, functions, or data.

CUSTOMER CONTENT WARNING: section 10 returns tenant business text, not just
identifiers. Route its output to the restricted archive used for migration 028
manifests, not into a ticket or chat transcript.

WHAT MUST BE TRUE BEFORE 031 IS APPLIED
  A. Section 2: record attnotnull for business_objective, response_style and
     prompt_text. This is the ONLY record of what 031 step 2 relaxes, and the
     rollback's commented-out SET NOT NULL block cannot be uncommented without
     it.
  B. Section 3: no CHECK constraint may express not-null-ness for a legacy
     column (e.g. `CHECK (prompt_text IS NOT NULL)`). ALTER COLUMN DROP NOT NULL
     does NOT remove a CHECK constraint, so 031 would commit successfully and
     the application deploy would then fail every write with 23514.
  C. Section 2: domain_forces_not_null must be false for the legacy columns. A
     domain-level NOT NULL survives DROP NOT NULL and rejects NULL with 23502.
  D. Section 2: generated_kind must be blank for all six columns. A stored
     generated column cannot be assigned by the backfill (42601).
  E. Section 5: no trigger may re-mirror or reject NULL on a legacy column. A
     BEFORE trigger doing `NEW.business_objective := NEW.business_description`
     would silently defeat the entire change while every unit test still passes.
  F. Section 4: no legacy column may sit in the primary key or in the index
     named by REPLICA IDENTITY USING INDEX; DROP NOT NULL errors in both cases.
     Also confirm no unique index over a legacy column uses NULLS NOT DISTINCT,
     which would turn mass-NULLing into 23505 collisions.
  G. Sections 7-8: no view, materialized view or routine may read a legacy
     column. This is the only genuinely SILENT failure mode - such a consumer
     keeps answering, with NULL.
  H. Section 9: if anon or authenticated hold SELECT, an out-of-repo consumer
     may be reading the legacy columns over PostgREST.
  I. Section 10 must be exported before 031 is applied. Divergent legacy values
     are unrecoverable once the application code starts writing NULL.
*/

-- 1. Table identity, ownership, RLS posture, replica identity, size.
--    replica_identity 'i' means REPLICA IDENTITY USING INDEX -- cross-check
--    section 4 before running any DROP NOT NULL.
SELECT
    n.nspname                                        AS schema_name,
    c.relname                                        AS table_name,
    pg_get_userbyid(c.relowner)                      AS table_owner,
    c.relkind                                        AS relation_kind,
    c.relpersistence                                 AS persistence_type,
    c.reltuples::bigint                              AS estimated_row_count,
    c.relrowsecurity                                 AS rls_enabled,
    c.relforcerowsecurity                            AS rls_forced,
    c.relreplident                                   AS replica_identity,
    pg_size_pretty(pg_total_relation_size(c.oid))    AS total_size
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname = 'bot_configs'
  AND c.relkind IN ('r', 'p');

-- 2. Full column definition -- the `\d+` replacement, plus the three attributes
--    `\d+` hides (domain not-null, identity kind, generated kind).
--    is_not_null on the three legacy columns is the value the rollback needs.
SELECT
    a.attnum                                         AS ordinal,
    a.attname                                        AS column_name,
    format_type(a.atttypid, a.atttypmod)             AS data_type,
    t.typtype                                        AS type_kind,
    t.typnotnull                                     AS domain_forces_not_null,
    a.attnotnull                                     AS is_not_null,
    a.attidentity                                    AS identity_kind,
    a.attgenerated                                   AS generated_kind,
    pg_get_expr(d.adbin, d.adrelid)                  AS column_default,
    col_description(a.attrelid, a.attnum)            AS existing_comment
FROM pg_attribute AS a
JOIN pg_type AS t ON t.oid = a.atttypid
LEFT JOIN pg_attrdef AS d
       ON d.adrelid = a.attrelid
      AND d.adnum = a.attnum
WHERE a.attrelid = 'public.bot_configs'::regclass
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum;

-- 3. Every constraint on the table. Read each CHECK definition for a legacy
--    column name: DROP NOT NULL clears only the attnotnull flag, never a CHECK.
--    Also answers the open question of whether (chatbot_id, profile_name) is
--    unique -- both writers do read-then-insert without one.
SELECT
    con.conname                                      AS constraint_name,
    con.contype                                      AS constraint_type,
    pg_get_constraintdef(con.oid)                    AS constraint_definition,
    (
        SELECT array_agg(att.attname ORDER BY att.attnum)
        FROM pg_attribute AS att
        WHERE att.attrelid = con.conrelid
          AND att.attnum = ANY (con.conkey)
    )                                                AS constrained_columns
FROM pg_constraint AS con
WHERE con.conrelid = 'public.bot_configs'::regclass
ORDER BY con.contype, con.conname;

-- 4. Every index. index_definition renders NULLS NOT DISTINCT where present.
SELECT
    i.relname                                        AS index_name,
    x.indisprimary                                   AS is_primary_key,
    x.indisunique                                    AS is_unique,
    x.indisvalid                                     AS is_valid,
    x.indisreplident                                 AS is_replica_identity,
    pg_get_indexdef(x.indexrelid)                    AS index_definition
FROM pg_index AS x
JOIN pg_class AS i ON i.oid = x.indexrelid
WHERE x.indrelid = 'public.bot_configs'::regclass
ORDER BY i.relname;

-- 5. Triggers and their full function source. Read every body for the three
--    legacy names before believing the application's NULL write will stick.
SELECT
    tg.tgname                                        AS trigger_name,
    tg.tgenabled                                     AS trigger_enabled,
    p.proname                                        AS function_name,
    pg_get_triggerdef(tg.oid)                        AS trigger_definition,
    pg_get_functiondef(p.oid)                        AS function_source
FROM pg_trigger AS tg
JOIN pg_proc AS p ON p.oid = tg.tgfoid
WHERE tg.tgrelid = 'public.bot_configs'::regclass
  AND NOT tg.tgisinternal
ORDER BY tg.tgname;

-- 6. RLS policies. The backend uses the service-role key and bypasses RLS, so
--    a policy referencing a legacy column changes behaviour only for anon or
--    authenticated callers -- cross-check section 9.
SELECT
    pol.polname                                      AS policy_name,
    pol.polcmd                                       AS command,
    pol.polpermissive                                AS is_permissive,
    pg_get_expr(pol.polqual, pol.polrelid)           AS using_expression,
    pg_get_expr(pol.polwithcheck, pol.polrelid)      AS with_check_expression
FROM pg_policy AS pol
WHERE pol.polrelid = 'public.bot_configs'::regclass
ORDER BY pol.polname;

-- 7. Views and materialized views with a recorded column-level dependency on
--    public.bot_configs. Any row naming a legacy column is a silent breakage.
SELECT DISTINCT
    dep_ns.nspname                                   AS dependent_schema,
    dep.relname                                      AS dependent_object,
    dep.relkind                                      AS dependent_kind,
    src.attname                                      AS bot_configs_column
FROM pg_depend AS d
JOIN pg_rewrite AS rw ON rw.oid = d.objid
JOIN pg_class AS dep ON dep.oid = rw.ev_class
JOIN pg_namespace AS dep_ns ON dep_ns.oid = dep.relnamespace
JOIN pg_attribute AS src
       ON src.attrelid = d.refobjid
      AND src.attnum = d.refobjsubid
WHERE d.classid = 'pg_rewrite'::regclass
  AND d.refclassid = 'pg_class'::regclass
  AND d.refobjid = 'public.bot_configs'::regclass
  AND d.refobjsubid > 0
  AND dep.oid <> 'public.bot_configs'::regclass
ORDER BY 1, 2, 4;

-- 8. Text sweep for the legacy names anywhere in the database, including
--    schemas and routines this repository does not define. This is what
--    catches a hand-deployed create_guided_chatbot RPC -- the design at
--    .omx/plans/guided-chatbot-creation-architecture.md:585-587 writes all
--    three legacy mirror columns and would re-introduce the drift.
SELECT 'view'::text AS object_kind, schemaname AS schema_name, viewname AS object_name
FROM pg_views
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND definition ~ '(business_objective|response_style|prompt_text)'
UNION ALL
SELECT 'matview'::text, schemaname, matviewname
FROM pg_matviews
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND definition ~ '(business_objective|response_style|prompt_text)'
UNION ALL
SELECT 'routine'::text, n.nspname, p.proname
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND p.prosrc ~ '(business_objective|response_style|prompt_text)'
ORDER BY 1, 2, 3;

-- 9. Table privileges. anon or authenticated holding SELECT means an
--    out-of-repo PostgREST consumer may be reading the legacy columns.
SELECT
    grantee,
    privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name = 'bot_configs'
ORDER BY grantee, privilege_type;

-- 10. Impact counts. One row; paste it into the change record.
--     null_canonical_rows is the precondition for the rollback's commented-out
--     SET NOT NULL block: that block can only succeed if this count is 0.
--     space_only_canonical_rows are the rows where the migration's
--     btrim(x) = '' predicate is stricter than the application's Python
--     truthiness test, so they are the only rows whose SERVED value the
--     backfill can change.
SELECT
    count(*)                                                     AS total_rows,
    count(*) FILTER (
        WHERE (business_description IS NULL OR btrim(business_description) = '')
          AND btrim(coalesce(business_objective, '')) <> ''
    )                                          AS backfill_business_description,
    count(*) FILTER (
        WHERE (tone IS NULL OR btrim(tone) = '')
          AND btrim(coalesce(response_style, '')) <> ''
    )                                                        AS backfill_tone,
    count(*) FILTER (
        WHERE (custom_prompt IS NULL OR btrim(custom_prompt) = '')
          AND btrim(coalesce(prompt_text, '')) <> ''
    )                                               AS backfill_custom_prompt,
    count(*) FILTER (
        WHERE business_description IS DISTINCT FROM business_objective
           OR tone IS DISTINCT FROM response_style
           OR custom_prompt IS DISTINCT FROM prompt_text
    )                                                       AS divergent_rows,
    count(*) FILTER (
        WHERE business_description IS NULL
           OR tone IS NULL
           OR custom_prompt IS NULL
    )                                                  AS null_canonical_rows,
    count(*) FILTER (
        WHERE (business_description <> '' AND btrim(business_description) = '')
           OR (tone <> '' AND btrim(tone) = '')
           OR (custom_prompt <> '' AND btrim(custom_prompt) = '')
    )                                            AS space_only_canonical_rows
FROM public.bot_configs;

-- 11. DIVERGENCE MANIFEST -- CUSTOMER CONTENT. Export to the restricted
--     archive BEFORE applying 031 and record the export identifier, mirroring
--     the discipline in data/028_cleanup_orphan_crm_agent_actions.sql:9-16.
--     031 deliberately leaves these rows untouched, but the legacy value is
--     destroyed the first time the new application code saves the row, and the
--     rollback then overwrites it from the canonical column. This result set
--     is the only copy that will survive.
SELECT
    id,
    chatbot_id,
    profile_name,
    business_description,
    business_objective,
    tone,
    response_style,
    custom_prompt,
    prompt_text
FROM public.bot_configs
WHERE business_description IS DISTINCT FROM business_objective
   OR tone IS DISTINCT FROM response_style
   OR custom_prompt IS DISTINCT FROM prompt_text
ORDER BY id;
