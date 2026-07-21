-- Platform-admin Phase 4 append-only staging verification.
-- STAGING ONLY. Do not run in production.
--
-- Preconditions:
-- - migrations 023 through 026 are applied in staging;
-- - at least one existing platform_admin_users row is inactive;
-- - execute as an approved migration/database owner that can SET LOCAL ROLE to
--   service_role; the mutation attempts themselves execute as service_role.
--
-- If any unexpected error escapes the verification blocks, issue ROLLBACK
-- immediately in the same session and inspect the table/grants before retrying.
--
-- The fixed negative audit ID avoids advancing the identity sequence. The
-- temporary row and temporary UPDATE/DELETE grants are removed by the final
-- ROLLBACK. Those grants are required to prove that the trigger still rejects
-- service_role after ordinary ACL denial is deliberately removed. PL/pgSQL
-- EXCEPTION blocks use internal subtransactions; explicit savepoints bracket
-- the expected UPDATE and DELETE checks.

BEGIN;

DO $verification$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.platform_admin_users
        WHERE is_active = FALSE
    ) THEN
        RAISE EXCEPTION
            'Append-only verification requires one existing inactive platform-admin mapping';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.platform_admin_audit_events
        WHERE id = -9223372036854775807
    ) THEN
        RAISE EXCEPTION
            'Reserved append-only verification audit ID already exists';
    END IF;
END;
$verification$;

-- Normal service_role grants already deny UPDATE/DELETE. Broaden them only
-- inside this rollback-only transaction so the following stable 55000 errors
-- prove trigger enforcement rather than ACL enforcement.
GRANT UPDATE, DELETE
ON TABLE public.platform_admin_audit_events
TO service_role;

SET LOCAL ROLE service_role;

INSERT INTO public.platform_admin_audit_events (
    id,
    platform_admin_user_id,
    action,
    resource_type,
    resource_id,
    metadata,
    created_at
)
SELECT
    -9223372036854775807,
    platform_admin.id,
    'platform_admin.identity.read',
    'platform_admin',
    platform_admin.id::TEXT,
    jsonb_build_object(
        'outcome', 'success',
        'endpoint', '/api/platform-admin/me',
        'http_method', 'GET'
    ),
    NOW()
FROM public.platform_admin_users AS platform_admin
WHERE platform_admin.is_active = FALSE
ORDER BY platform_admin.id
LIMIT 1
RETURNING id, platform_admin_user_id, action, resource_type, resource_id;

SAVEPOINT before_expected_update_rejection;

DO $verification$
BEGIN
    BEGIN
        UPDATE public.platform_admin_audit_events
        SET metadata = metadata || '{"outcome":"not_found"}'::jsonb
        WHERE id = -9223372036854775807;

        RAISE EXCEPTION
            'Append-only verification failed: UPDATE unexpectedly succeeded';
    EXCEPTION
        WHEN SQLSTATE '55000' THEN
            IF SQLERRM <> 'platform_admin_audit_events is append-only' THEN
                RAISE EXCEPTION
                    'Append-only verification failed: UPDATE returned an unexpected message';
            END IF;
    END;
END;
$verification$;

RELEASE SAVEPOINT before_expected_update_rejection;

SAVEPOINT before_expected_delete_rejection;

DO $verification$
BEGIN
    BEGIN
        DELETE FROM public.platform_admin_audit_events
        WHERE id = -9223372036854775807;

        RAISE EXCEPTION
            'Append-only verification failed: DELETE unexpectedly succeeded';
    EXCEPTION
        WHEN SQLSTATE '55000' THEN
            IF SQLERRM <> 'platform_admin_audit_events is append-only' THEN
                RAISE EXCEPTION
                    'Append-only verification failed: DELETE returned an unexpected message';
            END IF;
    END;
END;
$verification$;

RELEASE SAVEPOINT before_expected_delete_rejection;

-- INSERT and SELECT succeeded, and both rejected mutations left the original
-- temporary row unchanged.
SELECT
    id,
    platform_admin_user_id,
    action,
    resource_type,
    resource_id,
    metadata,
    created_at
FROM public.platform_admin_audit_events
WHERE id = -9223372036854775807;

DO $verification$
BEGIN
    IF (
        SELECT COUNT(*)
        FROM public.platform_admin_audit_events
        WHERE id = -9223372036854775807
          AND action = 'platform_admin.identity.read'
          AND resource_type = 'platform_admin'
          AND metadata = jsonb_build_object(
              'outcome', 'success',
              'endpoint', '/api/platform-admin/me',
              'http_method', 'GET'
          )
    ) <> 1 THEN
        RAISE EXCEPTION
            'Append-only verification failed: temporary row missing or changed';
    END IF;
END;
$verification$;

RESET ROLE;

ROLLBACK;

-- Run in the same SQL session immediately after ROLLBACK. Expected: true.
SELECT NOT EXISTS (
    SELECT 1
    FROM public.platform_admin_audit_events
    WHERE id = -9223372036854775807
) AS temporary_audit_row_removed;

-- Expected: both false, proving the temporary test grants also rolled back.
SELECT
    has_table_privilege(
        'service_role',
        'public.platform_admin_audit_events',
        'UPDATE'
    ) AS service_role_can_update_after_rollback,
    has_table_privilege(
        'service_role',
        'public.platform_admin_audit_events',
        'DELETE'
    ) AS service_role_can_delete_after_rollback;
