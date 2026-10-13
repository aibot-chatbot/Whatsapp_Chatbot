-- Increase the Pro workspace channel allowance from two to four.
--
-- Channel enforcement reads subscription_plans.channel_limit on every
-- activation, so existing active Pro subscriptions receive the new allowance
-- as soon as this migration is applied. No subscription rows need rewriting.

BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

UPDATE public.subscription_plans
SET channel_limit = 4,
    description = replace(description, '2 channels', '4 channels'),
    updated_at = now()
WHERE lower(code) = 'pro'
  AND channel_limit IS DISTINCT FROM 4;

COMMIT;

