-- Apply before enabling held replies on any bot. Only the service role can read drafts.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS public.held_replies (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
    conversation_id bigint NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    draft text NOT NULL,
    category text NOT NULL,
    subtype text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'edited', 'discarded')),
    resolved_by bigint,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS held_replies_conversation_status_idx
    ON public.held_replies (conversation_id, status);

ALTER TABLE public.held_replies ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.held_replies FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.held_replies_id_seq FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.held_replies TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.held_replies_id_seq TO service_role;

ALTER TABLE public.chatbots
    ADD COLUMN IF NOT EXISTS hold_risky_replies boolean NOT NULL DEFAULT false;
COMMIT;
