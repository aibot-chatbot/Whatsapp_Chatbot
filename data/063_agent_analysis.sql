-- Analysis is private to the Flask service. Apply 064 before enabling workers.
-- New tables only; no backfill of customer conversations or messages.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.business_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
    conversation_id bigint NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    actor_user_id bigint REFERENCES public.users(id) ON DELETE SET NULL,
    event_key text NOT NULL CHECK (length(event_key) BETWEEN 1 AND 200),
    action_type text NOT NULL CHECK (action_type ~ '^[a-z][a-z0-9_]{0,63}$'),
    status text NOT NULL CHECK (status IN ('intent','requested','confirmed','completed','failed','cancelled','rescheduled')),
    record_id text CHECK (length(record_id) BETWEEN 1 AND 200),
    source text NOT NULL CHECK (source IN ('observation','business_service')),
    evidence_message_ids bigint[] NOT NULL DEFAULT '{}',
    details jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details)='object' AND octet_length(details::text)<=16384),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(company_id,chatbot_id,conversation_id,event_key),
    CHECK (cardinality(evidence_message_ids)<=50),
    CHECK (source<>'observation' OR cardinality(evidence_message_ids)>0),
    CHECK ((source='observation' AND status IN ('intent','requested')) OR
           (source='business_service' AND record_id IS NOT NULL))
);
CREATE INDEX business_events_scope_time ON public.business_events(company_id,chatbot_id,created_at,id);
CREATE INDEX business_events_conversation ON public.business_events(conversation_id,id);

CREATE TABLE public.analysis_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
    actor_user_id bigint NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    client_message_id text NOT NULL CHECK (length(client_message_id) BETWEEN 1 AND 200),
    request_text text NOT NULL CHECK (length(request_text) BETWEEN 1 AND 2000),
    request_spec jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(request_spec)='object' AND octet_length(request_spec::text)<=16384),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','complete','partial','failed','needs_review','needs_input')),
    automation_event_id bigint UNIQUE REFERENCES public.automation_events(id) ON DELETE RESTRICT,
    snapshot jsonb CHECK (jsonb_typeof(snapshot)='object' AND octet_length(snapshot::text)<=1048576),
    result jsonb CHECK (jsonb_typeof(result)='object' AND octet_length(result::text)<=1048576),
    manifest jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(manifest)='object'),
    error_code text CHECK (error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(company_id,chatbot_id,actor_user_id,client_message_id)
);
CREATE INDEX analysis_reports_scope_time ON public.analysis_reports(company_id,chatbot_id,created_at DESC,id);

CREATE TABLE public.analysis_model_steps (
    report_id uuid NOT NULL REFERENCES public.analysis_reports(id) ON DELETE CASCADE,
    step_id text NOT NULL CHECK (step_id IN ('plan','analyze')),
    state text NOT NULL CHECK (state IN ('started','succeeded','uncertain')),
    lease_token uuid NOT NULL,
    output jsonb CHECK (jsonb_typeof(output)='object' AND octet_length(output::text)<=1048576),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY(report_id,step_id)
);

CREATE TABLE public.analysis_schedules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
    actor_user_id bigint NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    frequency text NOT NULL CHECK (frequency IN ('weekly','monthly')),
    timezone text NOT NULL DEFAULT 'Asia/Kuala_Lumpur' CHECK (timezone='Asia/Kuala_Lumpur'),
    enabled boolean NOT NULL DEFAULT false,
    last_period_key text CHECK (length(last_period_key) BETWEEN 1 AND 100),
    next_due_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(company_id,chatbot_id,frequency)
);
CREATE INDEX analysis_schedules_due ON public.analysis_schedules(next_due_at) WHERE enabled;

ALTER TABLE public.business_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analysis_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analysis_model_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analysis_schedules ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.business_events,public.analysis_reports,public.analysis_model_steps,public.analysis_schedules FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON SEQUENCE public.business_events_id_seq FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.business_events,public.analysis_reports,public.analysis_model_steps,public.analysis_schedules TO service_role;

