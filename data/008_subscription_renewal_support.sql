-- 008_subscription_renewal_support.sql

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS billing_period_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_cso_billing_period_key
    ON public.company_subscription_orders (billing_period_key)
    WHERE billing_period_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cs_expiry_trial
    ON public.company_subscriptions (trial_ends_at)
    WHERE status = 'trialing';

CREATE INDEX IF NOT EXISTS idx_cs_expiry_period
    ON public.company_subscriptions (current_period_end)
    WHERE status IN ('active', 'past_due');

GRANT ALL ON public.company_subscription_orders TO service_role;
GRANT ALL ON public.company_subscriptions TO service_role;

COMMENT ON COLUMN public.company_subscription_orders.billing_period_key IS
    'Historical billing-period idempotency key. Retained for compatibility; newer orders use activation_sequence_key.';