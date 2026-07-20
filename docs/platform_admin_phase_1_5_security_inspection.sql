-- Phase 1.5 platform-admin security and staging inspection.
-- READ ONLY: every statement is SELECT-only.
--
-- Run before staging deployment and again after each approved staging migration.
-- Empty result sets for target-table queries are expected before migration 023.

-- 1. Environment identity. Record this output with the staging approval.
SELECT
    current_database() AS database_name,
    current_user AS session_user,
    session_user AS authenticated_session_user,
    current_setting('server_version') AS postgres_version;

-- 2. Detect target-table or sequence name collisions before deployment.
SELECT
    to_regclass('public.platform_admin_users') AS platform_admin_users,
    to_regclass('public.platform_admin_users_id_seq') AS platform_admin_users_id_seq,
    to_regclass('public.platform_admin_audit_events') AS platform_admin_audit_events,
    to_regclass('public.platform_admin_audit_events_id_seq') AS platform_admin_audit_events_id_seq;

-- 3. Relevant role attributes. service_role normally has BYPASSRLS in Supabase;
-- verify rather than assume. No password or secret data is returned.
SELECT
    rolname,
    rolsuper,
    rolinherit,
    rolcreaterole,
    rolcreatedb,
    rolcanlogin,
    rolreplication,
    rolbypassrls
FROM pg_roles
WHERE rolname IN (
    'anon',
    'authenticated',
    'service_role',
    'postgres',
    'supabase_admin'
)
ORDER BY rolname;

-- 4. Direct role memberships that could supply inherited privileges.
SELECT
    member_role.rolname AS member_role,
    inherited_role.rolname AS inherited_role,
    membership.admin_option,
    grantor_role.rolname AS granted_by
FROM pg_auth_members AS membership
JOIN pg_roles AS member_role
  ON member_role.oid = membership.member
JOIN pg_roles AS inherited_role
  ON inherited_role.oid = membership.roleid
LEFT JOIN pg_roles AS grantor_role
  ON grantor_role.oid = membership.grantor
WHERE member_role.rolname IN ('anon', 'authenticated', 'service_role')
   OR inherited_role.rolname IN ('anon', 'authenticated', 'service_role')
ORDER BY member_role.rolname, inherited_role.rolname;

-- 5. Target columns, exact types, defaults, and identity state after creation.
SELECT
    table_schema,
    table_name,
    ordinal_position,
    column_name,
    data_type,
    udt_schema,
    udt_name,
    is_nullable,
    column_default,
    is_identity,
    identity_generation
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
      'platform_admin_users',
      'platform_admin_audit_events'
  )
ORDER BY table_name, ordinal_position;

-- 6. Ownership and RLS state for dependencies and target tables.
SELECT
    namespace.nspname AS table_schema,
    relation.relname AS table_name,
    pg_get_userbyid(relation.relowner) AS table_owner,
    relation.relrowsecurity AS rls_enabled,
    relation.relforcerowsecurity AS rls_forced,
    relation.relkind AS relation_kind
FROM pg_class AS relation
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname IN (
      'users',
      'companies',
      'platform_admin_users',
      'platform_admin_users_id_seq',
      'platform_admin_audit_events',
      'platform_admin_audit_events_id_seq'
  )
ORDER BY relation.relname;

-- 7. Exact relation ACL entries. This reports direct ACLs for target tables and
-- identity sequences; role memberships from query 4 must be reviewed alongside it.
SELECT
    namespace.nspname AS object_schema,
    relation.relname AS object_name,
    CASE relation.relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned table'
        WHEN 'S' THEN 'sequence'
        ELSE relation.relkind::text
    END AS object_type,
    pg_get_userbyid(acl.grantor) AS grantor,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    acl.privilege_type,
    acl.is_grantable
FROM pg_class AS relation
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(
        relation.relacl,
        acldefault(
            CASE
                WHEN relation.relkind = 'S' THEN 'S'::"char"
                ELSE 'r'::"char"
            END,
            relation.relowner
        )
    )
) AS acl
WHERE namespace.nspname = 'public'
  AND relation.relname IN (
      'platform_admin_users',
      'platform_admin_users_id_seq',
      'platform_admin_audit_events',
      'platform_admin_audit_events_id_seq'
  )
ORDER BY object_name, grantee, privilege_type;

-- 8. Effective privileges for the three application-facing Supabase roles.
-- Each row appears only when the role exists in the inspected project.
SELECT
    role_row.rolname AS role_name,
    target.object_name,
    has_table_privilege(
        role_row.oid,
        resolved.object_oid,
        'SELECT'
    ) AS can_select,
    has_table_privilege(
        role_row.oid,
        resolved.object_oid,
        'INSERT'
    ) AS can_insert,
    has_table_privilege(
        role_row.oid,
        resolved.object_oid,
        'UPDATE'
    ) AS can_update,
    has_table_privilege(
        role_row.oid,
        resolved.object_oid,
        'DELETE'
    ) AS can_delete