-- No browser JWT assumption: callers are authenticated/authorized by Flask.
CREATE FUNCTION public.analysis_require_actor(p_company_id bigint,p_chatbot_id bigint,p_actor_user_id bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.chatbots WHERE id=p_chatbot_id AND company_id=p_company_id
                   AND deleted_at IS NULL AND status IS DISTINCT FROM 'archived') THEN
        RAISE EXCEPTION 'analysis_scope_denied' USING ERRCODE='42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.users WHERE id=p_actor_user_id AND company_id=p_company_id
                   AND status='active' AND role IN ('owner','admin')) THEN
        RAISE EXCEPTION 'analysis_actor_denied' USING ERRCODE='42501';
    END IF;
END $$;

CREATE FUNCTION public.analysis_create_report_request(p_company_id bigint,p_chatbot_id bigint,p_actor_user_id bigint,
    p_client_message_id text,p_text text,p_request_spec jsonb DEFAULT '{}')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE r public.analysis_reports; eid bigint;
BEGIN
    PERFORM public.analysis_require_actor(p_company_id,p_chatbot_id,p_actor_user_id);
    -- Serialize admission for one company across its Bots and administrators.
    PERFORM id FROM public.companies WHERE id=p_company_id FOR UPDATE;
    SELECT * INTO r FROM public.analysis_reports WHERE company_id=p_company_id AND chatbot_id=p_chatbot_id
      AND actor_user_id=p_actor_user_id AND client_message_id=p_client_message_id;
    IF r.id IS NOT NULL THEN
        IF r.request_text IS DISTINCT FROM p_text OR r.request_spec IS DISTINCT FROM p_request_spec THEN
            RAISE EXCEPTION 'analysis_idempotency_conflict' USING ERRCODE='22023';
        END IF;
        RETURN to_jsonb(r);
    END IF;
    IF (SELECT count(*) FROM public.analysis_reports WHERE company_id=p_company_id AND status IN ('queued','running')) >= 10 THEN
        RAISE EXCEPTION 'analysis_pending_limit' USING ERRCODE='54000';
    END IF;
    INSERT INTO public.analysis_reports(company_id,chatbot_id,actor_user_id,client_message_id,request_text,request_spec)
      VALUES(p_company_id,p_chatbot_id,p_actor_user_id,p_client_message_id,p_text,p_request_spec)
      ON CONFLICT(company_id,chatbot_id,actor_user_id,client_message_id) DO NOTHING RETURNING * INTO r;
    IF r.id IS NULL THEN
        SELECT * INTO r FROM public.analysis_reports WHERE company_id=p_company_id AND chatbot_id=p_chatbot_id
          AND actor_user_id=p_actor_user_id AND client_message_id=p_client_message_id;
        IF r.request_text IS DISTINCT FROM p_text OR r.request_spec IS DISTINCT FROM p_request_spec THEN
            RAISE EXCEPTION 'analysis_idempotency_conflict' USING ERRCODE='22023';
        END IF;
        RETURN to_jsonb(r);
    END IF;
    INSERT INTO public.automation_events(company_id,chatbot_id,event_type,status,idempotency_key,payload)
      VALUES(p_company_id,p_chatbot_id,'agent_report','queued','agent_report:'||r.run_id::text,
        jsonb_build_object('report_id',r.id,'run_id',r.run_id)) RETURNING id INTO eid;
    UPDATE public.analysis_reports SET automation_event_id=eid WHERE id=r.id RETURNING * INTO r;
    RETURN to_jsonb(r);
END $$;

CREATE FUNCTION public.analysis_record_business_event(p_company_id bigint,p_chatbot_id bigint,p_conversation_id bigint,
    p_actor_user_id bigint,p_event_key text,p_action_type text,p_status text,p_source text,
    p_record_id text DEFAULT NULL,p_evidence_message_ids bigint[] DEFAULT '{}',p_details jsonb DEFAULT '{}')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE r public.business_events;
