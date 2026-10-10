-- Same transaction as the data files. Empties the copy so each run (dry run,
-- then cutover) holds exactly the latest dump. Only ever pointed at the NEW project.
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
-- Triggers and FK checks off while loading, as Supabase's own restore guide does.
SET session_replication_role = replica;
