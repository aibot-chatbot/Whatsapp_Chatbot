BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.whatsapp_templates (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    channel_id bigint REFERENCES public.whatsapp_channels(id) ON DELETE SET NULL,
    waba_id text NOT NULL,
    meta_template_id text NOT NULL,
    name text NOT NULL,
    language text NOT NULL,
    category text NOT NULL,
    status text NOT NULL,
    rejected_reason text,
    body_has_variables boolean NOT NULL,
    requires_component_parameters boolean NOT NULL,
    status_event_time bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (waba_id, name, language),
    UNIQUE (waba_id, meta_template_id)
);

ALTER TABLE public.whatsapp_templates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_templates FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.whatsapp_templates TO service_role;
REVOKE ALL ON SEQUENCE public.whatsapp_templates_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.whatsapp_templates_id_seq TO service_role;

ALTER TABLE public.chatbots
    ADD COLUMN followup_template_id bigint REFERENCES public.whatsapp_templates(id) ON DELETE SET NULL;

CREATE OR REPLACE VIEW public.follow_up_receipts WITH (security_invoker = true) AS
SELECT e.company_id, e.chatbot_id, e.conversation_id, e.source_id, e.ordinal, e.sent_at, mc.withdrawn_at
FROM (
    SELECT b.company_id, c.chatbot_id, c.id AS conversation_id, m.id AS source_id, 0::bigint AS ordinal,
           m.follow_up_sent_at AS sent_at, c.source_channel AS platform, c.platform_user_id
    FROM public.messages m
    JOIN public.conversations c ON c.id = m.conversation_id
    JOIN public.chatbots b ON b.id = c.chatbot_id
    WHERE m.follow_up_sent_at IS NOT NULL AND m.sender_type = 'bot'
        AND ((m.ai_generated AND m.delivery_status = 'sent')
             OR (c.source_channel = 'whatsapp' AND m.delivery_status IN ('sent', 'delivered', 'read')
                 AND (m.ai_generated OR m.message_type = 'template')))
    UNION ALL
    SELECT f.company_id, f.chatbot_id, f.conversation_id, f.id, t.ordinal, t.sent_at,
           f.platform, c.platform_user_id
    FROM public.follow_ups f
    JOIN public.chatbots b ON b.id = f.chatbot_id AND b.company_id = f.company_id
    JOIN public.conversations c ON c.id = f.conversation_id AND c.chatbot_id = b.id
    CROSS JOIN LATERAL unnest(f.legacy_touch_times) WITH ORDINALITY AS t(sent_at, ordinal)
) e
LEFT JOIN public.marketing_consents mc ON mc.company_id = e.company_id
    AND mc.platform = e.platform AND mc.platform_user_id = e.platform_user_id
    AND mc.status = 'withdrawn';
REVOKE ALL ON public.follow_up_receipts FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.follow_up_receipts TO service_role;

COMMIT;
