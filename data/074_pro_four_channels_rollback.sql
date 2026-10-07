-- Roll back only the Pro channel allowance introduced by migration 074.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

UPDATE public.subscription_plans
SET channel_limit = 2,
    description = replace(description, '4 channels', '2 channels'),
    updated_at = now()
WHERE lower(code) = 'pro'
  AND channel_limit = 4;

COMMIT;