BEGIN
    -- Always validate ownership, even for customer-originated events with no actor.
    IF NOT EXISTS (SELECT 1 FROM public.conversations c JOIN public.chatbots b ON b.id=c.chatbot_id
        WHERE c.id=p_conversation_id AND b.id=p_chatbot_id AND b.company_id=p_company_id) THEN
        RAISE EXCEPTION 'business_event_scope_denied' USING ERRCODE='42501';
    END IF;
    IF p_actor_user_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.users
        WHERE id=p_actor_user_id AND company_id=p_company_id AND status='active') THEN
        RAISE EXCEPTION 'business_event_actor_denied' USING ERRCODE='42501';
    END IF;
    IF EXISTS (SELECT 1 FROM unnest(p_evidence_message_ids) evidence(id)
        WHERE NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id=evidence.id AND m.conversation_id=p_conversation_id)) THEN
        RAISE EXCEPTION 'business_event_evidence_denied' USING ERRCODE='42501';
    END IF;
    INSERT INTO public.business_events(company_id,chatbot_id,conversation_id,actor_user_id,event_key,action_type,status,
      source,record_id,evidence_message_ids,details)
      VALUES(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id,p_event_key,p_action_type,p_status,
        p_source,p_record_id,p_evidence_message_ids,p_details)
      ON CONFLICT(company_id,chatbot_id,conversation_id,event_key) DO NOTHING RETURNING * INTO r;
    IF r.id IS NULL THEN
        SELECT * INTO r FROM public.business_events WHERE company_id=p_company_id AND chatbot_id=p_chatbot_id
          AND conversation_id=p_conversation_id AND event_key=p_event_key;
        IF r.action_type IS DISTINCT FROM p_action_type OR r.status IS DISTINCT FROM p_status OR r.source IS DISTINCT FROM p_source
           OR r.record_id IS DISTINCT FROM p_record_id OR r.evidence_message_ids IS DISTINCT FROM p_evidence_message_ids
           OR r.details IS DISTINCT FROM p_details OR r.actor_user_id IS DISTINCT FROM p_actor_user_id THEN
            RAISE EXCEPTION 'business_event_idempotency_conflict' USING ERRCODE='22023';
        END IF;
    END IF;
    RETURN to_jsonb(r);
END $$;

-- 064 adds lease fields. PL/pgSQL resolves these statements when called,
-- so deploy both migrations before enabling Analysis or its worker.
CREATE FUNCTION public.analysis_apply_run(p_company_id bigint,p_chatbot_id bigint,p_report_id uuid,
    p_event_id bigint,p_lease_token uuid,p_operation text,p_payload jsonb DEFAULT '{}')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE e record; r public.analysis_reports; s public.analysis_model_steps; item record; facts_only boolean := false;
