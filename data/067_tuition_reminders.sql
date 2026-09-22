-- Apply after 066. Telegram only; no overdue catch-up or uncertain retry.
BEGIN;
SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='30s';
ALTER TABLE public.tuition_bookings DROP CONSTRAINT IF EXISTS tuition_bookings_reminder_status_check;
ALTER TABLE public.tuition_bookings ADD CONSTRAINT tuition_bookings_reminder_status_check
 CHECK(reminder_status IN ('not_requested','unsupported','pending','sent','failed','cancelled','skipped','needs_review'));
CREATE INDEX IF NOT EXISTS tuition_reminder_due ON public.tuition_bookings(reminder_at,id)
 WHERE reminder_enabled AND reminder_status='pending' AND status='confirmed';

CREATE OR REPLACE FUNCTION public.tuition_enqueue_reminders(p_limit integer DEFAULT 100) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE b public.tuition_bookings; n integer:=0; skipped integer:=0; added integer; epoch bigint; v_now timestamptz:=clock_timestamp();
BEGIN
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'invalid_limit' USING ERRCODE='22023'; END IF;
 FOR b IN SELECT t.* FROM public.tuition_bookings t WHERE t.status='confirmed' AND t.reminder_enabled
    AND t.reminder_consent AND t.reminder_status='pending' AND t.reminder_at<=v_now
    AND NOT EXISTS(SELECT 1 FROM public.automation_events e WHERE e.company_id=t.company_id
      AND e.idempotency_key='tuition_reminder:'||t.id::text||':'||t.version::text)
    ORDER BY t.reminder_at,t.id LIMIT p_limit
 LOOP
   IF b.reminder_at<v_now-interval '5 minutes' THEN
     -- Do not relabel an already-admitted/in-flight delivery as skipped.
     IF NOT EXISTS(SELECT 1 FROM public.automation_events WHERE company_id=b.company_id
       AND idempotency_key='tuition_reminder:'||b.id::text||':'||b.version::text) THEN
       -- The scan does not lock bookings. Recheck the version and original due
       -- time after any concurrent reschedule/cancel has released the row.
       UPDATE public.tuition_bookings SET reminder_status='skipped',reminder_unavailable_reason='overdue',updated_at=v_now
         WHERE id=b.id AND version=b.version AND status='confirmed'
           AND reminder_enabled AND reminder_consent AND reminder_status='pending'
           AND reminder_at=b.reminder_at AND reminder_at<v_now-interval '5 minutes';
       GET DIAGNOSTICS added=ROW_COUNT; skipped:=skipped+added;
     END IF;
     CONTINUE;
   END IF;
   epoch:=0;
   IF to_regclass('public.conversation_handoff_controls') IS NOT NULL THEN
     EXECUTE 'SELECT coalesce((to_jsonb(h)->>''automation_epoch'')::bigint,0) FROM public.conversation_handoff_controls h WHERE conversation_id=$1'
       INTO epoch USING b.conversation_id;
   END IF;
   INSERT INTO public.automation_events(company_id,chatbot_id,event_type,status,idempotency_key,payload)
     VALUES(b.company_id,b.chatbot_id,'tuition_reminder','queued','tuition_reminder:'||b.id::text||':'||b.version::text,
       jsonb_build_object('booking_id',b.id,'booking_version',b.version,'conversation_id',b.conversation_id,'automation_epoch',coalesce(epoch,0)))
     ON CONFLICT(company_id,idempotency_key) DO NOTHING;
   GET DIAGNOSTICS added=ROW_COUNT; n:=n+added;
 END LOOP;
 RETURN jsonb_build_object('enqueued',n,'skipped_overdue',skipped);
END $$;

