-- 026_enforce_platform_admin_audit_append_only.sql
--
-- Adds database-enforced append-only protection to the platform-admin audit
-- trail. The trigger rejects every UPDATE and DELETE attempt, including one
-- made by service_role despite that role's BYPASSRLS attribute.
--
-- SECURITY INVOKER is intentional: the function reads no database objects and
-- needs no elevated privilege. Its fixed pg_catalog search_path is defensive
-- hardening. The migration executor owns the function; production must use and
-- verify the approved postgres executor/owner.
--
-- This migration does not change RLS, policies, table/sequence grants, audit
-- rows, retention behavior, or tenant users.role semantics. It provides no
-- maintenance bypass. Owners and superusers can still alter/disable/drop the
-- trigger and therefore remain privileged operational boundaries.

CREATE OR REPLACE FUNCTION public.reject_platform_admin_audit_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = '55000',
        MESSAGE = 'platform_admin_audit_events is append-only';
END;
$function$;

COMMENT ON FUNCTION public.reject_platform_admin_audit_event_mutation() IS
    'Rejects UPDATE and DELETE on platform_admin_audit_events. SECURITY INVOKER; no maintenance bypass.';

DROP TRIGGER IF EXISTS platform_admin_audit_events_reject_mutation
    ON public.platform_admin_audit_events;

CREATE TRIGGER platform_admin_audit_events_reject_mutation
    BEFORE UPDATE OR DELETE
    ON public.platform_admin_audit_events
    FOR EACH ROW
    EXECUTE FUNCTION public.reject_platform_admin_audit_event_mutation();

-- Trigger invocation does not require calling roles to retain direct EXECUTE
-- on the trigger function. Remove PostgreSQL's default PUBLIC EXECUTE and any
-- explicit application-role EXECUTE grants after deterministic trigger setup.
REVOKE ALL
ON FUNCTION public.reject_platform_admin_audit_event_mutation()
FROM PUBLIC, anon, authenticated, service_role;
