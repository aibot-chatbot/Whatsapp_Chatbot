-- Roll back migration 080: remove the self-service workspace deletion functions and the
-- confirmation-code table. Workspaces already deleted stay deleted; this only removes the means
-- to delete more. Pending (unexpired) confirmation codes are lost, which is harmless.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP FUNCTION IF EXISTS public.delete_company_account(bigint, bigint);
DROP FUNCTION IF EXISTS public.account_deletion_blocker(bigint, bigint);
DROP TABLE IF EXISTS public.account_deletion_codes;
DROP INDEX IF EXISTS public.messages_actor_user_id_idx;

COMMIT;