CREATE OR REPLACE FUNCTION public.tuition_apply_reminder(p_event_id bigint,p_lease_token uuid,p_operation text,p_output jsonb DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE e public.automation_events; b public.tuition_bookings; c public.conversations; s public.tuition_sessions;
 class_name text; reason text; epoch bigint:=0; mid bigint; response jsonb;
BEGIN
 IF p_operation IS NULL OR p_operation NOT IN ('inspect','begin','finish','uncertain','skip') THEN
   RAISE EXCEPTION 'invalid_reminder_operation' USING ERRCODE='22023'; END IF;
 SELECT * INTO e FROM public.automation_events WHERE id=p_event_id FOR UPDATE;
 IF NOT FOUND OR e.event_type<>'tuition_reminder' OR e.worker_kind<>'tuition_reminder'
   OR p_lease_token IS NULL OR e.lease_token IS DISTINCT FROM p_lease_token THEN
   RAISE EXCEPTION 'reminder_lease_lost' USING ERRCODE='40001'; END IF;
 IF e.status IN ('completed','needs_review','failed') THEN RETURN jsonb_build_object('status',e.status,'result',e.result); END IF;
 IF e.status<>'running' OR e.lease_expires_at IS NULL OR e.lease_expires_at<=clock_timestamp() THEN
   RAISE EXCEPTION 'reminder_lease_lost' USING ERRCODE='40001'; END IF;
 SELECT * INTO b FROM public.tuition_bookings WHERE id=(e.payload->>'booking_id')::uuid
   AND company_id=e.company_id AND chatbot_id=e.chatbot_id;
 IF NOT FOUND OR b.conversation_id IS DISTINCT FROM (e.payload->>'conversation_id')::bigint THEN
   RAISE EXCEPTION 'reminder_scope_denied' USING ERRCODE='42501'; END IF;

 -- Terminal acknowledgement records what the provider already accepted, even if
 -- a booking was changed afterwards; never mutate the newer booking's state.
 IF p_operation IN ('finish','uncertain') THEN
   IF NOT e.external_effect_started THEN RAISE EXCEPTION 'reminder_not_started' USING ERRCODE='22023'; END IF;
   IF p_operation='finish' THEN
     IF jsonb_typeof(p_output) IS DISTINCT FROM 'object' OR jsonb_typeof(p_output->'provider_message_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_output->'text') IS DISTINCT FROM 'string' OR (p_output->>'provider_message_id') !~ '^[0-9]{1,20}$'
       OR coalesce(length(p_output->>'text'),0) NOT BETWEEN 1 AND 1000
       OR (p_output-'provider_message_id'-'text')<>'{}'::jsonb THEN
       RAISE EXCEPTION 'invalid_reminder_receipt' USING ERRCODE='22023'; END IF;
     INSERT INTO public.messages(conversation_id,sender_type,message_type,message_text,platform_message_id,delivery_status,ai_generated)
       VALUES(b.conversation_id,'bot','text',p_output->>'text',p_output->>'provider_message_id','sent',false) RETURNING id INTO mid;
     PERFORM public.analysis_record_business_event(e.company_id,e.chatbot_id,b.conversation_id,NULL,
       'trial_reminder:'||e.id::text,'trial_reminder','completed','business_service','reminder:'||e.id::text,ARRAY[mid],
       jsonb_build_object('booking_id',b.id,'booking_version',e.payload->'booking_version','delivery_status','accepted'));
     response:=jsonb_build_object('delivery_status','accepted','message_id',mid,'provider_message_id',p_output->>'provider_message_id');
     UPDATE public.automation_events SET status='completed',result=response,external_effect_started=false,
       lease_expires_at=NULL,updated_at=clock_timestamp() WHERE id=e.id;
     UPDATE public.tuition_bookings SET reminder_status='sent',reminder_unavailable_reason=NULL,updated_at=clock_timestamp()
       WHERE id=b.id AND version=(e.payload->>'booking_version')::integer AND reminder_status='pending';
     RETURN jsonb_build_object('status','completed','result',response);
   END IF;
   UPDATE public.automation_events SET status='needs_review',error_message='provider_result_uncertain',lease_expires_at=NULL,updated_at=clock_timestamp() WHERE id=e.id;
   UPDATE public.tuition_bookings SET reminder_status='needs_review',reminder_unavailable_reason='provider_result_uncertain',updated_at=clock_timestamp()
     WHERE id=b.id AND version=(e.payload->>'booking_version')::integer AND reminder_status='pending';
   RETURN jsonb_build_object('status','needs_review');
 END IF;
 IF e.external_effect_started THEN RETURN jsonb_build_object('status','needs_review','reason','provider_result_uncertain'); END IF;

 -- The Flask sender also holds the existing conversation_delivery_lock. RPC
 -- lock order agrees with booking writes: conversation, then booking, session.
 BEGIN
   c:=public.tuition_require_conversation(e.company_id,e.chatbot_id,b.conversation_id,NULL);
 EXCEPTION WHEN insufficient_privilege OR object_not_in_prerequisite_state THEN
   reason:='conversation_unavailable';
 END;
 SELECT * INTO b FROM public.tuition_bookings WHERE id=b.id FOR UPDATE;
 SELECT * INTO s FROM public.tuition_sessions WHERE id=b.session_id AND company_id=e.company_id AND chatbot_id=e.chatbot_id FOR UPDATE;
 IF reason IS NULL AND (b.version IS DISTINCT FROM (e.payload->>'booking_version')::integer OR b.status<>'confirmed'
   OR NOT b.reminder_enabled OR NOT b.reminder_consent OR b.reminder_status<>'pending') THEN reason:='booking_changed'; END IF;
 IF reason IS NULL AND (s.id IS NULL OR NOT s.enabled OR s.starts_at<=clock_timestamp() OR b.reminder_at IS NULL
   OR b.reminder_at>clock_timestamp() OR b.reminder_at<clock_timestamp()-interval '5 minutes') THEN reason:='reminder_not_due'; END IF;
 IF reason IS NULL AND (c.source_channel IS DISTINCT FROM 'telegram' OR b.contact_key IS DISTINCT FROM public.tuition_contact_key(c)
   OR coalesce(c.platform_user_id,'') !~ '^-?[0-9]{1,20}$') THEN reason:='channel_unsupported'; END IF;
 IF reason IS NULL AND NOT EXISTS(SELECT 1 FROM public.telegram_channels t WHERE t.id=c.source_channel_id
   AND t.company_id=e.company_id AND t.chatbot_id=e.chatbot_id AND t.is_active AND t.connection_status='connected'
   AND t.verified_at IS NOT NULL AND t.telegram_bot_id::text=c.source_provider_id) THEN reason:='channel_unavailable'; END IF;
 IF reason IS NULL AND to_regclass('public.conversation_handoff_controls') IS NOT NULL THEN
   EXECUTE 'SELECT coalesce((to_jsonb(h)->>''automation_epoch'')::bigint,0) FROM public.conversation_handoff_controls h WHERE conversation_id=$1'
     INTO epoch USING b.conversation_id;
   IF coalesce(epoch,0) IS DISTINCT FROM (e.payload->>'automation_epoch')::bigint THEN reason:='handoff_changed'; END IF;
 END IF;
 IF p_operation='skip' THEN reason:='delivery_not_permitted'; END IF;
 IF reason IS NOT NULL THEN
   response:=jsonb_build_object('delivery_status','skipped','reason',reason);
   UPDATE public.automation_events SET status='completed',result=response,lease_expires_at=NULL,updated_at=clock_timestamp() WHERE id=e.id;
   UPDATE public.tuition_bookings SET reminder_status='skipped',reminder_unavailable_reason=reason,updated_at=clock_timestamp()
     WHERE id=b.id AND version=(e.payload->>'booking_version')::integer AND reminder_status='pending';
   RETURN jsonb_build_object('status','completed','result',response);
 END IF;
 SELECT name INTO class_name FROM public.tuition_classes WHERE id=s.class_id AND company_id=e.company_id AND chatbot_id=e.chatbot_id AND enabled;
 IF class_name IS NULL THEN RAISE EXCEPTION 'reminder_class_unavailable' USING ERRCODE='42501'; END IF;
 IF p_operation='begin' THEN
   UPDATE public.automation_events SET external_effect_started=true,updated_at=clock_timestamp() WHERE id=e.id;
 END IF;
 RETURN jsonb_build_object('status','ready','started',p_operation='begin','company_id',e.company_id,'chatbot_id',e.chatbot_id,
   'booking_id',b.id,'booking_version',b.version,'class_name',class_name,'starts_at',s.starts_at,
   'conversation',jsonb_build_object('id',c.id,'chatbot_id',c.chatbot_id,'source_channel',c.source_channel,
     'source_channel_id',c.source_channel_id,'source_provider_id',c.source_provider_id,'platform_user_id',c.platform_user_id));
END $$;
REVOKE ALL ON FUNCTION public.tuition_enqueue_reminders(integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.tuition_apply_reminder(bigint,uuid,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.tuition_enqueue_reminders(integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.tuition_apply_reminder(bigint,uuid,text,jsonb) TO service_role;
COMMIT;
