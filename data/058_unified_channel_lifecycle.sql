-- Additive rollout for verified replacement and immutable conversation origins.
-- Existing rows are retained. Conflicting active identities or open bound
-- conversations fail index creation, which aborts the whole transaction.
--
-- GRANDFATHERING. app/services/channel_delivery_service.validate_channel refuses
-- to deliver for a channel with no verified_at, and get_bound_channel refuses a
-- conversation with no source_channel_id. Both columns are created empty here,
-- so without the two backfills below this migration takes every ALREADY
-- CONNECTED tenant offline the moment it is applied: inbound webhooks raise,
-- the routes answer 500, Meta and Telegram back off, and nothing in the product
-- reports it. Rows that were connected before this migration were trusted by the
-- code that connected them, so they stay trusted; only NEW connections go
-- through the verification added here.
--
-- LOCKING. This runs as one transaction over public.conversations, the largest
-- table, so inbound message writes block until it commits. Apply it in a short
-- maintenance window. The CHECK constraint is added NOT VALID for that reason;
-- validate it after COMMIT with the statement at the end of this file.
BEGIN;

ALTER TABLE public.telegram_channels
  ADD COLUMN IF NOT EXISTS connection_attempted_at timestamptz,
  ADD COLUMN IF NOT EXISTS verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS connection_slot_reserved boolean NOT NULL DEFAULT false;
ALTER TABLE public.whatsapp_channels
  ADD COLUMN IF NOT EXISTS connection_attempted_at timestamptz,
  ADD COLUMN IF NOT EXISTS verified_at timestamptz;
ALTER TABLE public.wasender_channels
  ADD COLUMN IF NOT EXISTS connection_attempted_at timestamptz,
  ADD COLUMN IF NOT EXISTS verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS provider_user_id text;

-- Grandfather connections made before verification existed (see header).
-- wasender identity is derived from the configured number, the same fallback
-- the configured-phone index below already uses.
UPDATE public.wasender_channels
  SET provider_user_id = '+' || NULLIF(regexp_replace(phone_number, '[^0-9]', '', 'g'), '')
  WHERE is_active = true AND connection_status = 'connected' AND provider_user_id IS NULL
    AND NULLIF(regexp_replace(phone_number, '[^0-9]', '', 'g'), '') IS NOT NULL;
UPDATE public.telegram_channels SET verified_at = now()
  WHERE is_active = true AND connection_status = 'connected'
    AND verified_at IS NULL AND telegram_bot_id IS NOT NULL;
UPDATE public.whatsapp_channels SET verified_at = now()
  WHERE is_active = true AND connection_status = 'connected'
    AND verified_at IS NULL AND phone_number_id IS NOT NULL;
UPDATE public.wasender_channels SET verified_at = now()
  WHERE is_active = true AND connection_status = 'connected'
    AND verified_at IS NULL AND provider_user_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS telegram_channels_active_provider_identity_uidx
  ON public.telegram_channels(telegram_bot_id) WHERE is_active = true;
-- Retain past records when a released Meta identity is connected again.
-- Drop both forms: this table has no CREATE TABLE in the repo, so whether the
-- live uniqueness is a table constraint or a standalone index is unknown. If
-- only the constraint form is dropped and production used an index, the global
-- unique survives and re-binding a released number still fails with 23505.
ALTER TABLE public.whatsapp_channels DROP CONSTRAINT IF EXISTS whatsapp_channels_phone_number_id_key;
DROP INDEX IF EXISTS public.whatsapp_channels_phone_number_id_key;
-- Only a CONNECTED row reserves a Meta number, matching the wasender predicate
-- below. The row is created pending+active before verification runs, so keying
-- on is_active alone would let any tenant hold another tenant's number for the
-- length of the Graph round-trips - or permanently, if the attempt died.
-- Dropped, not IF NOT EXISTS: this index already exists in production with the
-- older, broader predicate (is_active AND phone_number_id IS NOT NULL). A
-- CREATE ... IF NOT EXISTS would silently skip and leave the wrong predicate in
-- place, so the narrowing above would never take effect.
DROP INDEX IF EXISTS public.whatsapp_channels_phone_number_id_active_unique;
CREATE UNIQUE INDEX whatsapp_channels_phone_number_id_active_unique
  ON public.whatsapp_channels(phone_number_id)
  WHERE is_active = true AND connection_status = 'connected' AND phone_number_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS wasender_channels_active_provider_identity_uidx
  ON public.wasender_channels(provider_user_id) WHERE is_active = true AND provider_user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS wasender_channels_active_session_uidx
  ON public.wasender_channels(session_id) WHERE is_active = true AND NULLIF(session_id, '') IS NOT NULL;
