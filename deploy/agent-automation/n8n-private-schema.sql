-- TEMPLATE ONLY. Run with the confirmed project administrator, never API keys.
-- Set the login password separately through the approved secret-management path.
-- Do not expose agent_n8n in Supabase Data API schemas.
BEGIN;
CREATE ROLE agent_n8n LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
-- CREATEROLE administrators receive ADMIN only on the new role in PostgreSQL
-- 16+. Temporarily permit schema ownership operations, even with NOINHERIT.
GRANT agent_n8n TO CURRENT_USER WITH SET TRUE;
GRANT agent_n8n TO CURRENT_USER WITH INHERIT TRUE;
CREATE SCHEMA agent_n8n AUTHORIZATION agent_n8n;
REVOKE ALL ON SCHEMA agent_n8n FROM PUBLIC,anon,authenticated,service_role;
GRANT USAGE,CREATE ON SCHEMA agent_n8n TO agent_n8n;
ALTER ROLE agent_n8n SET search_path = agent_n8n;
-- A schema is not a security boundary if PUBLIC still grants app-data access.
-- Abort instead of silently broadening/revoking existing production permissions.
DO $guard$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
             WHERE n.nspname IN ('public','auth','storage') AND c.relkind IN ('r','p','v','m','f')
               AND has_table_privilege('agent_n8n',c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE'))
     OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname IN ('public','auth','storage') AND p.prosecdef
                  AND has_function_privilege('agent_n8n',p.oid,'EXECUTE')) THEN
    RAISE EXCEPTION 'n8n role inherits app access through PUBLIC; review grants or use an isolated database';
  END IF;
END $guard$;
ALTER DEFAULT PRIVILEGES FOR ROLE agent_n8n IN SCHEMA agent_n8n
  REVOKE ALL ON TABLES FROM PUBLIC,anon,authenticated,service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE agent_n8n IN SCHEMA agent_n8n
  REVOKE ALL ON SEQUENCES FROM PUBLIC,anon,authenticated,service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE agent_n8n IN SCHEMA agent_n8n
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC,anon,authenticated,service_role;
-- Remove our temporary grant; retain PostgreSQL's separate ADMIN-only grant
-- so the provisioning administrator can set or rotate the login password.
REVOKE agent_n8n FROM CURRENT_USER;
COMMIT;
