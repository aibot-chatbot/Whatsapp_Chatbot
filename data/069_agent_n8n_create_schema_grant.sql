-- 069_agent_n8n_create_schema_grant.sql
-- n8n 2.x runs CREATE SCHEMA IF NOT EXISTS "<DB_POSTGRESDB_SCHEMA>" on every
-- boot. PostgreSQL checks database-level CREATE before it checks whether the
-- schema exists, so without this grant n8n stalls forever at startup (no exit,
-- no listener, Fly never restarts it). Reproduced on PostgreSQL 17.
--
-- Scope: lets agent_n8n create NEW empty schemas. It grants no access to any
-- existing schema, table or function; the isolation checks in
-- deploy/agent-automation/n8n-private-schema.sql still hold.
--
-- Applied to production 2026-09-23 with owner approval (Supabase migration
-- 069_agent_n8n_create_schema_grant). Verify:
--   SELECT has_database_privilege('agent_n8n', current_database(), 'CREATE');  -- true
--   SELECT has_table_privilege('agent_n8n', 'public.chatbots', 'SELECT');      -- false

GRANT CREATE ON DATABASE postgres TO agent_n8n;
