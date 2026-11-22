-- Preserve the reason in the log when reverting to the pre-085 terminal statuses.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
UPDATE public.broadcast_logs SET status = 'cancelled' WHERE status = 'skipped';
ALTER TABLE public.broadcast_logs DROP CONSTRAINT IF EXISTS broadcast_logs_status_check;
ALTER TABLE public.broadcast_logs ADD CONSTRAINT broadcast_logs_status_check
    CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'cancelled')) NOT VALID;
ALTER TABLE public.broadcast_logs VALIDATE CONSTRAINT broadcast_logs_status_check;

ALTER TABLE public.broadcast_campaigns
    DROP COLUMN IF EXISTS consent_confirmed_by,
    DROP COLUMN IF EXISTS consent_confirmed_at;
ALTER TABLE public.chatbots DROP COLUMN IF EXISTS followups_enabled;
DROP TABLE IF EXISTS public.marketing_consents;
COMMIT;