FROM pg_roles AS role_row
CROSS JOIN (
    VALUES
        ('platform_admin_users'),
        ('platform_admin_audit_events')
) AS target(object_name)
CROSS JOIN LATERAL (
    SELECT to_regclass(format('public.%I', target.object_name))::oid AS object_oid
) AS resolved
WHERE role_row.rolname IN ('anon', 'authenticated', 'service_role')
  AND resolved.object_oid IS NOT NULL
ORDER BY role_name, target.object_name;

-- 8b. Effective identity-sequence privileges, including inherited privileges.
SELECT
    role_row.rolname AS role_name,
    target.object_name,
    has_sequence_privilege(
        role_row.oid,
        resolved.object_oid,
        'USAGE'
    ) AS can_use,
    has_sequence_privilege(
        role_row.oid,
        resolved.object_oid,
        'SELECT'
    ) AS can_select,
    has_sequence_privilege(
        role_row.oid,
        resolved.object_oid,
        'UPDATE'
    ) AS can_update
FROM pg_roles AS role_row
CROSS JOIN (
    VALUES
        ('platform_admin_users_id_seq'),
        ('platform_admin_audit_events_id_seq')
) AS target(object_name)
CROSS JOIN LATERAL (
    SELECT to_regclass(format('public.%I', target.object_name))::oid AS object_oid
) AS resolved
WHERE role_row.rolname IN ('anon', 'authenticated', 'service_role')
  AND resolved.object_oid IS NOT NULL
ORDER BY role_name, target.object_name;

-- 9. Default privileges that could grant access to future tables or sequences.
SELECT
    owner_role.rolname AS owner_role,
    CASE
        WHEN default_acl.defaclnamespace = 0 THEN 'all schemas'
        ELSE default_acl.defaclnamespace::regnamespace::text
    END AS schema_name,
    CASE default_acl.defaclobjtype
        WHEN 'r' THEN 'tables'
        WHEN 'S' THEN 'sequences'
        WHEN 'f' THEN 'functions'
        WHEN 'T' THEN 'types'
        WHEN 'n' THEN 'schemas'
        ELSE default_acl.defaclobjtype::text
    END AS object_type,
    pg_get_userbyid(acl.grantor) AS grantor,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    acl.privilege_type,
    acl.is_grantable
FROM pg_default_acl AS default_acl
JOIN pg_roles AS owner_role
  ON owner_role.oid = default_acl.defaclrole
CROSS JOIN LATERAL aclexplode(default_acl.defaclacl) AS acl
ORDER BY owner_role, schema_name, object_type, grantee, privilege_type;

-- 10. Schema-level privileges can permit object creation even when table ACLs
-- are locked down. Review public-schema CREATE carefully.
SELECT
    namespace.nspname AS schema_name,
    pg_get_userbyid(acl.grantor) AS grantor,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    acl.privilege_type,
    acl.is_grantable
FROM pg_namespace AS namespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(namespace.nspacl, acldefault('n'::"char", namespace.nspowner))
) AS acl
WHERE namespace.nspname = 'public'
ORDER BY grantee, privilege_type;

-- 11. RLS policies. No rows for a target table means no policies exist.
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
  AND tablename IN (
      'platform_admin_users',
      'platform_admin_audit_events'
  )
ORDER BY tablename, policyname;

-- 12. Constraints and indexes needed for migration verification.
SELECT
    relation.relname AS table_name,
    constraint_row.conname AS constraint_name,
    CASE constraint_row.contype
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'u' THEN 'UNIQUE'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'c' THEN 'CHECK'
        ELSE constraint_row.contype::text
    END AS constraint_type,
    pg_get_constraintdef(constraint_row.oid, true) AS definition
FROM pg_constraint AS constraint_row
JOIN pg_class AS relation
  ON relation.oid = constraint_row.conrelid
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname IN (
      'platform_admin_users',
      'platform_admin_audit_events'
  )
ORDER BY table_name, constraint_type, constraint_name;

SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN (
      'platform_admin_users',
      'platform_admin_audit_events'
  )
ORDER BY tablename, indexname;

-- 13. Trigger inspection. The finalized migrations create no triggers; any row
-- returned for these tables therefore requires investigation.
SELECT
    event_object_schema,
    event_object_table,
    trigger_name,
    event_manipulation,
    action_timing,
    action_statement
FROM information_schema.triggers
WHERE event_object_schema = 'public'
  AND event_object_table IN (
      'platform_admin_users',
      'platform_admin_audit_events'
  )
ORDER BY event_object_table, trigger_name, event_manipulation;
