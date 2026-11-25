BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

-- Validation aborts the rollback if linked reminders exist, preserving their history.
ALTER TABLE public.follow_ups DROP CONSTRAINT follow_ups_platform_check,
    ADD CONSTRAINT follow_ups_platform_check CHECK (platform IN ('telegram', 'whatsapp'));

COMMIT;
