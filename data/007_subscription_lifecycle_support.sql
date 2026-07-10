-- 007_subscription_lifecycle_support.sql

ALTER TABLE public.company_subscriptions
    ADD COLUMN IF NOT EXISTS pending_plan_id BIGINT;

ALTER TABLE public.company_subscriptions
    ADD COLUMN IF NOT EXISTS plan_change_effective_at TIMESTAMPTZ;

ALTER TABLE public.company_subscriptions
    ADD COLUMN IF NOT EXISTS cancellation_scheduled_at TIMESTAMPTZ;

ALTER TABLE public.company_subscriptions
    ADD COLUMN IF NOT EXISTS cancellation_effective_at TIMESTAMPTZ;

ALTER TABLE public.company_subscriptions
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

ALTER TABLE public.company_subscriptions
    ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Add pending-plan foreign key only when it does not already exist.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'company_subscriptions_pending_plan_id_fkey'
          AND conrelid = 'public.company_subscriptions'::regclass
    ) THEN
        ALTER TABLE public.company_subscriptions
            ADD CONSTRAINT company_subscriptions_pending_plan_id_fkey
            FOREIGN KEY (pending_plan_id)
            REFERENCES public.subscription_plans(id);
    END IF;
END $$;

ALTER TABLE public.company_subscriptions
    DROP CONSTRAINT IF EXISTS company_subscriptions_status_check;

ALTER TABLE public.company_subscriptions
    ADD CONSTRAINT company_subscriptions_status_check
    CHECK (
        status IN (
            'trialing',
            'active',
            'past_due',
            'expired',
            'cancelled'
        )
    );

CREATE INDEX IF NOT EXISTS idx_cs_status
    ON public.company_subscriptions (status);

CREATE INDEX IF NOT EXISTS idx_cs_current_period_end
    ON public.company_subscriptions (current_period_end)
    WHERE status IN ('active', 'past_due');

CREATE INDEX IF NOT EXISTS idx_cs_pending_plan_id
    ON public.company_subscriptions (pending_plan_id)
    WHERE pending_plan_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cs_cancellation_effective
    ON public.company_subscriptions (cancellation_effective_at)
    WHERE cancellation_effective_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cs_plan_change_effective
    ON public.company_subscriptions (plan_change_effective_at)
    WHERE plan_change_effective_at IS NOT NULL;

GRANT ALL ON public.company_subscriptions TO service_role;

COMMENT ON COLUMN public.company_subscriptions.pending_plan_id IS
    'Target paid plan for a scheduled plan change. NULL when no change is pending.';

COMMENT ON COLUMN public.company_subscriptions.plan_change_effective_at IS
    'UTC timestamp when the pending plan change should be processed.';

COMMENT ON COLUMN public.company_subscriptions.cancellation_scheduled_at IS
    'UTC timestamp when cancellation was requested.';

COMMENT ON COLUMN public.company_subscriptions.cancellation_effective_at IS
    'UTC timestamp when cancellation takes effect, normally current_period_end.';

COMMENT ON COLUMN public.company_subscriptions.cancelled_at IS
    'UTC timestamp when cancellation was applied.';

COMMENT ON COLUMN public.company_subscriptions.status_updated_at IS
    'UTC timestamp of the most recent subscription status change.';