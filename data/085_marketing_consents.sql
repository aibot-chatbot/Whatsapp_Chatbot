BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS public.marketing_consents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    platform text NOT NULL CHECK (platform IN ('telegram', 'whatsapp', 'whatsapp_link')),
    platform_user_id text NOT NULL CHECK (platform_user_id <> ''),
    phone_digits text CHECK (phone_digits ~ '^[0-9]+$'),
    status text NOT NULL CHECK (status IN ('asked', 'granted', 'withdrawn')),
    asked_at timestamptz,
    granted_at timestamptz,
    withdrawn_at timestamptz,
    source text NOT NULL CHECK (source IN ('chat_reply', 'stop_word')),
    chatbot_id bigint REFERENCES public.chatbots(id) ON DELETE SET NULL,
    evidence_message_id bigint REFERENCES public.messages(id) ON DELETE SET NULL,
    business_name text,
    language text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, platform, platform_user_id)
);

CREATE INDEX IF NOT EXISTS marketing_consents_phone_idx
    ON public.marketing_consents (company_id, phone_digits) WHERE phone_digits IS NOT NULL;

ALTER TABLE public.marketing_consents ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.marketing_consents FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.marketing_consents_id_seq FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.marketing_consents TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.marketing_consents_id_seq TO service_role;

ALTER TABLE public.chatbots ADD COLUMN IF NOT EXISTS followups_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE public.broadcast_campaigns
    ADD COLUMN IF NOT EXISTS consent_confirmed_by bigint REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS consent_confirmed_at timestamptz;

ALTER TABLE public.broadcast_logs DROP CONSTRAINT IF EXISTS broadcast_logs_status_check;
ALTER TABLE public.broadcast_logs ADD CONSTRAINT broadcast_logs_status_check
    CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'cancelled', 'skipped')) NOT VALID;
ALTER TABLE public.broadcast_logs VALIDATE CONSTRAINT broadcast_logs_status_check;
COMMIT;
