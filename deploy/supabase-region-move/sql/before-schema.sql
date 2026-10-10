-- Fresh project only (move.sh refuses if public already has tables).
-- Mirrors deploy/agent-automation/n8n-private-schema.sql and data/069.
\getenv n8n_pw N8N_DB_PASSWORD
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
-- A fresh project can hold an empty migration-history schema; the dump recreates it.
DROP SCHEMA IF EXISTS supabase_migrations CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_n8n') THEN
    CREATE ROLE agent_n8n LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;
-- Same password as the old project, so n8n only changes its host.
ALTER ROLE agent_n8n WITH LOGIN PASSWORD :'n8n_pw';
ALTER ROLE agent_n8n SET search_path = agent_n8n;
GRANT CREATE ON DATABASE postgres TO agent_n8n;
-- Temporary, revoked by after-restore.sql: lets postgres create n8n's objects as their owner.
GRANT agent_n8n TO CURRENT_USER WITH SET TRUE;
GRANT agent_n8n TO CURRENT_USER WITH INHERIT TRUE;
