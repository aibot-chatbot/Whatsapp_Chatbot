-- 070_analysis_schedule_custom_time.sql
-- Owner-chosen day and time for scheduled Analysis reports.
--
--   run_weekday  weekly only: 0 = Monday .. 6 = Sunday
--   run_day      monthly only: 1..28, or 0 = "last day of the month"
--   run_time     Malaysia time (the row's timezone), 15-minute steps
--
-- Product owner decision: there is no fixed default slot.  An enabled schedule
-- must carry a time plus the day column of its frequency; a disabled one may
-- keep (or lack) a choice.  Periods are computed by the application
-- (app/services/analysis_request_service.schedule_period).
--
-- Existing rows are never rewritten.  The CHECK constraints are added VALIDATED,
-- so if any enabled schedule exists without a slot this migration FAILS and
-- rolls back instead of inventing one.  Production had 0 enabled schedules when
-- this was written; disable any that exist, apply, then let owners re-enable.
--
-- analysis_upsert_schedule is REPLACED, not overloaded: the 063 7-argument
-- signature is dropped in the same transaction, because an overload with
-- defaulted arguments makes PostgREST named-argument calls ambiguous.
--
-- Deploy order: apply this first, while the pre-070 application still runs.
--   * Its 7 named arguments resolve to the new function (the rest default).
--   * Slot arguments left NULL keep the stored value, so tick skips and
--     downgrade/owner disables never wipe the owner's choice.
--   * When a 7-argument caller ENABLES a schedule that has no stored slot (only
--     the pre-070 application does that), the slot is read from its own
--     next_due_at, which that code always sets to Monday / the 1st at 09:00
--     MYT.  That records the slot it actually scheduled, not a default.
-- Then deploy the application that sends the owner's slot.
--
-- Security: same model as 063.  SECURITY DEFINER with an empty search_path,
-- analysis_require_actor re-verifies company, Bot and an active owner/admin
-- actor, and only service_role may execute.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.analysis_schedules
    ADD COLUMN IF NOT EXISTS run_weekday smallint,
    ADD COLUMN IF NOT EXISTS run_day smallint,
    ADD COLUMN IF NOT EXISTS run_time time;

-- Drop first so a re-run always installs these predicates, never a stale one.
ALTER TABLE public.analysis_schedules
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_weekday_range,
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_day_range,
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_time_quarter_hour,
    DROP CONSTRAINT IF EXISTS analysis_schedules_run_slot_matches_frequency,
    DROP CONSTRAINT IF EXISTS analysis_schedules_enabled_has_run_slot;
ALTER TABLE public.analysis_schedules
    ADD CONSTRAINT analysis_schedules_run_weekday_range CHECK (run_weekday BETWEEN 0 AND 6),
    ADD CONSTRAINT analysis_schedules_run_day_range CHECK (run_day BETWEEN 0 AND 28),
    ADD CONSTRAINT analysis_schedules_run_time_quarter_hour
        -- time accepts '24:00'; the last slot of a day is 23:45.
        CHECK (extract(second FROM run_time) = 0 AND extract(minute FROM run_time) IN (0, 15, 30, 45) AND run_time < '24:00'),
    ADD CONSTRAINT analysis_schedules_run_slot_matches_frequency
        CHECK ((frequency = 'weekly' AND run_day IS NULL) OR (frequency = 'monthly' AND run_weekday IS NULL)),
    ADD CONSTRAINT analysis_schedules_enabled_has_run_slot
        CHECK (NOT enabled OR (run_time IS NOT NULL AND ((frequency = 'weekly' AND run_weekday IS NOT NULL) OR (frequency = 'monthly' AND run_day IS NOT NULL))));

DROP FUNCTION IF EXISTS public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz);
DROP FUNCTION IF EXISTS public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz,smallint,smallint,time);

CREATE FUNCTION public.analysis_upsert_schedule(p_company_id bigint,p_chatbot_id bigint,p_actor_user_id bigint,
    p_frequency text,p_timezone text,p_enabled boolean,p_next_due_at timestamptz DEFAULT NULL,
    p_run_weekday smallint DEFAULT NULL,p_run_day smallint DEFAULT NULL,p_run_time time DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE s public.analysis_schedules; cur public.analysis_schedules; due_local timestamp;
    v_weekday smallint; v_day smallint; v_time time;
BEGIN
    PERFORM public.analysis_require_actor(p_company_id,p_chatbot_id,p_actor_user_id);
    -- Resolve the slot before INSERT: CHECKs apply to the proposed row even
    -- when ON CONFLICT turns it into an update. The lock keeps it current.
    SELECT * INTO cur FROM public.analysis_schedules WHERE company_id=p_company_id
      AND chatbot_id=p_chatbot_id AND frequency=p_frequency FOR UPDATE;
    IF p_enabled AND p_run_weekday IS NULL AND p_run_day IS NULL AND p_run_time IS NULL
       AND cur.run_time IS NULL AND p_next_due_at IS NOT NULL THEN
        -- A pre-070 caller enabling: record the exact slot its next_due_at
        -- names (Monday / 1st, 09:00), as if it had sent it. Never mix a
        -- stored day with the derived time.
        due_local := p_next_due_at AT TIME ZONE 'Asia/Kuala_Lumpur';
        p_run_time := due_local::time;
        IF p_frequency='weekly' THEN
            p_run_weekday := extract(isodow FROM due_local)::smallint-1;
        ELSE
            p_run_day := extract(day FROM due_local)::smallint;
        END IF;
    END IF;
    v_weekday := coalesce(p_run_weekday,cur.run_weekday);
    v_day := coalesce(p_run_day,cur.run_day);
    v_time := coalesce(p_run_time,cur.run_time);
    INSERT INTO public.analysis_schedules AS existing(company_id,chatbot_id,actor_user_id,frequency,timezone,enabled,
        next_due_at,run_weekday,run_day,run_time)
      VALUES(p_company_id,p_chatbot_id,p_actor_user_id,p_frequency,p_timezone,p_enabled,p_next_due_at,
        v_weekday,v_day,v_time)
      ON CONFLICT(company_id,chatbot_id,frequency) DO UPDATE SET actor_user_id=excluded.actor_user_id,
        timezone=excluded.timezone,enabled=excluded.enabled,next_due_at=excluded.next_due_at,
        run_weekday=coalesce(p_run_weekday,existing.run_weekday,excluded.run_weekday),
        run_day=coalesce(p_run_day,existing.run_day,excluded.run_day),
        run_time=coalesce(p_run_time,existing.run_time,excluded.run_time),updated_at=now()
      RETURNING * INTO s;
    RETURN to_jsonb(s);
END $$;

REVOKE ALL ON FUNCTION public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz,smallint,smallint,time)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz,smallint,smallint,time)
    TO service_role;
COMMIT;

-- Verification (read-only), after applying:
--   SELECT p.oid::regprocedure, p.prosecdef, p.proconfig,
--          has_function_privilege('service_role', p.oid, 'EXECUTE') AS service_role_can,
--          has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_can,
--          has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authenticated_can
--     FROM pg_proc p WHERE p.proname = 'analysis_upsert_schedule';
--   -- expect ONE row: (...,smallint,smallint,time), true, {search_path=""}, true, false, false
--   SELECT conname, convalidated FROM pg_constraint
--    WHERE conrelid = 'public.analysis_schedules'::regclass AND conname LIKE 'analysis_schedules_%run%';
--   -- expect 5 rows, all convalidated = true
--   SELECT count(*) FROM public.analysis_schedules WHERE enabled AND run_time IS NULL;  -- expect 0