-- Legacy configured numbers reserve their identity even before the provider has
-- confirmed it. This does not assert verification or enable their delivery.
CREATE UNIQUE INDEX IF NOT EXISTS wasender_channels_active_configured_phone_uidx
  ON public.wasender_channels((COALESCE(provider_user_id, '+' || NULLIF(regexp_replace(phone_number, '[^0-9]', '', 'g'), ''))))
  WHERE is_active = true AND (provider_user_id IS NOT NULL OR connection_status = 'connected');

CREATE UNIQUE INDEX IF NOT EXISTS telegram_channels_connected_chatbot_uidx
  ON public.telegram_channels(chatbot_id) WHERE is_active = true AND connection_status = 'connected';
CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_channels_connected_chatbot_uidx
  ON public.whatsapp_channels(chatbot_id) WHERE is_active = true AND connection_status = 'connected';
CREATE UNIQUE INDEX IF NOT EXISTS wasender_channels_connected_chatbot_uidx
  ON public.wasender_channels(chatbot_id) WHERE is_active = true AND connection_status = 'connected';

CREATE OR REPLACE FUNCTION public.guard_channel_identity()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $function$
DECLARE v_old jsonb := to_jsonb(OLD); v_new jsonb := to_jsonb(NEW); v_identity text := TG_ARGV[0];
BEGIN
  IF OLD.company_id IS DISTINCT FROM NEW.company_id OR OLD.chatbot_id IS DISTINCT FROM NEW.chatbot_id
     OR (NULLIF(v_old->>v_identity, '') IS NOT NULL AND v_old->>v_identity IS DISTINCT FROM v_new->>v_identity) THEN
    RAISE EXCEPTION 'Channel ownership and provider identity are immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$function$;
DROP TRIGGER IF EXISTS telegram_channel_identity_guard ON public.telegram_channels;
CREATE TRIGGER telegram_channel_identity_guard BEFORE UPDATE ON public.telegram_channels
  FOR EACH ROW EXECUTE FUNCTION public.guard_channel_identity('telegram_bot_id');
DROP TRIGGER IF EXISTS whatsapp_channel_identity_guard ON public.whatsapp_channels;
CREATE TRIGGER whatsapp_channel_identity_guard BEFORE UPDATE ON public.whatsapp_channels
  FOR EACH ROW EXECUTE FUNCTION public.guard_channel_identity('phone_number_id');
DROP TRIGGER IF EXISTS wasender_channel_identity_guard ON public.wasender_channels;
CREATE TRIGGER wasender_channel_identity_guard BEFORE UPDATE ON public.wasender_channels
  FOR EACH ROW EXECUTE FUNCTION public.guard_channel_identity('provider_user_id');

CREATE OR REPLACE FUNCTION public.activate_verified_channel(
  p_provider text, p_channel_id bigint, p_chatbot_id bigint, p_company_id bigint,
  p_channel_limit integer, p_expected_attempt_at timestamptz DEFAULT NULL
)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $function$
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
  -- All providers and all chatbots share this lock for company-wide quota.
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
  -- In-flight candidates retain provider reservations until their own operation
  -- ends. Old connected/failed rows are released only after this candidate passes.
  EXECUTE format('UPDATE public.%I SET is_active=false,connection_status=''disconnected'',last_error=NULL WHERE chatbot_id=$1 AND company_id=$2 AND id<>$3 AND is_active=true AND connection_status<>''pending''',v_table)
    USING p_chatbot_id,p_company_id,p_channel_id;
  EXECUTE format('UPDATE public.%I c SET is_active=true,connection_status=''connected'',last_error=NULL WHERE id=$1 RETURNING to_jsonb(c)',v_table)
    INTO v_result USING p_channel_id;
  RETURN v_result;
