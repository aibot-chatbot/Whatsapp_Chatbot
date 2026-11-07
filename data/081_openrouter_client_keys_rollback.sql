-- Roll back migration 081. Set OPENROUTER_CLIENT_KEYS_ENABLED=false and restart FIRST, so nothing
-- is reading these tables. This destroys the only stored copy of every key, because OpenRouter
-- shows a key once: disable the omnexa-pool-* keys in the OpenRouter dashboard afterwards.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP TABLE IF EXISTS public.openrouter_key_assignments;
DROP TABLE IF EXISTS public.openrouter_client_keys;

COMMIT;
