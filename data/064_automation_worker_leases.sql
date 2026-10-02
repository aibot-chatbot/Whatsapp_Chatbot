-- Apply after 063. Worker-only RPCs; do not enable workers before both migrate.
-- DEFINER is required to settle analysis_reports without granting direct UPDATE
-- around its fenced API. Only service_role may execute; search_path is empty.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
ALTER TABLE public.automation_events
  ADD COLUMN IF NOT EXISTS lease_token uuid,
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 3,
  ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS external_effect_started boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS worker_kind text GENERATED ALWAYS AS (
    CASE WHEN event_type = 'agent_report' THEN 'agent_report'
         WHEN event_type = 'business_observation' THEN 'business_observation'
         WHEN event_type = 'tuition_reminder' THEN 'tuition_reminder'
         WHEN event_type IN ('knowledge_document_follow_up','agent_notification','schedule_tick') THEN 'n8n'
         ELSE 'audit' END
  ) STORED;
ALTER TABLE public.automation_events DROP CONSTRAINT IF EXISTS automation_events_type_check;
ALTER TABLE public.automation_events ADD CONSTRAINT automation_events_type_check
  CHECK (event_type IN ('knowledge_document_follow_up','crm_stage_transition','agent_report','business_observation','tuition_reminder','agent_notification','schedule_tick'));
ALTER TABLE public.automation_events DROP CONSTRAINT IF EXISTS automation_events_status_check;
ALTER TABLE public.automation_events ADD CONSTRAINT automation_events_status_check
  CHECK (status IN ('queued','running','completed','failed','blocked','needs_review'));
ALTER TABLE public.automation_events DROP CONSTRAINT IF EXISTS automation_events_attempts_check;
ALTER TABLE public.automation_events ADD CONSTRAINT automation_events_attempts_check
  CHECK (attempts >= 0 AND max_attempts BETWEEN 1 AND 10);
CREATE INDEX IF NOT EXISTS automation_events_worker_due_idx
  ON public.automation_events(worker_kind,available_at,id) WHERE status IN ('queued','running');

CREATE OR REPLACE FUNCTION public.claim_automation_events_v1(
  p_worker_kind text, p_limit integer DEFAULT 1, p_lease_seconds integer DEFAULT 300
) RETURNS SETOF public.automation_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $function$
DECLARE v_row public.automation_events%ROWTYPE; v_now timestamptz := clock_timestamp();
BEGIN
  IF p_worker_kind NOT IN ('agent_report','business_observation','tuition_reminder','n8n') OR p_worker_kind IS NULL
     OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50
     OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid worker claim' USING ERRCODE='22023';
  END IF;
  FOR v_row IN
    SELECT e.* FROM public.automation_events e
    WHERE e.worker_kind=p_worker_kind
      AND ((e.status='queued' AND e.available_at<=v_now)
        OR (e.status='running' AND COALESCE(e.lease_expires_at,e.updated_at)<=v_now))
    ORDER BY e.available_at,e.id FOR UPDATE SKIP LOCKED LIMIT p_limit
  LOOP
    -- An expired provider call may already have billed or delivered. Never replay it.
    IF v_row.external_effect_started THEN
      UPDATE public.automation_events SET status='needs_review',lease_expires_at=NULL,
        error_message='external_result_uncertain',updated_at=v_now WHERE id=v_row.id;
      IF v_row.event_type='agent_report' THEN
        UPDATE public.analysis_reports SET status='needs_review',error_code='provider_result_uncertain',updated_at=v_now
          WHERE automation_event_id=v_row.id AND status IN ('queued','running');
      END IF;
      IF v_row.event_type='tuition_reminder' THEN
        UPDATE public.tuition_bookings SET reminder_status='needs_review',reminder_unavailable_reason='provider_result_uncertain',updated_at=v_now
          WHERE id=(v_row.payload->>'booking_id')::uuid AND company_id=v_row.company_id AND chatbot_id=v_row.chatbot_id
            AND version=(v_row.payload->>'booking_version')::integer AND reminder_status='pending';
      END IF;
    ELSIF v_row.attempts>=v_row.max_attempts THEN
      UPDATE public.automation_events SET status='failed',lease_expires_at=NULL,
        error_message='attempts_exhausted',updated_at=v_now WHERE id=v_row.id;
      IF v_row.event_type='agent_report' THEN
        UPDATE public.analysis_reports SET status='failed',error_code='attempts_exhausted',updated_at=v_now
          WHERE automation_event_id=v_row.id AND status IN ('queued','running');
      END IF;
      IF v_row.event_type='tuition_reminder' THEN
        UPDATE public.tuition_bookings SET reminder_status='failed',reminder_unavailable_reason='attempts_exhausted',updated_at=v_now
          WHERE id=(v_row.payload->>'booking_id')::uuid AND company_id=v_row.company_id AND chatbot_id=v_row.chatbot_id
            AND version=(v_row.payload->>'booking_version')::integer AND reminder_status='pending';
      END IF;
    ELSE
      RETURN QUERY UPDATE public.automation_events e
        SET status='running',attempts=e.attempts+1,lease_token=gen_random_uuid(),
          lease_expires_at=v_now+make_interval(secs=>p_lease_seconds),updated_at=v_now
        WHERE e.id=v_row.id RETURNING e.*;
    END IF;
  END LOOP;