END;
$function$;
REVOKE ALL ON FUNCTION public.activate_verified_channel(text,bigint,bigint,bigint,integer,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.activate_verified_channel(text,bigint,bigint,bigint,integer,timestamptz) TO service_role;

ALTER TABLE public.conversations
  ADD COLUMN IF NOT EXISTS source_channel_id bigint,
  ADD COLUMN IF NOT EXISTS source_provider_id text;
DO $constraint$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.conversations'::regclass AND conname='conversations_origin_pair_check') THEN
    ALTER TABLE public.conversations ADD CONSTRAINT conversations_origin_pair_check
      CHECK ((source_channel_id IS NULL) = (source_provider_id IS NULL)) NOT VALID;
  END IF;
END; $constraint$;
-- Bind existing OPEN conversations to their channel wherever that channel is
-- unambiguous - exactly one active connected channel for the chatbot on that
-- provider. Without this, _scope_origin in conversation_repository never matches
-- a legacy row, so every returning customer silently gets a second empty thread
-- and the AI loses their history. Ambiguous chatbots (two connected channels on
-- one provider) are deliberately left unbound rather than guessed at.
-- Closed conversations are not backfilled: they are not on the inbound path, and
-- rewriting the whole table would hold the lock far longer. A staff reply to a
-- closed legacy conversation returns CHANNEL_IDENTITY_UNVERIFIED, which is
-- visible and recoverable, unlike a wrong binding.
DO $backfill$
DECLARE r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
      ('telegram','telegram_channels','telegram_bot_id'),
      ('whatsapp','whatsapp_channels','phone_number_id'),
      ('wasender','wasender_channels','provider_user_id')
    ) AS t(source_channel, table_name, identity_column)
  LOOP
    EXECUTE format($sql$
      WITH sole_channel AS (
        SELECT chatbot_id, min(id) AS channel_id, min(%I::text) AS provider_id
        FROM public.%I
        WHERE is_active = true AND connection_status = 'connected' AND %I IS NOT NULL
        GROUP BY chatbot_id HAVING count(*) = 1
      )
      UPDATE public.conversations c
        SET source_channel_id = sole_channel.channel_id,
            source_provider_id = sole_channel.provider_id
        FROM sole_channel
        WHERE c.chatbot_id = sole_channel.chatbot_id
          AND c.source_channel = $1
          AND c.conversation_status = 'open'
          AND c.source_channel_id IS NULL
    $sql$, r.identity_column, r.table_name, r.identity_column) USING r.source_channel;
  END LOOP;
END; $backfill$;

DROP INDEX IF EXISTS public.unique_open_conversation_per_channel;
CREATE UNIQUE INDEX IF NOT EXISTS unique_open_legacy_conversation_per_channel
  ON public.conversations(chatbot_id,customer_phone,source_channel)
  WHERE conversation_status='open' AND source_channel_id IS NULL;
-- Telegram's chat ID is its identity; a supplied phone is only profile data.
DROP INDEX IF EXISTS public.unique_open_bound_conversation_per_phone;
CREATE UNIQUE INDEX unique_open_bound_conversation_per_phone
  ON public.conversations(chatbot_id,customer_phone,source_channel,source_channel_id,source_provider_id)
  WHERE conversation_status='open' AND source_channel_id IS NOT NULL AND source_channel <> 'telegram';
CREATE UNIQUE INDEX IF NOT EXISTS unique_open_bound_conversation_per_platform
  ON public.conversations(chatbot_id,platform_user_id,source_channel,source_channel_id,source_provider_id)
  WHERE conversation_status='open' AND source_channel_id IS NOT NULL AND platform_user_id IS NOT NULL;
