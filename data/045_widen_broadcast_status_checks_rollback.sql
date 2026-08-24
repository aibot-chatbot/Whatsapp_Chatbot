-- 045_widen_broadcast_status_checks_rollback.sql
--
-- Reverts 044 to the pre-cancellation vocabulary.
--
-- This fails if any row already holds a cancelled/cancelling value. Map those
-- back first -- campaigns to 'failed', recipients to 'failed' -- then run this:
--
--   UPDATE public.broadcast_campaigns SET status = 'failed'
--    WHERE status IN ('cancelling', 'cancelled');
--   UPDATE public.broadcast_logs SET status = 'failed'
--    WHERE status = 'cancelled';

BEGIN;

ALTER TABLE public.broadcast_campaigns
    DROP CONSTRAINT IF EXISTS broadcast_campaigns_status_check;

ALTER TABLE public.broadcast_campaigns
    ADD CONSTRAINT broadcast_campaigns_status_check
    CHECK (status IN ('draft', 'sending', 'completed', 'failed')) NOT VALID;

ALTER TABLE public.broadcast_campaigns
    VALIDATE CONSTRAINT broadcast_campaigns_status_check;

ALTER TABLE public.broadcast_logs
    DROP CONSTRAINT IF EXISTS broadcast_logs_status_check;

ALTER TABLE public.broadcast_logs
    ADD CONSTRAINT broadcast_logs_status_check
    CHECK (status IN ('pending', 'sending', 'sent', 'failed')) NOT VALID;

ALTER TABLE public.broadcast_logs
    VALIDATE CONSTRAINT broadcast_logs_status_check;

COMMIT;