END $function$;

CREATE OR REPLACE FUNCTION public.renew_automation_event_lease_v1(
  p_event_id bigint,p_worker_kind text,p_lease_token uuid,p_lease_seconds integer DEFAULT 300
) RETURNS SETOF public.automation_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $function$
BEGIN
  IF p_worker_kind NOT IN ('agent_report','business_observation','tuition_reminder','n8n') OR p_worker_kind IS NULL
     OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
    RAISE EXCEPTION 'invalid worker renewal' USING ERRCODE='22023';
  END IF;
  RETURN QUERY UPDATE public.automation_events e SET
    lease_expires_at=clock_timestamp()+make_interval(secs=>p_lease_seconds),updated_at=clock_timestamp()
    WHERE e.id=p_event_id AND e.worker_kind=p_worker_kind AND e.status='running'
      AND e.lease_token=p_lease_token AND e.lease_expires_at>clock_timestamp() RETURNING e.*;
END $function$;

CREATE OR REPLACE FUNCTION public.finish_automation_event_v1(
  p_event_id bigint,p_worker_kind text,p_lease_token uuid,p_status text,
  p_result jsonb DEFAULT NULL,p_error_message text DEFAULT NULL,p_retryable boolean DEFAULT false
) RETURNS SETOF public.automation_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $function$
DECLARE v_row public.automation_events%ROWTYPE; v_status text;
BEGIN
  IF p_worker_kind NOT IN ('agent_report','business_observation','tuition_reminder','n8n') OR p_worker_kind IS NULL
     OR p_status NOT IN ('completed','failed','needs_review') OR p_status IS NULL
     OR (p_result IS NOT NULL AND jsonb_typeof(p_result)<>'object') THEN
    RAISE EXCEPTION 'invalid worker outcome' USING ERRCODE='22023';
  END IF;
  SELECT * INTO v_row FROM public.automation_events WHERE id=p_event_id FOR UPDATE;
  IF NOT FOUND OR v_row.worker_kind<>p_worker_kind OR v_row.lease_token IS DISTINCT FROM p_lease_token
    OR p_lease_token IS NULL THEN RETURN; END IF;
  -- Retrying precisely the same settled callback is safe; a different result is not.
  IF v_row.status=p_status AND v_row.status IN ('completed','failed','needs_review') THEN
    RETURN NEXT v_row; RETURN;
  END IF;
  IF v_row.status<>'running' OR v_row.lease_expires_at<=clock_timestamp()
    OR v_row.lease_expires_at IS NULL THEN RETURN; END IF;
  v_status := p_status;
  IF v_row.external_effect_started THEN v_status := 'needs_review';
  ELSIF p_status='failed' AND p_retryable AND v_row.attempts<v_row.max_attempts THEN v_status := 'queued';
  END IF;
  RETURN QUERY UPDATE public.automation_events e SET status=v_status,result=p_result,
    error_message=left(p_error_message,500),lease_expires_at=NULL,updated_at=clock_timestamp(),
    available_at=CASE WHEN v_status='queued' THEN clock_timestamp()+make_interval(secs=>LEAST(900,15*power(2,v_row.attempts-1)::integer)) ELSE e.available_at END
    WHERE e.id=p_event_id RETURNING e.*;
  IF v_row.event_type='agent_report' AND v_status IN ('failed','needs_review') THEN
    UPDATE public.analysis_reports SET status=v_status,
      error_code=CASE WHEN v_status='needs_review' THEN 'provider_result_uncertain' ELSE 'worker_failed' END,
      updated_at=clock_timestamp()
      WHERE automation_event_id=p_event_id AND status IN ('queued','running');
  END IF;
  IF v_row.event_type='tuition_reminder' AND v_status IN ('failed','needs_review') THEN
    UPDATE public.tuition_bookings SET reminder_status=v_status,
      reminder_unavailable_reason=CASE WHEN v_status='needs_review' THEN 'provider_result_uncertain' ELSE 'worker_failed' END,
      updated_at=clock_timestamp()
      WHERE id=(v_row.payload->>'booking_id')::uuid AND company_id=v_row.company_id AND chatbot_id=v_row.chatbot_id
        AND version=(v_row.payload->>'booking_version')::integer AND reminder_status='pending';
  END IF;
END $function$;

REVOKE ALL ON FUNCTION public.claim_automation_events_v1(text,integer,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.renew_automation_event_lease_v1(bigint,text,uuid,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.finish_automation_event_v1(bigint,text,uuid,text,jsonb,text,boolean) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_automation_events_v1(text,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_automation_event_lease_v1(bigint,text,uuid,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_automation_event_v1(bigint,text,uuid,text,jsonb,text,boolean) TO service_role;
COMMIT;
