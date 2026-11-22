-- Preserve completed moves and audit history. Old keys stay disabled.
-- Migration 082 has no manual-replacement reason, so its value becomes NULL.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP FUNCTION IF EXISTS public.replace_openrouter_client_key(bigint, text, text, text, bigint, text);

ALTER TABLE public.openrouter_client_keys
    DROP CONSTRAINT IF EXISTS openrouter_manual_replacement_is_final,
    DROP COLUMN IF EXISTS replacement_reason;

UPDATE public.openrouter_client_keys
    SET disabled_reason = NULL WHERE disabled_reason = 'manual_replacement';

ALTER TABLE public.openrouter_client_keys
    DROP CONSTRAINT openrouter_client_keys_disabled_reason_check,
    ADD CONSTRAINT openrouter_client_keys_disabled_reason_check
        CHECK (disabled_reason IN ('ours', 'openrouter'));

COMMIT;
