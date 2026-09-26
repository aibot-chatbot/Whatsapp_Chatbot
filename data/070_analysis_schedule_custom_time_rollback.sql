-- 070_analysis_schedule_custom_time_rollback.sql
-- Reverses 070_analysis_schedule_custom_time.sql: restores the 063
-- analysis_upsert_schedule (7 arguments) and its grants, and drops the slot
-- constraints and columns.
--
-- Effect: every owner's chosen day/time is DELETED.  Enabled schedules keep
-- their next_due_at, but the pre-070 application computes Monday / 1st at 09:00
-- MYT from then on.  The 070 application cannot enable schedules against this
-- schema (its slot arguments no longer exist); its skip/disable calls send only
-- the 7 pre-070 arguments and keep working.  Roll the application back with it.
--
-- Re-applying 070 afterwards fails while any schedule is enabled (no slot is
-- stored any more); disable them first.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP FUNCTION IF EXISTS public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz,smallint,smallint,time);
DROP FUNCTION IF EXISTS public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz);

-- Verbatim from data/063_agent_analysis.sql.
CREATE FUNCTION public.analysis_upsert_schedule(p_company_id bigint,p_chatbot_id bigint,p_actor_user_id bigint,
    p_frequency text,p_timezone text,p_enabled boolean,p_next_due_at timestamptz DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE s public.analysis_schedules;
BEGIN
    PERFORM public.analysis_require_actor(p_company_id,p_chatbot_id,p_actor_user_id);
    INSERT INTO public.analysis_schedules(company_id,chatbot_id,actor_user_id,frequency,timezone,enabled,next_due_at)
      VALUES(p_company_id,p_chatbot_id,p_actor_user_id,p_frequency,p_timezone,p_enabled,p_next_due_at)
      ON CONFLICT(company_id,chatbot_id,frequency) DO UPDATE SET actor_user_id=excluded.actor_user_id,
        timezone=excluded.timezone,enabled=excluded.enabled,next_due_at=excluded.next_due_at,updated_at=now()
      RETURNING * INTO s;
    RETURN to_jsonb(s);
END $$;

REVOKE ALL ON FUNCTION public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz)
    TO service_role;

ALTER TABLE public.analysis_schedules
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_weekday_range,
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_day_range,
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_time_quarter_hour,
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_slot_matches_frequency,
    DROP CONSTRAINT IF EXISTS analysis_schedules_enabled_has_run_slot,
    DROP COLUMN IF EXISTS run_weekday,
    DROP COLUMN IF EXISTS run_day,
    DROP COLUMN IF EXISTS run_time;
COMMIT;

-- Verification (read-only), after rolling back:
--   SELECT p.oid::regprocedure FROM pg_proc p WHERE p.proname = 'analysis_upsert_schedule';
--   -- expect ONE row with 7 arguments ending in timestamptz
--   SELECT count(*) FROM information_schema.columns
--    WHERE table_schema = 'public' AND table_name = 'analysis_schedules' AND column_name LIKE 'run\_%';
--   -- expect 0
