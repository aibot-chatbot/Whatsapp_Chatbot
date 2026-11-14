-- 082: why an OpenRouter key was disabled, and let Clients move between keys (plan step E6).
--
--   openrouter_client_keys.disabled_reason      'ours' = disabled by an operator because of one
--                                               Client; 'openrouter' = OpenRouter disabled it or
--                                               it is missing there. NULL = not recorded (an empty
--                                               key retired by the app, or disabled before 082).
--   openrouter_client_keys.culprit_company_id   the Client a key was disabled for ('ours' only).
--                                               No foreign key, so deleting a Client never waits
--                                               on this table; identity ids are never reused.
--   openrouter_key_assignments UPDATE grant     the key check moves every other Client off a key
--                                               disabled for one Client; 081 granted no UPDATE.
--
-- Both columns are nullable with no default, so adding them rewrites nothing. No new policy: the
-- tables stay service-role only, as 081 set them up.
--
-- Not applied by this file's author. Safe to deploy the code before or after this: until it is
-- applied, the code moves nobody and keeps alerting the owner. Rollback:
-- 082_openrouter_key_disable_reason_rollback.sql.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.openrouter_client_keys
    ADD COLUMN IF NOT EXISTS disabled_reason text CHECK (disabled_reason IN ('ours', 'openrouter')),
    ADD COLUMN IF NOT EXISTS culprit_company_id bigint;

-- Required: 081 gave service_role SELECT and INSERT only on the assignments. Its table-level
-- UPDATE on openrouter_client_keys already covers the two new columns.
GRANT UPDATE ON public.openrouter_key_assignments TO service_role;

COMMIT;
