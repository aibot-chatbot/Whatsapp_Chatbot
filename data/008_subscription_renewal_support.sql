-- 008_subscription_renewal_support.sql
-- Idempotent migration to add renewal and billing-period support to
-- subscription tables.
--
-- Adds:
--   billing_period_key on company_subscription_orders for credit idempotency
--   composite index for expiry processing queries
--
-- Does not modify existing rows or change existing behavior.

-- 1. Add billing_period_key to company_subscription_orders
DO 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'billing_period_key'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN billing_period_key TEXT;
    END IF;
END ;

-- Unique index for billing_period_key (only when non-null)
CREATE UNIQUE INDEX IF NOT EXISTS idx_cso_billing_period_key
    ON company_subscription_orders (billing_period_key)
    WHERE billing_period_key IS NOT NULL;

-- 2. Add composite index for expiry processing queries
-- Supports: WHERE status IN ('trialing') AND trial_ends_at <= now
-- Supports: WHERE status IN ('active', 'past_due') AND current_period_end <= now
CREATE INDEX IF NOT EXISTS idx_cs_expiry_trial
    ON company_subscriptions (trial_ends_at)
    WHERE status = 'trialing';

CREATE INDEX IF NOT EXISTS idx_cs_expiry_period
    ON company_subscriptions (current_period_end)
    WHERE status IN ('active', 'past_due');

-- 3. Grant permissions
GRANT ALL ON company_subscription_orders TO service_role;

-- 4. Add column comments
COMMENT ON COLUMN company_subscription_orders.billing_period_key IS
    'Unique key for the billing period this order covers, used for credit-idempotency checks. Format: company_id_subscription_id_period_start. NULL when not yet computed.';

-- 5. Update column comment to match new format
COMMENT ON COLUMN company_subscription_orders.billing_period_key IS
    'Deterministic key for the billing period: company:{company_id}:period:{period_start}:plan:{plan_id}. Populated during activation. Unique index prevents two orders claiming the same period. NULL for pre-migration rows.';
