-- 093 rollback: remove the add function and first-assignment tracking.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP FUNCTION IF EXISTS public.add_openrouter_client_key(text, text, text, integer, bigint);
DROP TRIGGER IF EXISTS mark_openrouter_key_assigned ON public.openrouter_key_assignments;
DROP FUNCTION IF EXISTS public.mark_openrouter_key_assigned();
ALTER TABLE public.openrouter_client_keys DROP COLUMN IF EXISTS awaiting_first_client;
COMMIT;
