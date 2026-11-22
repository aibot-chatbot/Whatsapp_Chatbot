BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.chatbots
    ADD COLUMN IF NOT EXISTS followups_enabled_at timestamptz,
    ADD COLUMN IF NOT EXISTS followups_auto_stopped_at timestamptz,
    ADD COLUMN IF NOT EXISTS followups_auto_stop_counts jsonb;

ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS follow_up_sent_at timestamptz;
CREATE INDEX IF NOT EXISTS messages_follow_up_sent_idx
    ON public.messages (conversation_id, follow_up_sent_at) WHERE follow_up_sent_at IS NOT NULL;
ALTER TABLE public.follow_ups ADD COLUMN IF NOT EXISTS legacy_touch_times timestamptz[];
ALTER TABLE public.follow_ups ALTER COLUMN legacy_touch_times SET DEFAULT '{}';

-- 086 recorded the last send exactly. Recover earlier sends only when the
-- transcript between scheduling and that send accounts for every earlier touch.
WITH legacy AS (
    SELECT f.id, f.last_touch_at, f.touch_count, array_agg(m.created_at ORDER BY m.created_at)
        FILTER (WHERE m.id IS NOT NULL) AS earlier
    FROM public.follow_ups f
    LEFT JOIN public.messages m ON m.conversation_id = f.conversation_id
        AND m.id > f.source_message_id AND m.created_at >= f.scheduled_at
        AND m.created_at < f.last_touch_at AND m.sender_type = 'bot'
        AND m.ai_generated AND m.delivery_status = 'sent'
    WHERE f.legacy_touch_times IS NULL
    GROUP BY f.id
)
UPDATE public.follow_ups f SET legacy_touch_times =
    CASE WHEN l.last_touch_at IS NULL THEN '{}'::timestamptz[]
         WHEN cardinality(l.earlier) = l.touch_count - 1
         THEN array_append(l.earlier, l.last_touch_at) ELSE ARRAY[l.last_touch_at] END
FROM legacy l WHERE f.id = l.id;

-- A withdrawal belongs to the company even if it was received by another bot.
CREATE OR REPLACE VIEW public.follow_up_receipts WITH (security_invoker = true) AS
SELECT e.company_id, e.chatbot_id, e.conversation_id, e.source_id, e.ordinal, e.sent_at, mc.withdrawn_at
FROM (
    SELECT b.company_id, c.chatbot_id, c.id AS conversation_id, m.id AS source_id, 0::bigint AS ordinal,
           m.follow_up_sent_at AS sent_at, c.source_channel AS platform, c.platform_user_id
    FROM public.messages m
    JOIN public.conversations c ON c.id = m.conversation_id
    JOIN public.chatbots b ON b.id = c.chatbot_id
    WHERE m.follow_up_sent_at IS NOT NULL AND m.delivery_status = 'sent'
        AND m.sender_type = 'bot' AND m.ai_generated
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
