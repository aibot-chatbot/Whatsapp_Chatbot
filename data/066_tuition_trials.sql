-- Tuition trials only. Business effects require service-issued confirmation.
-- Apply after 063/064. Feature remains off in the application by default.
BEGIN;
SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.tuition_courses (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
 chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 150), enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tuition_courses_scope ON public.tuition_courses(company_id,chatbot_id,id);
CREATE TABLE public.tuition_classes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
 chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
 course_id uuid NOT NULL REFERENCES public.tuition_courses(id) ON DELETE CASCADE,
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 150), enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tuition_classes_scope ON public.tuition_classes(company_id,chatbot_id,course_id,id);
CREATE TABLE public.tuition_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
 chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
 class_id uuid NOT NULL REFERENCES public.tuition_classes(id) ON DELETE CASCADE,
 starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL CHECK(ends_at>starts_at),
 total_capacity integer NOT NULL CHECK(total_capacity BETWEEN 1 AND 10000),
 enrolled_seats integer NOT NULL DEFAULT 0 CHECK(enrolled_seats>=0),
 trial_limit integer NOT NULL CHECK(trial_limit>=0), enabled boolean NOT NULL DEFAULT true,
 version integer NOT NULL DEFAULT 1 CHECK(version>0), created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(enrolled_seats<=total_capacity AND trial_limit<=total_capacity)
);
CREATE INDEX tuition_sessions_scope_time ON public.tuition_sessions(company_id,chatbot_id,starts_at,id);
CREATE TABLE public.tuition_participants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
 chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
 conversation_id bigint NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
 client_key text NOT NULL CHECK(length(client_key) BETWEEN 1 AND 100),
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 80),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(company_id,chatbot_id,conversation_id,client_key)
);
CREATE TABLE public.tuition_bookings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
 chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
 conversation_id bigint NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
 participant_id uuid NOT NULL REFERENCES public.tuition_participants(id) ON DELETE RESTRICT,
 session_id uuid NOT NULL REFERENCES public.tuition_sessions(id) ON DELETE RESTRICT,
 confirmation_id uuid NOT NULL UNIQUE,
 contact_key text NOT NULL, status text NOT NULL DEFAULT 'confirmed' CHECK(status IN ('confirmed','cancelled','completed')),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 reminder_consent boolean NOT NULL DEFAULT false, reminder_enabled boolean NOT NULL DEFAULT false,
 reminder_unavailable_reason text, reminder_at timestamptz,
 reminder_status text NOT NULL DEFAULT 'not_requested' CHECK(reminder_status IN ('not_requested','unsupported','pending','sent','failed','cancelled')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX tuition_one_active_trial ON public.tuition_bookings(participant_id,session_id) WHERE status='confirmed';
CREATE INDEX tuition_booking_session_status ON public.tuition_bookings(session_id,status);
CREATE INDEX tuition_booking_scope ON public.tuition_bookings(company_id,chatbot_id,conversation_id,created_at,id);
CREATE TABLE public.tuition_confirmations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), token_hash text NOT NULL UNIQUE,
 company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
 chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
 conversation_id bigint NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
 participant_id uuid NOT NULL REFERENCES public.tuition_participants(id) ON DELETE CASCADE,
 participant_version integer NOT NULL,
 session_id uuid NOT NULL REFERENCES public.tuition_sessions(id) ON DELETE CASCADE,
 session_version integer NOT NULL, contact_key text NOT NULL,
 operation text NOT NULL CHECK(operation IN ('reserve','reschedule')),
 booking_id uuid REFERENCES public.tuition_bookings(id) ON DELETE CASCADE,
 booking_version integer, reminder_consent boolean NOT NULL DEFAULT false,
 evidence_message_id bigint REFERENCES public.messages(id) ON DELETE SET NULL,
 expires_at timestamptz NOT NULL, consumed_at timestamptz, result_booking_id uuid REFERENCES public.tuition_bookings(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tuition_confirmation_scope ON public.tuition_confirmations(company_id,chatbot_id,conversation_id,expires_at);

-- All writes go through validated RPCs. No customer can invoke them directly.
ALTER TABLE public.tuition_courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tuition_classes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tuition_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tuition_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tuition_bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tuition_confirmations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tuition_courses,public.tuition_classes,public.tuition_sessions,public.tuition_participants,
 public.tuition_bookings,public.tuition_confirmations FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.tuition_courses,public.tuition_classes,public.tuition_sessions,public.tuition_participants,
 public.tuition_bookings TO service_role;

CREATE FUNCTION public.tuition_require_bot(p_company_id bigint,p_chatbot_id bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.chatbots WHERE id=p_chatbot_id AND company_id=p_company_id
   AND deleted_at IS NULL AND status IS DISTINCT FROM 'archived'
   AND industry_template_published->>'template_id'='tuition_center'
   AND industry_template_published->>'confirmed_at' IS NOT NULL) THEN
   RAISE EXCEPTION 'tuition_scope_or_industry_denied' USING ERRCODE='42501';
 END IF;
END $$;

CREATE FUNCTION public.tuition_require_conversation(p_company_id bigint,p_chatbot_id bigint,p_conversation_id bigint,p_actor_user_id bigint)
RETURNS public.conversations LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c public.conversations; h record; paused boolean;
BEGIN
 PERFORM public.tuition_require_bot(p_company_id,p_chatbot_id);
 SELECT * INTO c FROM public.conversations WHERE id=p_conversation_id AND chatbot_id=p_chatbot_id FOR UPDATE;
 IF NOT FOUND OR c.conversation_status IS DISTINCT FROM 'open' THEN
   RAISE EXCEPTION 'tuition_conversation_denied' USING ERRCODE='42501'; END IF;
 IF p_actor_user_id IS NOT NULL THEN
   PERFORM public.analysis_require_actor(p_company_id,p_chatbot_id,p_actor_user_id);
 END IF;
 IF to_regclass('public.conversation_handoff_controls') IS NOT NULL THEN
   EXECUTE 'SELECT company_id,chatbot_id,handling_mode FROM public.conversation_handoff_controls WHERE conversation_id=$1 FOR UPDATE'
     INTO h USING p_conversation_id;
   IF h.handling_mode IS NOT NULL AND (h.company_id IS DISTINCT FROM p_company_id OR h.chatbot_id IS DISTINCT FROM p_chatbot_id
       OR h.handling_mode IS DISTINCT FROM 'ai_active') THEN
     RAISE EXCEPTION 'tuition_human_controlled' USING ERRCODE='55000'; END IF;
 END IF;
 -- Legacy handoff stays authoritative until the control flag is enabled.
 IF to_regclass('public.agent_actions') IS NULL THEN
   RAISE EXCEPTION 'tuition_handoff_unavailable' USING ERRCODE='55000';
 ELSE
   EXECUTE 'SELECT EXISTS(SELECT 1 FROM public.agent_actions WHERE conversation_id=$1 AND chatbot_id=$2
       AND status=''detected'' AND intent IN (''handoff_request'',''complaint'',''knowledge_gap''))'
     INTO paused USING p_conversation_id,p_chatbot_id;
   IF paused THEN RAISE EXCEPTION 'tuition_human_controlled' USING ERRCODE='55000'; END IF;
 END IF;
 RETURN c;
