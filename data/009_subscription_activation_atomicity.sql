-- 009_subscription_activation_atomicity.sql
-- Idempotent migration to add atomic activation support to
-- company_subscription_orders.
--
-- Adds:
--   source_plan_id          — snapshot of the subscription's plan_id at checkout time
--   source_period_start     — snapshot of current_period_start at checkout time
--   source_period_end       — snapshot of current_period_end at checkout time
--   source_status           — snapshot of subscription status at checkout time
--   activation_type         — 'initial_purchase', 'renewal', or 'upgrade'
--   activation_sequence_key — deterministic key claimed atomically during activation
--
-- The unique partial index on activation_sequence_key ensures that two
-- orders created against the same source subscription state cannot both
-- activate.  The key is computed at order-creation time (not callback time).
--
-- Does not modify existing rows or change existing behavior.

-- 1. Add source-snapshot columns (IF NOT EXISTS for idempotency)
DO \$\$
BEGIN
    -- source_plan_id
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'source_plan_id'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN source_plan_id BIGINT
            REFERENCES subscription_plans(id);
    END IF;

    -- source_period_start
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'source_period_start'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN source_period_start TIMESTAMPTZ;
    END IF;

    -- source_period_end
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'source_period_end'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN source_period_end TIMESTAMPTZ;
    END IF;

    -- source_status
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'source_status'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN source_status TEXT;
    END IF;

    -- activation_type
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'activation_type'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN activation_type TEXT;
    END IF;

    -- activation_sequence_key
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'activation_sequence_key'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN activation_sequence_key TEXT;
    END IF;
END \$\$;

-- 2. Unique partial index on activation_sequence_key (only when non-null)
CREATE UNIQUE INDEX IF NOT EXISTS idx_cso_activation_sequence_key
    ON company_subscription_orders (activation_sequence_key)
    WHERE activation_sequence_key IS NOT NULL;

-- 3. Index on gateway_order_id for callback lookup
CREATE INDEX IF NOT EXISTS idx_cso_gateway_order_id
    ON company_subscription_orders (gateway_order_id)
    WHERE gateway_order_id IS NOT NULL;

-- 4. Grant permissions to service_role
GRANT ALL ON company_subscription_orders TO service_role;

-- 5. Add column comments
COMMENT ON COLUMN company_subscription_orders.source_plan_id IS
    'Snapshot of the subscription plan_id at the time the checkout order was created. Used during activation to verify the subscription has not been changed by another order.';

COMMENT ON COLUMN company_subscription_orders.source_period_start IS
    'Snapshot of subscription current_period_start at checkout time. NULL for new (trial) companies.';

COMMENT ON COLUMN company_subscription_orders.source_period_end IS
    'Snapshot of subscription current_period_end at checkout time. Used to generate renewal activation_sequence_key.';

COMMENT ON COLUMN company_subscription_orders.source_status IS
    'Snapshot of subscription status at checkout time. Used to validate the expected activation path during callback.';

COMMENT ON COLUMN company_subscription_orders.activation_type IS
    'Type of activation this order represents: initial_purchase (trial?paid), renewal (expired/past_due?active), or upgrade (active?higher plan).';

COMMENT ON COLUMN company_subscription_orders.activation_sequence_key IS
    'Deterministic key claimed atomically during payment activation to prevent two orders against the same source subscription state from both activating. Format depends on activation_type. Unique partial index prevents concurrent claims.';

-- 6. Update billing_period_key comment to note deprecation
COMMENT ON COLUMN company_subscription_orders.billing_period_key IS
    'DEPRECATED in favour of activation_sequence_key. Retained for historical rows.';

-- 7. Add activation_type check constraint
ALTER TABLE company_subscription_orders
    DROP CONSTRAINT IF EXISTS cso_activation_type_check;

ALTER TABLE company_subscription_orders
    ADD CONSTRAINT cso_activation_type_check
    CHECK (
        activation_type IS NULL
        OR activation_type IN ('initial_purchase', 'renewal', 'upgrade')
    );
