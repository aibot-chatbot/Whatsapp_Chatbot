-- Roll back migration 082. The code may stay deployed: without these columns it moves nobody and
-- alerts the owner about disabled keys, as before 082. A key disabled because of one Client loses
-- that record, so the check then treats it like any disabled key: nobody moves, the owner is told.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

REVOKE UPDATE ON public.openrouter_key_assignments FROM service_role;

ALTER TABLE public.openrouter_client_keys
    DROP COLUMN IF EXISTS disabled_reason,
    DROP COLUMN IF EXISTS culprit_company_id;

COMMIT;