END $$;

CREATE FUNCTION public.tuition_contact_key(c public.conversations) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path='' AS $$
 SELECT encode(sha256(convert_to(jsonb_build_array(c.id,c.chatbot_id,c.source_channel,c.source_channel_id,
   c.source_provider_id,c.platform_user_id,c.customer_phone)::text,'UTF8')),'hex');
$$;

CREATE FUNCTION public.tuition_catalog_write(p_company_id bigint,p_chatbot_id bigint,p_actor_user_id bigint,p_operation text,p_data jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE course public.tuition_courses; class public.tuition_classes; session public.tuition_sessions; occupied integer;
BEGIN
 PERFORM public.analysis_require_actor(p_company_id,p_chatbot_id,p_actor_user_id);
 PERFORM public.tuition_require_bot(p_company_id,p_chatbot_id);
 IF p_operation='course' THEN
   INSERT INTO public.tuition_courses(company_id,chatbot_id,name) VALUES(p_company_id,p_chatbot_id,p_data->>'name') RETURNING * INTO course;
   RETURN to_jsonb(course);
 ELSIF p_operation='class' THEN
   IF NOT EXISTS(SELECT 1 FROM public.tuition_courses WHERE id=(p_data->>'course_id')::uuid AND company_id=p_company_id AND chatbot_id=p_chatbot_id AND enabled) THEN
     RAISE EXCEPTION 'tuition_course_denied' USING ERRCODE='42501'; END IF;
   INSERT INTO public.tuition_classes(company_id,chatbot_id,course_id,name)
     VALUES(p_company_id,p_chatbot_id,(p_data->>'course_id')::uuid,p_data->>'name') RETURNING * INTO class;
   RETURN to_jsonb(class);
 ELSIF p_operation='session' THEN
   IF NOT EXISTS(SELECT 1 FROM public.tuition_classes WHERE id=(p_data->>'class_id')::uuid AND company_id=p_company_id AND chatbot_id=p_chatbot_id AND enabled) THEN
     RAISE EXCEPTION 'tuition_class_denied' USING ERRCODE='42501'; END IF;
   IF (p_data->>'starts_at')::timestamptz<=clock_timestamp() THEN
     RAISE EXCEPTION 'tuition_session_in_past' USING ERRCODE='22023'; END IF;
   INSERT INTO public.tuition_sessions(company_id,chatbot_id,class_id,starts_at,ends_at,total_capacity,enrolled_seats,trial_limit)
     VALUES(p_company_id,p_chatbot_id,(p_data->>'class_id')::uuid,(p_data->>'starts_at')::timestamptz,
       (p_data->>'ends_at')::timestamptz,(p_data->>'total_capacity')::integer,
       (p_data->>'enrolled_seats')::integer,(p_data->>'trial_limit')::integer) RETURNING * INTO session;
   RETURN to_jsonb(session);
 ELSIF p_operation='capacity' THEN
   SELECT * INTO session FROM public.tuition_sessions WHERE id=(p_data->>'session_id')::uuid
     AND company_id=p_company_id AND chatbot_id=p_chatbot_id FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'tuition_session_denied' USING ERRCODE='42501'; END IF;
   IF session.version IS DISTINCT FROM (p_data->>'expected_version')::integer THEN
     RAISE EXCEPTION 'tuition_version_conflict' USING ERRCODE='40001'; END IF;
   SELECT count(*) INTO occupied FROM public.tuition_bookings WHERE session_id=session.id AND status='confirmed';
   IF (p_data->>'total_capacity')::integer-(p_data->>'enrolled_seats')::integer<occupied
     OR (p_data->>'trial_limit')::integer<occupied THEN
     RAISE EXCEPTION 'tuition_capacity_below_reserved' USING ERRCODE='22023'; END IF;
   UPDATE public.tuition_sessions SET total_capacity=(p_data->>'total_capacity')::integer,
     enrolled_seats=(p_data->>'enrolled_seats')::integer,trial_limit=(p_data->>'trial_limit')::integer,
     version=version+1 WHERE id=session.id RETURNING * INTO session;
   RETURN to_jsonb(session);
 ELSE RAISE EXCEPTION 'tuition_invalid_operation' USING ERRCODE='22023'; END IF;
END $$;

CREATE FUNCTION public.tuition_create_participant(p_company_id bigint,p_chatbot_id bigint,p_conversation_id bigint,
 p_actor_user_id bigint,p_client_key text,p_label text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE participant public.tuition_participants;
BEGIN
 PERFORM public.tuition_require_conversation(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id);
 INSERT INTO public.tuition_participants(company_id,chatbot_id,conversation_id,client_key,label)
   VALUES(p_company_id,p_chatbot_id,p_conversation_id,p_client_key,p_label)
   ON CONFLICT(company_id,chatbot_id,conversation_id,client_key) DO NOTHING RETURNING * INTO participant;
 IF participant.id IS NULL THEN
   SELECT * INTO participant FROM public.tuition_participants WHERE company_id=p_company_id AND chatbot_id=p_chatbot_id
     AND conversation_id=p_conversation_id AND client_key=p_client_key;
   IF participant.label IS DISTINCT FROM p_label THEN
     RAISE EXCEPTION 'tuition_idempotency_conflict' USING ERRCODE='22023'; END IF;
 END IF;
 RETURN to_jsonb(participant);
END $$;

CREATE FUNCTION public.tuition_prepare_trial(p_company_id bigint,p_chatbot_id bigint,p_conversation_id bigint,
 p_actor_user_id bigint,p_participant_id uuid,p_session_id uuid,p_booking_id uuid DEFAULT NULL,
 p_reminder_consent boolean DEFAULT false,p_evidence_message_id bigint DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c public.conversations; session public.tuition_sessions; booking public.tuition_bookings;
 token text; confirmation public.tuition_confirmations; participant public.tuition_participants;
BEGIN
 c := public.tuition_require_conversation(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id);
 SELECT * INTO participant FROM public.tuition_participants WHERE id=p_participant_id AND company_id=p_company_id
   AND chatbot_id=p_chatbot_id AND conversation_id=p_conversation_id;
 IF NOT FOUND THEN
   RAISE EXCEPTION 'tuition_participant_denied' USING ERRCODE='42501'; END IF;
 IF p_evidence_message_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.messages WHERE id=p_evidence_message_id AND conversation_id=p_conversation_id) THEN
   RAISE EXCEPTION 'tuition_evidence_denied' USING ERRCODE='42501'; END IF;
 SELECT * INTO session FROM public.tuition_sessions WHERE id=p_session_id AND company_id=p_company_id AND chatbot_id=p_chatbot_id;
 IF NOT FOUND OR NOT session.enabled OR session.starts_at<=clock_timestamp() THEN
   RAISE EXCEPTION 'tuition_session_unavailable' USING ERRCODE='22023'; END IF;
 IF p_booking_id IS NOT NULL THEN
   SELECT * INTO booking FROM public.tuition_bookings WHERE id=p_booking_id AND company_id=p_company_id
     AND chatbot_id=p_chatbot_id AND conversation_id=p_conversation_id AND participant_id=p_participant_id;
   IF NOT FOUND OR booking.status<>'confirmed' OR booking.session_id=session.id
     OR booking.contact_key IS DISTINCT FROM public.tuition_contact_key(c) THEN
     RAISE EXCEPTION 'tuition_booking_unavailable' USING ERRCODE='22023'; END IF;
 END IF;
 token := gen_random_uuid()::text||gen_random_uuid()::text;
 INSERT INTO public.tuition_confirmations(token_hash,company_id,chatbot_id,conversation_id,participant_id,participant_version,session_id,
   session_version,contact_key,operation,booking_id,booking_version,reminder_consent,evidence_message_id,expires_at)
   VALUES(encode(sha256(convert_to(token,'UTF8')),'hex'),p_company_id,p_chatbot_id,p_conversation_id,p_participant_id,participant.version,
     p_session_id,session.version,public.tuition_contact_key(c),CASE WHEN p_booking_id IS NULL THEN 'reserve' ELSE 'reschedule' END,
     p_booking_id,booking.version,p_reminder_consent,p_evidence_message_id,clock_timestamp()+interval '10 minutes') RETURNING * INTO confirmation;
 RETURN jsonb_build_object('confirmation_token',token,'expires_at',confirmation.expires_at,
   'operation',confirmation.operation,'session',to_jsonb(session),'participant_id',p_participant_id,
   'participant',jsonb_build_object('id',participant.id,'label',participant.label,'version',participant.version),
   'reminder_consent',p_reminder_consent,'reserved',false,
   'reminder_supported',coalesce(c.source_channel='telegram' AND c.source_channel_id>0
       AND nullif(c.source_provider_id,'') IS NOT NULL AND coalesce(nullif(c.platform_user_id,''),nullif(c.customer_phone,'')) IS NOT NULL
       AND session.starts_at>clock_timestamp()+interval '24 hours',false));
END $$;

CREATE FUNCTION public.tuition_update_participant(p_company_id bigint,p_chatbot_id bigint,p_conversation_id bigint,
 p_actor_user_id bigint,p_participant_id uuid,p_expected_version integer,p_label text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE participant public.tuition_participants;
BEGIN
 PERFORM public.analysis_require_actor(p_company_id,p_chatbot_id,p_actor_user_id);
 PERFORM public.tuition_require_conversation(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id);
 UPDATE public.tuition_participants SET label=p_label,version=version+1 WHERE id=p_participant_id
   AND company_id=p_company_id AND chatbot_id=p_chatbot_id AND conversation_id=p_conversation_id
   AND version=p_expected_version RETURNING * INTO participant;
 IF NOT FOUND THEN RAISE EXCEPTION 'tuition_participant_changed' USING ERRCODE='40001'; END IF;
 RETURN to_jsonb(participant);
END $$;

CREATE FUNCTION public.tuition_list_sessions(p_company_id bigint,p_chatbot_id bigint,p_class_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 PERFORM public.tuition_require_bot(p_company_id,p_chatbot_id);
 RETURN jsonb_build_object('sessions',coalesce((SELECT jsonb_agg(to_jsonb(row)) FROM (
   SELECT s.*,cl.name AS class_name,co.name AS course_name,
     greatest(0,least(s.total_capacity-s.enrolled_seats,s.trial_limit)-
       (SELECT count(*) FROM public.tuition_bookings b WHERE b.session_id=s.id AND b.status='confirmed')) AS available_trial_seats
   FROM public.tuition_sessions s JOIN public.tuition_classes cl ON cl.id=s.class_id
   JOIN public.tuition_courses co ON co.id=cl.course_id
   WHERE s.company_id=p_company_id AND s.chatbot_id=p_chatbot_id AND s.enabled
     AND cl.enabled AND co.enabled AND s.starts_at>clock_timestamp()
     AND (p_class_id IS NULL OR s.class_id=p_class_id)
   ORDER BY s.starts_at,s.id LIMIT 200
 ) row),'[]'::jsonb));
END $$;

CREATE FUNCTION public.tuition_confirm_trial(p_company_id bigint,p_chatbot_id bigint,p_conversation_id bigint,
 p_actor_user_id bigint,p_confirmation_token text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c public.conversations; conf public.tuition_confirmations; target public.tuition_sessions; booking public.tuition_bookings;
 occupied integer; reminder boolean; reason text; evidence bigint[];
BEGIN
 c := public.tuition_require_conversation(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id);
 SELECT * INTO conf FROM public.tuition_confirmations WHERE token_hash=encode(sha256(convert_to(p_confirmation_token,'UTF8')),'hex')
   AND company_id=p_company_id AND chatbot_id=p_chatbot_id AND conversation_id=p_conversation_id FOR UPDATE;
 IF NOT FOUND OR conf.contact_key IS DISTINCT FROM public.tuition_contact_key(c) THEN
   RAISE EXCEPTION 'tuition_confirmation_denied' USING ERRCODE='42501'; END IF;
 IF conf.consumed_at IS NOT NULL THEN
   SELECT * INTO booking FROM public.tuition_bookings WHERE id=conf.result_booking_id;
   SELECT * INTO target FROM public.tuition_sessions WHERE id=booking.session_id;
   RETURN jsonb_build_object('booking',to_jsonb(booking),'session',to_jsonb(target));
 END IF;
 IF conf.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'tuition_confirmation_expired' USING ERRCODE='22023'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.tuition_participants WHERE id=conf.participant_id AND version=conf.participant_version) THEN
   RAISE EXCEPTION 'tuition_participant_changed' USING ERRCODE='40001'; END IF;
 IF conf.operation='reschedule' THEN
   SELECT * INTO booking FROM public.tuition_bookings WHERE id=conf.booking_id FOR UPDATE;
   IF booking.status<>'confirmed' OR booking.version IS DISTINCT FROM conf.booking_version THEN
     RAISE EXCEPTION 'tuition_booking_changed' USING ERRCODE='40001'; END IF;
 END IF;
 -- Stable UUID order prevents deadlocks when two bookings swap sessions.
 PERFORM 1 FROM public.tuition_sessions WHERE id IN(conf.session_id,booking.session_id) ORDER BY id FOR UPDATE;
 SELECT * INTO target FROM public.tuition_sessions WHERE id=conf.session_id;
 IF target.version IS DISTINCT FROM conf.session_version OR NOT target.enabled OR target.starts_at<=clock_timestamp() THEN
   RAISE EXCEPTION 'tuition_session_changed' USING ERRCODE='40001'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.tuition_classes cl JOIN public.tuition_courses co ON co.id=cl.course_id
   WHERE cl.id=target.class_id AND cl.enabled AND co.enabled AND cl.company_id=p_company_id AND cl.chatbot_id=p_chatbot_id
   AND co.company_id=p_company_id AND co.chatbot_id=p_chatbot_id) THEN
   RAISE EXCEPTION 'tuition_session_unavailable' USING ERRCODE='22023'; END IF;
 SELECT count(*) INTO occupied FROM public.tuition_bookings WHERE session_id=target.id AND status='confirmed';
 IF occupied>=target.trial_limit OR occupied+target.enrolled_seats>=target.total_capacity THEN
   RAISE EXCEPTION 'tuition_session_full' USING ERRCODE='23514'; END IF;
 reminder := coalesce(conf.reminder_consent AND c.source_channel='telegram'
   AND c.source_channel_id>0 AND nullif(c.source_provider_id,'') IS NOT NULL
   AND coalesce(nullif(c.platform_user_id,''),nullif(c.customer_phone,'')) IS NOT NULL
   AND target.starts_at>clock_timestamp()+interval '24 hours',false);
 reason := CASE WHEN NOT conf.reminder_consent THEN 'not_requested'
   WHEN c.source_channel IS DISTINCT FROM 'telegram' THEN 'channel_unsupported'
   WHEN target.starts_at<=clock_timestamp()+interval '24 hours' THEN 'less_than_24h'
   WHEN NOT reminder THEN 'channel_identity_unavailable' ELSE NULL END;
 IF conf.operation='reserve' THEN
   INSERT INTO public.tuition_bookings(company_id,chatbot_id,conversation_id,participant_id,session_id,confirmation_id,
     contact_key,reminder_consent,reminder_enabled,reminder_unavailable_reason,reminder_at,reminder_status)
   VALUES(p_company_id,p_chatbot_id,p_conversation_id,conf.participant_id,target.id,conf.id,conf.contact_key,
     conf.reminder_consent,reminder,reason,CASE WHEN reminder THEN target.starts_at-interval '24 hours' ELSE NULL END,
     CASE WHEN reminder THEN 'pending' WHEN conf.reminder_consent THEN 'unsupported' ELSE 'not_requested' END) RETURNING * INTO booking;
 ELSE
   UPDATE public.tuition_bookings SET session_id=target.id,version=version+1,updated_at=now(),
     reminder_consent=conf.reminder_consent,reminder_enabled=reminder,reminder_unavailable_reason=reason,
     reminder_at=CASE WHEN reminder THEN target.starts_at-interval '24 hours' ELSE NULL END,
     reminder_status=CASE WHEN reminder THEN 'pending' WHEN conf.reminder_consent THEN 'unsupported' ELSE 'not_requested' END
     WHERE id=booking.id RETURNING * INTO booking;
 END IF;
 evidence := CASE WHEN conf.evidence_message_id IS NULL THEN '{}'::bigint[] ELSE ARRAY[conf.evidence_message_id] END;
 IF conf.operation='reschedule' THEN
   PERFORM public.analysis_record_business_event(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id,
     'trial:'||conf.id::text||':rescheduled','booking','rescheduled','business_service',booking.id::text,evidence,
     jsonb_build_object('booking_type','trial','session_id',target.id));
 END IF;
 PERFORM public.analysis_record_business_event(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id,
   'trial:'||conf.id::text||':confirmed','booking','confirmed','business_service',booking.id::text,evidence,
   jsonb_build_object('booking_type','trial','session_id',target.id));
 UPDATE public.tuition_confirmations SET consumed_at=now(),result_booking_id=booking.id WHERE id=conf.id;
 RETURN jsonb_build_object('booking',to_jsonb(booking),'session',to_jsonb(target));
END $$;

CREATE FUNCTION public.tuition_cancel_trial(p_company_id bigint,p_chatbot_id bigint,p_conversation_id bigint,
 p_actor_user_id bigint,p_booking_id uuid,p_client_message_id text,p_expected_version integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE booking public.tuition_bookings; c public.conversations;
BEGIN
 c := public.tuition_require_conversation(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id);
 IF length(p_client_message_id) NOT BETWEEN 1 AND 100 OR p_client_message_id IS NULL THEN
   RAISE EXCEPTION 'tuition_invalid_request_key' USING ERRCODE='22023'; END IF;
 SELECT * INTO booking FROM public.tuition_bookings WHERE id=p_booking_id AND company_id=p_company_id
   AND chatbot_id=p_chatbot_id AND conversation_id=p_conversation_id FOR UPDATE;
 IF NOT FOUND OR booking.contact_key IS DISTINCT FROM public.tuition_contact_key(c) THEN
   RAISE EXCEPTION 'tuition_booking_denied' USING ERRCODE='42501'; END IF;
 IF booking.status='cancelled' THEN RETURN to_jsonb(booking); END IF;
 IF booking.version IS DISTINCT FROM p_expected_version THEN
   RAISE EXCEPTION 'tuition_booking_changed' USING ERRCODE='40001'; END IF;
 IF booking.status<>'confirmed' THEN RAISE EXCEPTION 'tuition_booking_changed' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM public.tuition_sessions WHERE id=booking.session_id FOR UPDATE;
 UPDATE public.tuition_bookings SET status='cancelled',version=version+1,reminder_enabled=false,
   reminder_status='cancelled',updated_at=now() WHERE id=booking.id RETURNING * INTO booking;
 PERFORM public.analysis_record_business_event(p_company_id,p_chatbot_id,p_conversation_id,p_actor_user_id,
   'trial:'||booking.id::text||':cancel:'||p_client_message_id,'booking','cancelled','business_service',booking.id::text,
   '{}'::bigint[],jsonb_build_object('booking_type','trial','session_id',booking.session_id));
 RETURN to_jsonb(booking);
END $$;

REVOKE ALL ON FUNCTION public.tuition_require_bot(bigint,bigint),
 public.tuition_require_conversation(bigint,bigint,bigint,bigint),public.tuition_contact_key(public.conversations)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.tuition_catalog_write(bigint,bigint,bigint,text,jsonb),
 public.tuition_create_participant(bigint,bigint,bigint,bigint,text,text),
 public.tuition_update_participant(bigint,bigint,bigint,bigint,uuid,integer,text),
 public.tuition_list_sessions(bigint,bigint,uuid),
 public.tuition_prepare_trial(bigint,bigint,bigint,bigint,uuid,uuid,uuid,boolean,bigint),
 public.tuition_confirm_trial(bigint,bigint,bigint,bigint,text),
 public.tuition_cancel_trial(bigint,bigint,bigint,bigint,uuid,text,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.tuition_catalog_write(bigint,bigint,bigint,text,jsonb),
 public.tuition_create_participant(bigint,bigint,bigint,bigint,text,text),
 public.tuition_update_participant(bigint,bigint,bigint,bigint,uuid,integer,text),
 public.tuition_list_sessions(bigint,bigint,uuid),
 public.tuition_prepare_trial(bigint,bigint,bigint,bigint,uuid,uuid,uuid,boolean,bigint),
 public.tuition_confirm_trial(bigint,bigint,bigint,bigint,text),
 public.tuition_cancel_trial(bigint,bigint,bigint,bigint,uuid,text,integer) TO service_role;
COMMIT;
