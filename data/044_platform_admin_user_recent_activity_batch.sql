-- 044_platform_admin_user_recent_activity_batch.sql
-- MIGRATION DRAFT ONLY. Do not apply without approved executor, environment,
-- privacy, retention, rollback, and production-readiness approvals.
-- Batches latest platform-admin audit activity lookups for the user directory.

CREATE OR REPLACE FUNCTION public.get_latest_platform_admin_activity(
    p_platform_admin_user_ids BIGINT[]
)
RETURNS TABLE (
    platform_admin_user_id BIGINT,
    recent_platform_admin_activity_at TIMESTAMPTZ
)
LANGUAGE sql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
    WITH requested AS (
        SELECT DISTINCT supplied.platform_admin_user_id
        FROM pg_catalog.unnest(p_platform_admin_user_ids) AS supplied(platform_admin_user_id)
        WHERE supplied.platform_admin_user_id IS NOT NULL
          AND supplied.platform_admin_user_id > 0
    )
    SELECT
        requested.platform_admin_user_id,
        pg_catalog.max(events.created_at) AS recent_platform_admin_activity_at
    FROM requested
    LEFT JOIN public.platform_admin_audit_events AS events
      ON events.platform_admin_user_id = requested.platform_admin_user_id
    GROUP BY requested.platform_admin_user_id
    ORDER BY requested.platform_admin_user_id ASC;
$function$;

REVOKE ALL ON FUNCTION public.get_latest_platform_admin_activity(BIGINT[])
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.get_latest_platform_admin_activity(BIGINT[])
    TO service_role;