CREATE OR REPLACE FUNCTION public.guard_conversation_origin()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $function$
BEGIN
  IF OLD.source_channel_id IS NOT NULL AND
    (OLD.source_channel_id IS DISTINCT FROM NEW.source_channel_id OR OLD.source_provider_id IS DISTINCT FROM NEW.source_provider_id
       OR OLD.source_channel IS DISTINCT FROM NEW.source_channel OR OLD.chatbot_id IS DISTINCT FROM NEW.chatbot_id
       OR (OLD.source_channel='telegram' AND OLD.platform_user_id IS DISTINCT FROM NEW.platform_user_id)) THEN
    RAISE EXCEPTION 'Conversation origin is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$function$;
DROP TRIGGER IF EXISTS conversation_origin_guard ON public.conversations;
CREATE TRIGGER conversation_origin_guard BEFORE UPDATE ON public.conversations
  FOR EACH ROW EXECUTE FUNCTION public.guard_conversation_origin();

CREATE OR REPLACE FUNCTION public.resolve_conversation_escalation(p_action_id bigint,p_chatbot_id bigint,p_company_id bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $function$
DECLARE v_action public.agent_actions%ROWTYPE; v_changed boolean := false; v_resumed boolean := false;
BEGIN
  SELECT a.* INTO v_action FROM public.agent_actions a JOIN public.chatbots b ON b.id=a.chatbot_id
    WHERE a.id=p_action_id AND a.chatbot_id=p_chatbot_id AND a.company_id=p_company_id AND b.company_id=p_company_id
      AND a.intent IN ('handoff_request','complaint','knowledge_gap');
  IF NOT FOUND THEN RETURN NULL; END IF;
  PERFORM 1 FROM public.conversations WHERE id=v_action.conversation_id AND chatbot_id=p_chatbot_id FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  SELECT * INTO v_action FROM public.agent_actions WHERE id=p_action_id FOR UPDATE;
  IF v_action.status='detected' THEN
    UPDATE public.agent_actions SET status='resolved' WHERE id=p_action_id RETURNING * INTO v_action;
    v_changed := true;
  ELSIF v_action.status <> 'resolved' THEN RETURN NULL;
  END IF;
  SELECT NOT EXISTS(SELECT 1 FROM public.agent_actions WHERE conversation_id=v_action.conversation_id
    AND chatbot_id=p_chatbot_id AND company_id=p_company_id AND status='detected'
    AND intent IN ('handoff_request','complaint','knowledge_gap')) INTO v_resumed;
  -- An unbound legacy handoff is kept paused until explicitly resolved. Do not
  -- copy its transcript or guess which provider created it during rollout.
  IF v_resumed THEN
    SELECT NOT EXISTS(
      SELECT 1 FROM public.conversations current_conversation
      JOIN public.conversations legacy ON legacy.chatbot_id=current_conversation.chatbot_id
        AND legacy.source_channel=current_conversation.source_channel
        AND legacy.source_channel_id IS NULL AND legacy.conversation_status='open'
        AND ((current_conversation.platform_user_id IS NOT NULL AND
              (legacy.platform_user_id=current_conversation.platform_user_id OR legacy.customer_phone=current_conversation.platform_user_id))
          OR (current_conversation.customer_phone IS NOT NULL AND legacy.customer_phone=current_conversation.customer_phone))
      JOIN public.agent_actions a ON a.conversation_id=legacy.id AND a.chatbot_id=p_chatbot_id AND a.company_id=p_company_id
        AND a.status='detected' AND a.intent IN ('handoff_request','complaint','knowledge_gap')
      WHERE current_conversation.id=v_action.conversation_id AND current_conversation.source_channel_id IS NOT NULL
    ) INTO v_resumed;
  END IF;
  RETURN jsonb_build_object('resolved_action',to_jsonb(v_action),'changed',v_changed,'ai_resumed',v_resumed);
END;
$function$;
REVOKE ALL ON FUNCTION public.resolve_conversation_escalation(bigint,bigint,bigint) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_conversation_escalation(bigint,bigint,bigint) TO service_role;

COMMIT;

-- Run AFTER the transaction above has committed. VALIDATE takes only SHARE
-- UPDATE EXCLUSIVE, so inbound messages keep flowing while it scans.
-- ALTER TABLE public.conversations VALIDATE CONSTRAINT conversations_origin_pair_check;
