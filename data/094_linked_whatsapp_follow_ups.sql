BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

-- The existing gentle-mode constraint caps touch_count at one.
ALTER TABLE public.follow_ups DROP CONSTRAINT follow_ups_platform_check,
    ADD CONSTRAINT follow_ups_platform_check CHECK (
        platform IN ('telegram', 'whatsapp') OR
        (platform = 'whatsapp_link' AND mode = 'gentle' AND kind = 'sales')
    );

COMMIT;
