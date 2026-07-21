-- Platform-admin Phase 4 append-only inspection.
-- READ ONLY: every statement is SELECT-only.
-- Run after applying migration 026 in an approved environment.

-- 1. Function identity, owner, execution mode, configuration, ACL, and exact
-- definition. Expected: owner postgres (when applied by the approved executor),
-- security_definer false, search_path=pg_catalog, and the fixed 55000 error.
SELECT
    namespace.nspname AS function_schema,
    procedure.proname AS function_name,
    pg_get_function_identity_arguments(procedure.oid) AS identity_arguments,
    pg_get_userbyid(procedure.proowner) AS function_owner,
    procedure.prosecdef AS security_definer,
    procedure.proconfig AS function_configuration,
    procedure.proacl AS raw_function_acl,
    pg_get_functiondef(procedure.oid) AS function_definition
FROM pg_proc AS procedure
JOIN pg_namespace AS namespace
  ON namespace.oid = procedure.pronamespace
WHERE namespace.nspname = 'public'
  AND procedure.proname = 'reject_platform_admin_audit_event_mutation'
  AND pg_get_function_identity_arguments(procedure.oid) = '';

-- 2. Expanded effective function ACL entries. Expected: no EXECUTE entry for
-- PUBLIC, anon, authenticated, or service_role; the owner retains implicit
-- function privileges.
SELECT
    namespace.nspname AS function_schema,
    procedure.proname AS function_name,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    pg_get_userbyid(acl.grantor) AS grantor,
    acl.privilege_type,
    acl.is_grantable
FROM pg_proc AS procedure
JOIN pg_namespace AS namespace
  ON namespace.oid = procedure.pronamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(procedure.proacl, acldefault('f'::"char", procedure.proowner))
) AS acl
WHERE namespace.nspname = 'public'
  AND procedure.proname = 'reject_platform_admin_audit_event_mutation'
  AND pg_get_function_identity_arguments(procedure.oid) = ''
ORDER BY grantee, privilege_type;

-- 3. Explicit effective EXECUTE checks for application-facing roles. Expected:
-- false for anon, authenticated, and service_role. Trigger firing is not a
-- direct function call and remains effective after these revocations.
SELECT
    role_row.rolname AS role_name,
    has_function_privilege(
        role_row.oid,
        'public.reject_platform_admin_audit_event_mutation()'::regprocedure,
        'EXECUTE'
    ) AS can_execute_directly
FROM pg_roles AS role_row
WHERE role_row.rolname IN ('anon', 'authenticated', 'service_role')
ORDER BY role_name;

-- 4. Trigger existence, enabled state, and exact definition. Expected: one
-- non-internal trigger, enabled='O', BEFORE UPDATE OR DELETE, FOR EACH ROW.
SELECT
    namespace.nspname AS table_schema,
    relation.relname AS table_name,
    trigger_row.tgname AS trigger_name,
    trigger_row.tgenabled AS enabled_state,
    trigger_row.tgisinternal AS is_internal,
    pg_get_triggerdef(trigger_row.oid, true) AS trigger_definition
FROM pg_trigger AS trigger_row
JOIN pg_class AS relation
  ON relation.oid = trigger_row.tgrelid
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname = 'platform_admin_audit_events'
  AND trigger_row.tgname = 'platform_admin_audit_events_reject_mutation';

-- 5. Information-schema expansion of timing, events, and row orientation.
-- Expected: exactly two rows, one UPDATE and one DELETE; both BEFORE/ROW.
SELECT
    event_object_schema,
    event_object_table,
    trigger_name,
    event_manipulation,
    action_timing,
    action_orientation,
    action_statement
FROM information_schema.triggers
WHERE event_object_schema = 'public'
  AND event_object_table = 'platform_admin_audit_events'
  AND trigger_name = 'platform_admin_audit_events_reject_mutation'
ORDER BY event_manipulation;

-- 6. Table ownership and RLS must remain unchanged from migration 025.
-- Expected: postgres owner, RLS enabled, RLS not forced.
SELECT
    namespace.nspname AS table_schema,
    relation.relname AS table_name,
    pg_get_userbyid(relation.relowner) AS table_owner,
    relation.relrowsecurity AS rls_enabled,
    relation.relforcerowsecurity AS rls_forced
FROM pg_class AS relation
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname = 'platform_admin_audit_events';

-- 7. Direct table ACLs. Migration 026 must not change these.
SELECT
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE pg_get_userbyid(acl.grantee)
    END AS grantee,
    pg_get_userbyid(acl.grantor) AS grantor,
    acl.privilege_type,
    acl.is_grantable
FROM pg_class AS relation
CROSS JOIN LATERAL aclexplode(
    COALESCE(relation.relacl, acldefault('r'::"char", relation.relowner))
) AS acl
WHERE relation.oid = 'public.platform_admin_audit_events'::regclass
ORDER BY grantee, privilege_type;

-- 8. Effective table privileges. Expected: anon/authenticated all false;
-- service_role SELECT/INSERT true and UPDATE/DELETE false.
SELECT
    role_row.rolname AS role_name,
    has_table_privilege(role_row.oid, relation.oid, 'SELECT') AS can_select,
    has_table_privilege(role_row.oid, relation.oid, 'INSERT') AS can_insert,
    has_table_privilege(role_row.oid, relation.oid, 'UPDATE') AS can_update,
    has_table_privilege(role_row.oid, relation.oid, 'DELETE') AS can_delete
FROM pg_roles AS role_row
CROSS JOIN LATERAL (
    SELECT 'public.platform_admin_audit_events'::regclass::oid AS oid
) AS relation
WHERE role_row.rolname IN ('anon', 'authenticated', 'service_role')
ORDER BY role_name;

-- 9. RLS policies must remain exactly as migration 025 defined them: service
-- SELECT and INSERT only; no client, UPDATE, or DELETE policy.
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
  AND tablename = 'platform_admin_audit_events'
ORDER BY policyname;
