-- 009_subscription_activation_atomicity.sql

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS source_plan_id BIGINT;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS source_period_start TIMESTAMPTZ;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS source_period_end TIMESTAMPTZ;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS source_status TEXT;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS activation_type TEXT;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS activation_sequence_key TEXT;

-- Add source-plan foreign key only when it does not already exist.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'company_subscription_orders_source_plan_id_fkey'
          AND conrelid = 'public.company_subscription_orders'::regclass
    ) THEN
        ALTER TABLE public.company_subscription_orders
            ADD CONSTRAINT company_subscription_orders_source_plan_id_fkey
            FOREIGN KEY (source_plan_id)
            REFERENCES public.subscription_plans(id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_cso_activation_sequence_key
    ON public.company_subscription_orders (activation_sequence_key)
    WHERE activation_sequence_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cso_gateway_order_id
    ON public.company_subscription_orders (gateway_order_id)
    WHERE gateway_order_id IS NOT NULL;

ALTER TABLE public.company_subscription_orders
    DROP CONSTRAINT IF EXISTS cso_activation_type_check;

ALTER TABLE public.company_subscription_orders
    ADD CONSTRAINT cso_activation_type_check
    CHECK (
        activation_type IS NULL
        OR activation_type IN (
            'initial_purchase',
            'renewal',
            'upgrade'
        )
    );

GRANT ALL ON public.company_subscription_orders TO service_role;

COMMENT ON COLUMN public.company_subscription_orders.source_plan_id IS
    'Subscription plan snapshot captured when checkout was created.';

COMMENT ON COLUMN public.company_subscription_orders.source_period_start IS
    'Subscription current_period_start snapshot captured during checkout.';

COMMENT ON COLUMN public.company_subscription_orders.source_period_end IS
    'Subscription current_period_end snapshot captured during checkout.';

COMMENT ON COLUMN public.company_subscription_orders.source_status IS
    'Subscription status snapshot captured during checkout.';

COMMENT ON COLUMN public.company_subscription_orders.activation_type IS
    'Activation type: initial_purchase, renewal, or upgrade.';

COMMENT ON COLUMN public.company_subscription_orders.activation_sequence_key IS
    'Deterministic key used to atomically prevent duplicate subscription activation.';

COMMENT ON COLUMN public.company_subscription_orders.billing_period_key IS
    'Deprecated in favour of activation_sequence_key. Retained for historical compatibility.';