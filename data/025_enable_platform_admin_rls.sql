-- 025_enable_platform_admin_rls.sql
--
-- Enables RLS for both platform-admin tables after migrations 023 and 024.
-- Verified successfully in staging. Production application requires separate
-- approval and is intentionally not part of this migration-preparation task.
--
-- No policy is published to anon or authenticated. The service_role policies
-- match the minimum table grants. In Supabase, service_role has BYPASSRLS, so
-- these policies document the intended operation envelope but do not constrain
-- that role. Server-side platform-admin authorization remains mandatory.

ALTER TABLE public.platform_admin_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_admin_audit_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS platform_admin_users_service_select
    ON public.platform_admin_users;
CREATE POLICY platform_admin_users_service_select
    ON public.platform_admin_users
    FOR SELECT
    TO service_role
    USING (true);

DROP POLICY IF EXISTS platform_admin_users_service_insert
    ON public.platform_admin_users;
CREATE POLICY platform_admin_users_service_insert
    ON public.platform_admin_users
    FOR INSERT
    TO service_role
    WITH CHECK (true);

DROP POLICY IF EXISTS platform_admin_users_service_update
    ON public.platform_admin_users;
CREATE POLICY platform_admin_users_service_update
    ON public.platform_admin_users
    FOR UPDATE
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS platform_admin_audit_events_service_select
    ON public.platform_admin_audit_events;
CREATE POLICY platform_admin_audit_events_service_select
    ON public.platform_admin_audit_events
    FOR SELECT
    TO service_role
    USING (true);

DROP POLICY IF EXISTS platform_admin_audit_events_service_insert
    ON public.platform_admin_audit_events;
CREATE POLICY platform_admin_audit_events_service_insert
    ON public.platform_admin_audit_events
    FOR INSERT
    TO service_role
    WITH CHECK (true);

-- Intentionally absent:
-- - policies for anon or authenticated
-- - DELETE policy on either table
-- - UPDATE policy on platform_admin_audit_events
-- - FORCE ROW LEVEL SECURITY