BEGIN
    SELECT * INTO e FROM public.automation_events WHERE id=p_event_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'analysis_lease_lost' USING ERRCODE='40001'; END IF;
    IF e.company_id IS DISTINCT FROM p_company_id OR e.chatbot_id IS DISTINCT FROM p_chatbot_id
       OR e.event_type<>'agent_report' OR e.status<>'running' OR e.lease_token IS DISTINCT FROM p_lease_token
       OR p_lease_token IS NULL OR e.lease_expires_at IS NULL OR e.lease_expires_at<=clock_timestamp() THEN
        RAISE EXCEPTION 'analysis_lease_lost' USING ERRCODE='40001';
    END IF;
    SELECT * INTO r FROM public.analysis_reports WHERE id=p_report_id AND company_id=p_company_id
      AND chatbot_id=p_chatbot_id AND automation_event_id=p_event_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'analysis_scope_denied' USING ERRCODE='42501'; END IF;
    PERFORM public.analysis_require_actor(r.company_id,r.chatbot_id,r.actor_user_id);
    IF r.status NOT IN ('queued','running') THEN
        RAISE EXCEPTION 'analysis_already_terminal' USING ERRCODE='22023';
    END IF;
    IF p_operation='snapshot' THEN
        IF r.snapshot IS NOT NULL AND r.snapshot IS DISTINCT FROM p_payload THEN
            RAISE EXCEPTION 'analysis_snapshot_immutable' USING ERRCODE='22023';
        END IF;
        UPDATE public.analysis_reports SET snapshot=p_payload,status='running',updated_at=now()
          WHERE id=r.id RETURNING * INTO r;
    ELSIF p_operation='begin_step' THEN
        IF p_payload->>'step_id' NOT IN ('plan','analyze') OR p_payload->>'step_id' IS NULL THEN
            RAISE EXCEPTION 'analysis_invalid_step' USING ERRCODE='22023';
        END IF;
        SELECT * INTO s FROM public.analysis_model_steps WHERE report_id=r.id AND step_id=p_payload->>'step_id';
        IF FOUND THEN RETURN jsonb_build_object('started',false,'step',to_jsonb(s)); END IF;
        IF EXISTS (SELECT 1 FROM public.analysis_model_steps WHERE report_id=r.id AND state<>'succeeded') THEN
            RAISE EXCEPTION 'analysis_previous_step_uncertain' USING ERRCODE='22023';
        END IF;
        IF p_payload->>'step_id'='analyze' AND r.snapshot IS NULL THEN
            RAISE EXCEPTION 'analysis_snapshot_required' USING ERRCODE='22023';
        END IF;
        UPDATE public.automation_events SET external_effect_started=true WHERE id=e.id;
        INSERT INTO public.analysis_model_steps(report_id,step_id,state,lease_token)
          VALUES(r.id,p_payload->>'step_id','started',p_lease_token) RETURNING * INTO s;
        UPDATE public.analysis_reports SET status='running',updated_at=now() WHERE id=r.id;
        RETURN jsonb_build_object('started',true,'step',to_jsonb(s));
    ELSIF p_operation='finish_step' THEN
        IF p_payload->>'state' NOT IN ('succeeded','uncertain') OR p_payload->>'state' IS NULL THEN
            RAISE EXCEPTION 'analysis_invalid_step_state' USING ERRCODE='22023';
        END IF;
        UPDATE public.analysis_model_steps SET state=p_payload->>'state',output=p_payload->'output',finished_at=now()
          WHERE report_id=r.id AND step_id=p_payload->>'step_id' AND state='started' AND lease_token=p_lease_token
          RETURNING * INTO s;
        IF NOT FOUND THEN RAISE EXCEPTION 'analysis_step_conflict' USING ERRCODE='40001'; END IF;
        IF s.state='succeeded' THEN
            UPDATE public.automation_events SET external_effect_started=false WHERE id=e.id;
        END IF;
        RETURN to_jsonb(s);
    ELSIF p_operation='finish' THEN
        IF p_payload->>'status' NOT IN ('complete','partial','failed','needs_review','needs_input')
           OR p_payload->>'status' IS NULL THEN
            RAISE EXCEPTION 'analysis_invalid_status' USING ERRCODE='22023';
        END IF;
        IF p_payload->>'status' IN ('complete','partial') THEN
            SELECT * INTO s FROM public.analysis_model_steps WHERE report_id=r.id AND step_id='analyze';
            facts_only := coalesce(p_payload->>'status'='partial'
              AND p_payload->'result'->>'analysis_status'='needs_review'
              AND p_payload->'result'->>'narrative'=''
              AND p_payload->'result'->'sections'='[]'::jsonb
              AND s.state IN ('started','uncertain') AND e.external_effect_started,false) IS TRUE;
            IF facts_only AND (s.report_id IS NULL OR NOT e.external_effect_started) THEN
                RAISE EXCEPTION 'analysis_incomplete_result' USING ERRCODE='22023';
            END IF;
            IF s.report_id IS NULL OR r.snapshot IS NULL
              OR coalesce(r.snapshot->>'snapshot_sha256','') !~ '^[0-9a-f]{64}$'
              OR p_payload->'result'->'snapshot' IS DISTINCT FROM r.snapshot
              OR (NOT facts_only AND (s.state<>'succeeded'
                OR s.output->>'snapshot_sha256' IS DISTINCT FROM r.snapshot->>'snapshot_sha256'
                OR p_payload->'result'->'narrative' IS DISTINCT FROM s.output->'narrative'
                OR EXISTS (SELECT 1 FROM public.analysis_model_steps WHERE report_id=r.id AND state<>'succeeded'))) THEN
                RAISE EXCEPTION 'analysis_incomplete_result' USING ERRCODE='22023';
            END IF;
        END IF;
        IF jsonb_typeof(coalesce(p_payload->'manifest','{}'::jsonb))<>'object' THEN
            RAISE EXCEPTION 'analysis_invalid_manifest' USING ERRCODE='22023';
        END IF;
        FOR item IN SELECT * FROM jsonb_each(coalesce(p_payload->'manifest','{}'::jsonb)) LOOP
            IF item.key NOT IN ('pdf','xlsx','json') OR jsonb_typeof(item.value)<>'object'
               OR item.value->>'format' IS DISTINCT FROM item.key
               OR item.value->>'version' IS DISTINCT FROM p_lease_token::text
               OR coalesce(item.value->>'sha256','') !~ '^[0-9a-f]{64}$'
               OR jsonb_typeof(item.value->'size') IS DISTINCT FROM 'number'
               OR coalesce(item.value->>'size','') !~ '^[1-9][0-9]{0,8}$'
               OR (item.value - ARRAY['format','version','sha256','size']) <> '{}'::jsonb THEN
                RAISE EXCEPTION 'analysis_invalid_manifest' USING ERRCODE='22023';
            END IF;
            IF (item.value->>'size')::bigint>33554432 THEN
                RAISE EXCEPTION 'analysis_artifact_too_large' USING ERRCODE='22023';
            END IF;
        END LOOP;
        UPDATE public.analysis_reports SET status=p_payload->>'status',result=p_payload->'result',
          manifest=coalesce(p_payload->'manifest','{}'::jsonb),error_code=p_payload->>'error_code',updated_at=now()
          WHERE id=r.id RETURNING * INTO r;
        UPDATE public.automation_events SET
          status=CASE WHEN facts_only THEN 'needs_review' WHEN r.status IN ('complete','partial','needs_input') THEN 'completed' ELSE r.status END,
          result=jsonb_build_object('report_id',r.id,'run_id',r.run_id,'status',r.status),
          error_message=r.error_code,lease_expires_at=NULL,updated_at=now() WHERE id=e.id;
    ELSE RAISE EXCEPTION 'analysis_invalid_operation' USING ERRCODE='22023';
    END IF;
    RETURN to_jsonb(r);
