-- 071 rollback: restore the 065 definition (four industry IDs only).
-- Bots confirmed on newer industries then fail observation publishing again.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE OR REPLACE FUNCTION public.analysis_apply_business_observation(
  p_event_id bigint,p_lease_token uuid,p_operation text,p_output jsonb DEFAULT '{}'
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE e public.automation_events; m public.messages; b public.chatbots;
        cid bigint; outcome jsonb; recorded jsonb; action text; state text;
BEGIN
  IF p_operation IS NULL OR p_operation NOT IN ('inspect','start','finish','uncertain','skip')
     OR p_lease_token IS NULL THEN
    RAISE EXCEPTION 'invalid_observation_operation' USING ERRCODE='22023';
  END IF;
  SELECT * INTO e FROM public.automation_events WHERE id=p_event_id FOR UPDATE;
  IF NOT FOUND OR e.event_type<>'business_observation' OR e.lease_token IS DISTINCT FROM p_lease_token THEN
    RAISE EXCEPTION 'observation_lease_lost' USING ERRCODE='40001';
  END IF;
  IF e.status='completed' THEN RETURN jsonb_build_object('status','completed','result',e.result); END IF;
  IF e.status='needs_review' THEN RETURN jsonb_build_object('status','needs_review'); END IF;
  IF e.status<>'running' OR e.lease_expires_at IS NULL OR e.lease_expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'observation_lease_lost' USING ERRCODE='40001';
  END IF;
  IF coalesce(e.payload->>'message_id','') !~ '^[1-9][0-9]{0,18}$' THEN
    RAISE EXCEPTION 'observation_message_invalid' USING ERRCODE='22023';
  END IF;
  SELECT * INTO m FROM public.messages WHERE id=(e.payload->>'message_id')::bigint;
  IF NOT FOUND OR m.sender_type IS DISTINCT FROM 'customer' OR m.message_type IS DISTINCT FROM 'text'
     OR m.ai_generated IS DISTINCT FROM false THEN
    RAISE EXCEPTION 'observation_message_denied' USING ERRCODE='42501';
  END IF;
  SELECT c.chatbot_id INTO cid FROM public.conversations c WHERE c.id=m.conversation_id;
  SELECT * INTO b FROM public.chatbots WHERE id=cid AND id=e.chatbot_id AND company_id=e.company_id FOR SHARE;
  IF NOT FOUND OR b.deleted_at IS NOT NULL OR b.status='archived' THEN
    RAISE EXCEPTION 'observation_scope_denied' USING ERRCODE='42501';
  END IF;
  IF p_operation='uncertain' THEN
    IF NOT e.external_effect_started THEN
      RAISE EXCEPTION 'classifier_not_started' USING ERRCODE='40001';
    END IF;
    UPDATE public.automation_events SET status='needs_review',external_effect_started=true,
      result=jsonb_build_object('model_state','uncertain'),error_message='classifier_result_uncertain',
      lease_expires_at=NULL,updated_at=now() WHERE id=e.id;
    RETURN jsonb_build_object('status','needs_review');
  END IF;
  -- Disable is effective for queued jobs and for a known completed classifier
  -- result. An ambiguous paid call remains needs_review, never safe to retry.
  IF NOT b.analysis_recording_enabled THEN
    IF e.external_effect_started AND p_operation<>'finish' THEN
      UPDATE public.automation_events SET status='needs_review',lease_expires_at=NULL,
        error_message='classifier_result_uncertain',updated_at=now() WHERE id=e.id;
      RETURN jsonb_build_object('status','needs_review');
    END IF;
    outcome := jsonb_build_object('model_state','skipped','reason','recording_disabled');
    UPDATE public.automation_events SET status='completed',external_effect_started=false,
      result=outcome,lease_expires_at=NULL,updated_at=now() WHERE id=e.id;
    RETURN jsonb_build_object('status','completed','result',outcome);
  END IF;
  IF p_operation='inspect' THEN
    RETURN jsonb_build_object('status','running','company_id',e.company_id,'chatbot_id',e.chatbot_id,
      'message',jsonb_build_object('id',m.id,'conversation_id',m.conversation_id,'text',m.message_text),
      'model_started',e.external_effect_started);
  ELSIF p_operation='start' THEN
    IF e.external_effect_started OR e.result->>'model_state'='started' THEN
      RETURN jsonb_build_object('started',false);
    END IF;
    UPDATE public.automation_events SET external_effect_started=true,
      result=jsonb_build_object('model_state','started'),updated_at=now() WHERE id=e.id;
    RETURN jsonb_build_object('started',true);
  ELSIF p_operation='skip' THEN
    IF e.external_effect_started THEN RAISE EXCEPTION 'classifier_already_started' USING ERRCODE='40001'; END IF;
    outcome := jsonb_build_object('model_state','skipped','reason','no_business_action');
  ELSE
    IF NOT e.external_effect_started OR e.result->>'model_state' IS DISTINCT FROM 'started' THEN
      RAISE EXCEPTION 'classifier_not_started' USING ERRCODE='40001';
    END IF;
    IF jsonb_typeof(p_output) IS DISTINCT FROM 'object' OR octet_length(p_output::text)>2048
       OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_output) k WHERE k NOT IN ('action_type','status','industry_id','context_truncated')) THEN
      RAISE EXCEPTION 'invalid_classifier_output' USING ERRCODE='22023';
    END IF;
    IF p_output->>'industry_id' IS NULL OR p_output->>'industry_id' NOT IN ('general','restaurant','clinic','tuition_center')
       OR jsonb_typeof(p_output->'context_truncated') IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'invalid_classifier_metadata' USING ERRCODE='22023';
    END IF;
    action := p_output->>'action_type'; state := p_output->>'status';
    IF action IS NULL OR action NOT IN ('none','booking','registration','order','service_request')
       OR state IS NULL OR state NOT IN ('none','intent','requested')
       OR ((action='none') IS DISTINCT FROM (state='none')) THEN
      RAISE EXCEPTION 'invalid_classifier_outcome' USING ERRCODE='22023';
    END IF;
    IF action<>'none' THEN
      recorded := public.analysis_record_business_event(e.company_id,e.chatbot_id,m.conversation_id,NULL,
        'customer-message:' || m.id::text,action,state,'observation',NULL,ARRAY[m.id],
        jsonb_build_object('classifier_version','1','industry_id',p_output->>'industry_id',
                          'context_truncated',coalesce((p_output->>'context_truncated')::boolean,false)));
    END IF;
    outcome := jsonb_build_object('model_state','succeeded','action_type',action,
      'business_event_id',recorded->'id','message_id',m.id);
  END IF;
  UPDATE public.automation_events SET status='completed',external_effect_started=false,
    result=outcome,lease_expires_at=NULL,updated_at=now() WHERE id=e.id;
  RETURN jsonb_build_object('status','completed','result',outcome);
END $$;
REVOKE ALL ON FUNCTION public.analysis_apply_business_observation(bigint,uuid,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.analysis_apply_business_observation(bigint,uuid,text,jsonb) TO service_role;
COMMIT;
