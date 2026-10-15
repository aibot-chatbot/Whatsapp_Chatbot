-- Roll back migration 078: restore activate_verified_channel without the
-- whatchimp branch, then drop the WhatChimp tables. Connected WhatChimp
-- channels and their API keys are deleted; conversations and messages that
-- came through them stay (source_channel = 'whatchimp' rows remain readable).
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE OR REPLACE FUNCTION public.activate_verified_channel(p_provider text, p_channel_id bigint, p_chatbot_id bigint, p_company_id bigint, p_channel_limit integer, p_expected_attempt_at timestamp with time zone DEFAULT NULL::timestamp with time zone)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
DECLARE
  v_table text; v_identity text; v_candidate jsonb; v_result jsonb; v_newer boolean;
  v_replacing boolean; v_used bigint;
BEGIN
  v_table := CASE p_provider WHEN 'telegram' THEN 'telegram_channels'
    WHEN 'whatsapp' THEN 'whatsapp_channels' WHEN 'wasender' THEN 'wasender_channels' END;
  v_identity := CASE p_provider WHEN 'telegram' THEN 'telegram_bot_id'
    WHEN 'whatsapp' THEN 'phone_number_id' WHEN 'wasender' THEN 'provider_user_id' END;
  IF v_table IS NULL OR p_channel_limit < 0 THEN
    RAISE EXCEPTION 'Invalid activation parameters' USING ERRCODE = '22023';
  END IF;
  PERFORM 1 FROM public.companies WHERE id = p_company_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Company not found' USING ERRCODE = '42501'; END IF;
  PERFORM 1 FROM public.chatbots WHERE id = p_chatbot_id AND company_id = p_company_id
    AND deleted_at IS NULL AND status <> 'archived' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Chatbot ownership does not match' USING ERRCODE = '42501'; END IF;

  EXECUTE format('SELECT to_jsonb(c) FROM public.%I c WHERE id=$1 AND chatbot_id=$2 AND company_id=$3 AND is_active=true AND connection_status=''pending'' FOR UPDATE', v_table)
    INTO v_candidate USING p_channel_id, p_chatbot_id, p_company_id;
  IF v_candidate IS NULL THEN RETURN NULL; END IF;
  IF NULLIF(v_candidate->>v_identity, '') IS NULL
     OR v_candidate->>'verified_at' IS NULL OR v_candidate->>'connection_attempted_at' IS NULL
     OR (v_candidate->>'verified_at')::timestamptz < (v_candidate->>'connection_attempted_at')::timestamptz
     OR (p_expected_attempt_at IS NOT NULL AND (v_candidate->>'connection_attempted_at')::timestamptz <> p_expected_attempt_at) THEN
    RETURN NULL;
  END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I c WHERE chatbot_id=$1 AND company_id=$2 AND id<>$3 AND is_active=true AND connection_status=''connected'' AND (COALESCE(connection_attempted_at,created_at),id) > ($4,$3))', v_table)
    INTO v_newer USING p_chatbot_id,p_company_id,p_channel_id,(v_candidate->>'connection_attempted_at')::timestamptz;
  IF v_newer THEN
    EXECUTE format('UPDATE public.%I SET is_active=false,connection_status=''failed'',last_error=''A newer connection replaced this attempt.'' WHERE id=$1',v_table) USING p_channel_id;
    RETURN NULL;
  END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I WHERE chatbot_id=$1 AND company_id=$2 AND id<>$3 AND is_active=true AND connection_status=''connected'')',v_table)
    INTO v_replacing USING p_chatbot_id,p_company_id,p_channel_id;
  IF p_provider='telegram' AND COALESCE((v_candidate->>'connection_slot_reserved')::boolean,false) THEN
    v_replacing := true;
  END IF;
  SELECT count(*) INTO v_used FROM (
    SELECT c.chatbot_id FROM public.telegram_channels c WHERE company_id=p_company_id AND is_active=true
      AND (connection_status='connected' OR (connection_status='pending' AND connection_slot_reserved=true))
    UNION ALL SELECT c.chatbot_id FROM public.whatsapp_channels c WHERE company_id=p_company_id AND is_active=true AND connection_status='connected'
    UNION ALL SELECT c.chatbot_id FROM public.wasender_channels c WHERE company_id=p_company_id AND is_active=true AND connection_status='connected'
  ) channels JOIN public.chatbots b ON b.id=channels.chatbot_id
    WHERE b.company_id=p_company_id AND b.deleted_at IS NULL AND b.status <> 'archived';
  IF p_channel_limit IS NOT NULL AND NOT v_replacing AND v_used >= p_channel_limit THEN
    RAISE EXCEPTION 'channel_limit_reached' USING ERRCODE='P0001';
  END IF;
  EXECUTE format('UPDATE public.%I SET is_active=false,connection_status=''disconnected'',last_error=NULL WHERE chatbot_id=$1 AND company_id=$2 AND id<>$3 AND is_active=true AND connection_status<>''pending''',v_table)
    USING p_chatbot_id,p_company_id,p_channel_id;
  EXECUTE format('UPDATE public.%I c SET is_active=true,connection_status=''connected'',last_error=NULL WHERE id=$1 RETURNING to_jsonb(c)',v_table)
    INTO v_result USING p_channel_id;
  RETURN v_result;
END;
$function$;
REVOKE ALL ON FUNCTION public.activate_verified_channel(text,bigint,bigint,bigint,integer,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.activate_verified_channel(text,bigint,bigint,bigint,integer,timestamptz) TO service_role;


DROP TABLE IF EXISTS public.processed_whatchimp_messages;
DROP TABLE IF EXISTS public.whatchimp_channels;

COMMIT;
