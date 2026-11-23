BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.whatsapp_channels
    ADD COLUMN onboarding_type text NOT NULL DEFAULT 'standard'
        CONSTRAINT whatsapp_channels_onboarding_type_check
        CHECK (onboarding_type IN ('standard', 'coexistence')),
    ADD COLUMN register_pin_encrypted text;

-- Reserve the number before changing its PIN at Meta. The connected-only
-- index in 058 otherwise detects competing registrations only at activation.
CREATE UNIQUE INDEX whatsapp_channels_registration_uidx
    ON public.whatsapp_channels (phone_number_id)
    WHERE is_active AND (connection_status = 'connected'
        OR (connection_status = 'pending' AND register_pin_encrypted IS NOT NULL));

COMMIT;
