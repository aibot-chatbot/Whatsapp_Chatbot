BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE OR REPLACE VIEW public.follow_up_receipts WITH (security_invoker = true) AS
SELECT e.company_id, e.chatbot_id, e.conversation_id, e.source_id, e.ordinal, e.sent_at, mc.withdrawn_at
FROM (
    SELECT b.company_id, c.chatbot_id, c.id AS conversation_id, m.id AS source_id, 0::bigint AS ordinal,
           m.follow_up_sent_at AS sent_at, c.source_channel AS platform, c.platform_user_id, c.customer_phone
    FROM public.messages m
    JOIN public.conversations c ON c.id = m.conversation_id
    JOIN public.chatbots b ON b.id = c.chatbot_id
    WHERE m.follow_up_sent_at IS NOT NULL AND m.sender_type = 'bot'
        AND ((m.ai_generated AND m.delivery_status = 'sent')
             OR (c.source_channel = 'whatsapp' AND m.delivery_status IN ('sent', 'delivered', 'read')
                 AND (m.ai_generated OR m.message_type = 'template')))
    UNION ALL
    SELECT f.company_id, f.chatbot_id, f.conversation_id, f.id, t.ordinal, t.sent_at,
           f.platform, c.platform_user_id, c.customer_phone
    FROM public.follow_ups f
    JOIN public.chatbots b ON b.id = f.chatbot_id AND b.company_id = f.company_id
    JOIN public.conversations c ON c.id = f.conversation_id AND c.chatbot_id = b.id
    CROSS JOIN LATERAL unnest(f.legacy_touch_times) WITH ORDINALITY AS t(sent_at, ordinal)
) e
-- One withdrawal timestamp per receipt, even when both WhatsApp identities have STOP rows.
LEFT JOIN LATERAL (
    SELECT max(w.withdrawn_at) AS withdrawn_at
    FROM public.marketing_consents w
    WHERE w.company_id = e.company_id AND w.status = 'withdrawn'
      AND ((w.platform = e.platform AND w.platform_user_id = e.platform_user_id)
           OR (e.platform IN ('whatsapp', 'whatsapp_link') AND w.phone_digits = COALESCE(
               CASE e.platform
                   WHEN 'whatsapp_link' THEN substring(e.platform_user_id FROM '^([0-9]{8,15})@c[.]us$')
                   WHEN 'whatsapp' THEN substring(e.platform_user_id FROM '^[+]?([0-9]{1,15})$')
               END,
               substring(e.customer_phone FROM '^[+]?([0-9]{8,15})$')
           )))
) mc ON true;
REVOKE ALL ON public.follow_up_receipts FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.follow_up_receipts TO service_role;

COMMIT;
