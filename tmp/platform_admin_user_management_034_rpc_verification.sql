-- Platform-admin User Management Phase 4 RPC verification package.
-- TEMPLATE ONLY. Do not run until an approved second fake/team active user
-- exists in the main shared-testing protected internal company.
--
-- Current shared-testing facts at authoring time:
-- - protected company: 29, approved only for main shared-testing
-- - existing platform-admin mapping: 1
-- - existing platform-admin user: 32
-- - user 32 is already mapped, so create success remains pending
--
-- Replace placeholders before any approved manual run:
--   <ACTOR_PLATFORM_ADMIN_USER_ID>
--   <EXISTING_MAPPED_USER_ID>
--   <MISSING_USER_ID>
--   <SECOND_APPROVED_ACTIVE_USER_ID>
--   <SECOND_CREATED_PLATFORM_ADMIN_USER_ID>

BEGIN;

-- Baseline counts used to confirm rejected RPCs do not write partial rows.
CREATE TEMP TABLE phase4_user_management_baseline ON COMMIT DROP AS
SELECT
    (SELECT COUNT(*) FROM public.platform_admin_users) AS mapping_count,
    (SELECT COUNT(*) FROM public.platform_admin_audit_events
     WHERE action IN (
         'platform_admin.user.create',
         'platform_admin.user.activate',
         'platform_admin.user.deactivate'
     )) AS mutation_audit_count;

-- Duplicate create rejection using the already mapped user 32.
DO $$
BEGIN
    PERFORM public.create_platform_admin_user_mapping(
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        <EXISTING_MAPPED_USER_ID>::bigint
    );
    RAISE EXCEPTION 'Expected duplicate create rejection';
EXCEPTION
    WHEN unique_violation THEN
        NULL;
END $$;

SELECT
    'duplicate_create_rejected_without_partial_rows' AS check_name,
    (SELECT COUNT(*) FROM public.platform_admin_users) =
        (SELECT mapping_count FROM phase4_user_management_baseline) AS mapping_count_unchanged,
    (SELECT COUNT(*) FROM public.platform_admin_audit_events
     WHERE action IN (
         'platform_admin.user.create',
         'platform_admin.user.activate',
         'platform_admin.user.deactivate'
     )) =
        (SELECT mutation_audit_count FROM phase4_user_management_baseline) AS audit_count_unchanged;

-- Missing target user rejection.
DO $$
BEGIN
    PERFORM public.create_platform_admin_user_mapping(
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        <MISSING_USER_ID>::bigint
    );
    RAISE EXCEPTION 'Expected missing user rejection';
EXCEPTION
    WHEN no_data_found THEN
        NULL;
END $$;

SELECT
    'missing_user_rejected_without_partial_rows' AS check_name,
    (SELECT COUNT(*) FROM public.platform_admin_users) =
        (SELECT mapping_count FROM phase4_user_management_baseline) AS mapping_count_unchanged,
    (SELECT COUNT(*) FROM public.platform_admin_audit_events
     WHERE action IN (
         'platform_admin.user.create',
         'platform_admin.user.activate',
         'platform_admin.user.deactivate'
     )) =
        (SELECT mutation_audit_count FROM phase4_user_management_baseline) AS audit_count_unchanged;

-- Self-deactivation rejection.
DO $$
BEGIN
    PERFORM public.set_platform_admin_user_active(
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        false
    );
    RAISE EXCEPTION 'Expected self-deactivation rejection';
EXCEPTION
    WHEN insufficient_privilege THEN
        NULL;
END $$;

-- Final-active-admin rejection. This should fail while only one active mapping exists.
DO $$
BEGIN
    PERFORM public.set_platform_admin_user_active(
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        false
    );
    RAISE EXCEPTION 'Expected final active admin rejection';
EXCEPTION
    WHEN insufficient_privilege THEN
        NULL;
END $$;

-- No-op rejection for current active mapping.
DO $$
BEGIN
    PERFORM public.set_platform_admin_user_active(
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
        true
    );
    RAISE EXCEPTION 'Expected no-op active-state rejection';
EXCEPTION
    WHEN invalid_parameter_value THEN
        NULL;
END $$;

SELECT
    'active_state_rejections_without_partial_rows' AS check_name,
    (SELECT COUNT(*) FROM public.platform_admin_users) =
        (SELECT mapping_count FROM phase4_user_management_baseline) AS mapping_count_unchanged,
    (SELECT COUNT(*) FROM public.platform_admin_audit_events
     WHERE action IN (
         'platform_admin.user.create',
         'platform_admin.user.activate',
         'platform_admin.user.deactivate'
     )) =
        (SELECT mutation_audit_count FROM phase4_user_management_baseline) AS audit_count_unchanged;

-- Success path, pending until <SECOND_APPROVED_ACTIVE_USER_ID> exists and is approved.
SELECT public.create_platform_admin_user_mapping(
    <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
    <SECOND_APPROVED_ACTIVE_USER_ID>::bigint
) AS create_result;

SELECT
    'create_success_created_one_mapping_and_audit' AS check_name,
    COUNT(*) FILTER (WHERE user_id = <SECOND_APPROVED_ACTIVE_USER_ID>::bigint) = 1
        AS created_mapping_exists,
    COUNT(*) FILTER (WHERE user_id = <SECOND_APPROVED_ACTIVE_USER_ID>::bigint AND is_active IS TRUE) = 1
        AS created_mapping_active
FROM public.platform_admin_users;

SELECT public.set_platform_admin_user_active(
    <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
    <SECOND_CREATED_PLATFORM_ADMIN_USER_ID>::bigint,
    false
) AS deactivate_result;

SELECT public.set_platform_admin_user_active(
    <ACTOR_PLATFORM_ADMIN_USER_ID>::bigint,
    <SECOND_CREATED_PLATFORM_ADMIN_USER_ID>::bigint,
    true
) AS activate_result;

SELECT
    action,
    resource_type,
    resource_id,
    COUNT(*) AS action_count
FROM public.platform_admin_audit_events
WHERE action IN (
    'platform_admin.user.create',
    'platform_admin.user.activate',
    'platform_admin.user.deactivate'
)
GROUP BY action, resource_type, resource_id
ORDER BY action, resource_id;

ROLLBACK;
