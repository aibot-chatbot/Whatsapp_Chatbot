BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
DROP VIEW IF EXISTS public.follow_up_receipts;
DROP INDEX IF EXISTS public.messages_follow_up_sent_idx;
ALTER TABLE public.messages DROP COLUMN IF EXISTS follow_up_sent_at;
ALTER TABLE public.follow_ups DROP COLUMN IF EXISTS legacy_touch_times;
ALTER TABLE public.chatbots
    DROP COLUMN IF EXISTS followups_auto_stop_counts,
    DROP COLUMN IF EXISTS followups_auto_stopped_at,
    DROP COLUMN IF EXISTS followups_enabled_at;
COMMIT;