END $$;

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

CREATE FUNCTION public.analysis_enqueue_schedule(p_company_id bigint,p_chatbot_id bigint,p_schedule_id uuid,
    p_period_key text,p_request_spec jsonb,p_next_due_at timestamptz)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE s public.analysis_schedules; r jsonb;
BEGIN
    SELECT * INTO s FROM public.analysis_schedules WHERE id=p_schedule_id AND company_id=p_company_id
      AND chatbot_id=p_chatbot_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'analysis_scope_denied' USING ERRCODE='42501'; END IF;
    IF NOT s.enabled OR s.next_due_at IS NULL OR s.next_due_at>clock_timestamp() OR s.last_period_key=p_period_key THEN
        RETURN jsonb_build_object('enqueued',false);
    END IF;
    IF p_next_due_at IS NULL OR p_next_due_at<=clock_timestamp() OR length(p_period_key) NOT BETWEEN 1 AND 100 THEN
        RAISE EXCEPTION 'analysis_invalid_schedule_period' USING ERRCODE='22023';
    END IF;
    r := public.analysis_create_report_request(s.company_id,s.chatbot_id,s.actor_user_id,
      'schedule:'||s.id::text||':'||p_period_key,'Scheduled '||s.frequency||' report',p_request_spec);
    UPDATE public.analysis_schedules SET last_period_key=p_period_key,next_due_at=p_next_due_at,updated_at=now() WHERE id=s.id;
    RETURN jsonb_build_object('enqueued',true,'report',r);
END $$;

REVOKE ALL ON FUNCTION public.analysis_require_actor(bigint,bigint,bigint) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.analysis_create_report_request(bigint,bigint,bigint,text,text,jsonb),
    public.analysis_record_business_event(bigint,bigint,bigint,bigint,text,text,text,text,text,bigint[],jsonb),
    public.analysis_apply_run(bigint,bigint,uuid,bigint,uuid,text,jsonb),
    public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz),
    public.analysis_enqueue_schedule(bigint,bigint,uuid,text,jsonb,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.analysis_create_report_request(bigint,bigint,bigint,text,text,jsonb),
    public.analysis_record_business_event(bigint,bigint,bigint,bigint,text,text,text,text,text,bigint[],jsonb),
    public.analysis_apply_run(bigint,bigint,uuid,bigint,uuid,text,jsonb),
    public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz),
    public.analysis_enqueue_schedule(bigint,bigint,uuid,text,jsonb,timestamptz) TO service_role;
COMMIT;
