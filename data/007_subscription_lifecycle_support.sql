-- 007_subscription_lifecycle_support.sql
-- Idempotent migration to add lifecycle management fields to
-- company_subscriptions and add a status CHECK constraint.
--
-- Adds:
--   pending_plan_id             — target plan for a scheduled downgrade
--   plan_change_effective_at    — when the pending plan change takes effect
--   cancellation_scheduled_at   — when cancellation was requested
--   cancellation_effective_at   — when cancellation takes effect
--   cancelled_at                — when cancellation was actually applied
--   status_updated_at           — when status last changed (for monitoring)
--
-- Scheduling fields remain NULL while no change is pending.
-- The subscription status stays 'active' during scheduling.

-- 1. Add lifecycle columns (IF NOT EXISTS for idempotency)
DO 
BEGIN
    -- pending_plan_id
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscriptions'
        AND column_name = 'pending_plan_id'
    ) THEN
        ALTER TABLE company_subscriptions
            ADD COLUMN pending_plan_id BIGINT
            REFERENCES subscription_plans(id);
    END IF;

    -- plan_change_effective_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscriptions'
        AND column_name = 'plan_change_effective_at'
    ) THEN
        ALTER TABLE company_subscriptions
            ADD COLUMN plan_change_effective_at TIMESTAMPTZ;
    END IF;

    -- cancellation_scheduled_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscriptions'
        AND column_name = 'cancellation_scheduled_at'
    ) THEN
        ALTER TABLE company_subscriptions
            ADD COLUMN cancellation_scheduled_at TIMESTAMPTZ;
    END IF;

    -- cancellation_effective_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscriptions'
        AND column_name = 'cancellation_effective_at'
    ) THEN
        ALTER TABLE company_subscriptions
            ADD COLUMN cancellation_effective_at TIMESTAMPTZ;
    END IF;

    -- cancelled_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscriptions'
        AND column_name = 'cancelled_at'
    ) THEN
        ALTER TABLE company_subscriptions
            ADD COLUMN cancelled_at TIMESTAMPTZ;
    END IF;

    -- status_updated_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscriptions'
        AND column_name = 'status_updated_at'
    ) THEN
        ALTER TABLE company_subscriptions
            ADD COLUMN status_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
    END IF;
END ;

-- 2. Add or update status CHECK constraint
-- Drop any existing constraint first (idempotent)
ALTER TABLE company_subscriptions
    DROP CONSTRAINT IF EXISTS company_subscriptions_status_check;

ALTER TABLE company_subscriptions
    ADD CONSTRAINT company_subscriptions_status_check
    CHECK (status IN ('trialing', 'active', 'past_due', 'expired', 'cancelled'));

-- 3. Add indexes for lifecycle queries
CREATE INDEX IF NOT EXISTS idx_cs_status
    ON company_subscriptions (status);

CREATE INDEX IF NOT EXISTS idx_cs_current_period_end
    ON company_subscriptions (current_period_end)
    WHERE status IN ('active', 'past_due');

CREATE INDEX IF NOT EXISTS idx_cs_pending_plan_id
    ON company_subscriptions (pending_plan_id)
    WHERE pending_plan_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cs_cancellation_effective
    ON company_subscriptions (cancellation_effective_at)
    WHERE cancellation_effective_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cs_plan_change_effective
    ON company_subscriptions (plan_change_effective_at)
    WHERE plan_change_effective_at IS NOT NULL;

-- 4. Grant permissions
GRANT ALL ON company_subscriptions TO service_role;

-- 5. Add column comments
COMMENT ON COLUMN company_subscriptions.pending_plan_id IS
    'Target plan for a scheduled plan change (downgrade or upgrade on renewal). NULL when no change is pending.';

COMMENT ON COLUMN company_subscriptions.plan_change_effective_at IS
    'UTC timestamp when the pending plan change should be executed. NULL when no change is pending.';

COMMENT ON COLUMN company_subscriptions.cancellation_scheduled_at IS
    'UTC timestamp when the customer requested cancellation. NULL when no cancellation is pending.';

COMMENT ON COLUMN company_subscriptions.cancellation_effective_at IS
    'UTC timestamp when the cancellation takes effect (usually current_period_end). NULL when no cancellation is pending.';

COMMENT ON COLUMN company_subscriptions.cancelled_at IS
    'UTC timestamp when cancellation was actually applied (status moved to cancelled). NULL while active.';

COMMENT ON COLUMN company_subscriptions.status_updated_at IS
    'UTC timestamp of the most recent status change. Updated by the lifecycle service. Defaults to created_at.';
