-- Empties the copy so each run (dry run, then cutover) holds exactly the latest
-- dump. Only ever pointed at the NEW project. The grant lets postgres load n8n's
-- tables; after-restore.sql revokes it.
GRANT agent_n8n TO CURRENT_USER WITH SET TRUE;
GRANT agent_n8n TO CURRENT_USER WITH INHERIT TRUE;
DO $$
DECLARE tables text;
BEGIN
  SELECT string_agg(format('%I.%I', schemaname, tablename), ', ') INTO tables
  FROM pg_tables WHERE schemaname IN ('public', 'supabase_migrations', 'agent_n8n');
  IF tables IS NOT NULL THEN
    EXECUTE 'TRUNCATE TABLE ' || tables || ' RESTART IDENTITY CASCADE';
  END IF;
END $$;
