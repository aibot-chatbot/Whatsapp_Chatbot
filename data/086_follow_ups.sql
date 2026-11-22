BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS public.follow_ups (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
    conversation_id bigint NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    source_message_id bigint NOT NULL REFERENCES public.messages(id) ON DELETE CASCADE,
    platform text NOT NULL CHECK (platform IN ('telegram', 'whatsapp')),
    mode text NOT NULL CHECK (mode IN ('sales', 'gentle')),
    kind text NOT NULL CHECK (kind IN ('sales', 'check_in')),
    touch_count smallint NOT NULL DEFAULT 0 CHECK (touch_count BETWEEN 0 AND 3),
    next_due_at timestamptz NOT NULL,
    last_touch_at timestamptz,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished', 'stopped')),
    stop_reason text,
    lease_token uuid,
    lease_expires_at timestamptz,
    won_lead_id bigint,
    won_at timestamptz,
    scheduled_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (kind <> 'check_in' OR (mode = 'sales' AND won_lead_id IS NOT NULL AND won_at IS NOT NULL)),
    CHECK ((kind = 'sales' AND mode = 'sales') OR touch_count <= 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS follow_ups_active_conversation_idx
    ON public.follow_ups (conversation_id) WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS follow_ups_sales_turn_idx
    ON public.follow_ups (conversation_id, source_message_id) WHERE kind = 'sales';
CREATE INDEX IF NOT EXISTS follow_ups_due_idx
    ON public.follow_ups (next_due_at) WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS follow_ups_check_in_idx
    ON public.follow_ups (conversation_id, won_lead_id) WHERE kind = 'check_in';

ALTER TABLE public.follow_ups ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.follow_ups FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.follow_ups_id_seq FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.follow_ups TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.follow_ups_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.claim_due_follow_ups(p_limit integer DEFAULT 1)
RETURNS SETOF public.follow_ups LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
    WITH due AS (
        SELECT id FROM public.follow_ups
        WHERE status = 'active' AND next_due_at <= now()
          AND (lease_expires_at IS NULL OR lease_expires_at <= now())
        ORDER BY next_due_at, id LIMIT greatest(1, least(p_limit, 10)) FOR UPDATE SKIP LOCKED
    )
    UPDATE public.follow_ups f SET lease_token = gen_random_uuid(),
        lease_expires_at = now() + interval '10 minutes', updated_at = now()
    FROM due WHERE f.id = due.id RETURNING f.*;
$$;
REVOKE ALL ON FUNCTION public.claim_due_follow_ups(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_due_follow_ups(integer) TO service_role;

-- A CRM note can change updated_at while a reply is still scheduling its first touch.
ALTER TABLE public.crm_leads ADD COLUMN IF NOT EXISTS follow_up_won_at timestamptz;
CREATE OR REPLACE FUNCTION public.wake_follow_up_on_lead_outcome()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status IS NOT DISTINCT FROM NEW.status THEN
        RETURN NEW;
    END IF;
    IF NEW.status = 'won' THEN
        NEW.follow_up_won_at := now();
    END IF;
    UPDATE public.follow_ups f
    SET status = CASE WHEN NEW.status = 'lost' THEN 'stopped' ELSE f.status END,
        stop_reason = CASE WHEN NEW.status = 'lost' THEN 'lead_lost' END,
        won_lead_id = CASE WHEN NEW.status = 'won' THEN NEW.id ELSE f.won_lead_id END,
        won_at = CASE WHEN NEW.status = 'won' THEN now() ELSE f.won_at END,
        next_due_at = now(), lease_token = NULL, lease_expires_at = NULL, updated_at = now()
    WHERE f.company_id = NEW.company_id AND f.chatbot_id = NEW.chatbot_id
      AND f.conversation_id = NEW.conversation_id AND f.status = 'active'
      AND (f.kind = 'sales' OR (NEW.status = 'lost' AND f.won_lead_id = NEW.id));
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.wake_follow_up_on_lead_outcome() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.wake_follow_up_on_lead_outcome() TO service_role;
DROP TRIGGER IF EXISTS follow_ups_lead_outcome ON public.crm_leads;
CREATE TRIGGER follow_ups_lead_outcome BEFORE INSERT OR UPDATE OF status ON public.crm_leads
    FOR EACH ROW WHEN (NEW.status IN ('won', 'lost'))
    EXECUTE FUNCTION public.wake_follow_up_on_lead_outcome();

-- Consume the lease and create its single check-in together, including across a worker restart.
CREATE OR REPLACE FUNCTION public.finish_won_follow_up(
    p_id bigint, p_company_id bigint, p_chatbot_id bigint, p_conversation_id bigint,
    p_lease_token uuid, p_lead_id bigint, p_due_at timestamptz
) RETURNS void LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
    WITH won AS (
        UPDATE public.follow_ups f SET status = 'stopped', stop_reason = 'lead_won',
            updated_at = now(), lease_token = NULL, lease_expires_at = NULL
        FROM public.crm_leads l WHERE f.id = p_id AND f.company_id = p_company_id
          AND f.chatbot_id = p_chatbot_id AND f.conversation_id = p_conversation_id
          AND f.status = 'active' AND f.kind = 'sales' AND f.mode = 'sales'
          AND f.lease_token = p_lease_token AND f.lease_expires_at > now()
          AND l.id = p_lead_id AND l.company_id = f.company_id AND l.chatbot_id = f.chatbot_id
          AND l.conversation_id = f.conversation_id AND l.status = 'won'
        RETURNING f.*, l.follow_up_won_at AS lead_won_at
    )
    INSERT INTO public.follow_ups (company_id, chatbot_id, conversation_id, source_message_id,
                                  platform, mode, kind, won_lead_id, won_at, next_due_at)
    SELECT company_id, chatbot_id, conversation_id, source_message_id, platform, mode, 'check_in',
           p_lead_id, coalesce(won_at, lead_won_at), p_due_at FROM won
    ON CONFLICT (conversation_id, won_lead_id) WHERE kind = 'check_in' DO NOTHING;
$$;
REVOKE ALL ON FUNCTION public.finish_won_follow_up(bigint,bigint,bigint,bigint,uuid,bigint,timestamptz)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finish_won_follow_up(bigint,bigint,bigint,bigint,uuid,bigint,timestamptz)
    TO service_role;
COMMIT;
