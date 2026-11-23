BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

-- Dropping the column would lose the two-step PIN of every registered standard number.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.whatsapp_channels WHERE register_pin_encrypted IS NOT NULL) THEN
        RAISE EXCEPTION 'Registration PINs are stored; export them before rolling back 090.';
    END IF;
END
$$;

DROP INDEX public.whatsapp_channels_registration_uidx;
ALTER TABLE public.whatsapp_channels
    DROP COLUMN onboarding_type,
    DROP COLUMN register_pin_encrypted;

COMMIT;
