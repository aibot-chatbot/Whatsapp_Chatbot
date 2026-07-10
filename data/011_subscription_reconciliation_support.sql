-- 011_subscription_reconciliation_support.sql
-- Adds activation-state tracking and reconciliation fields to
-- company_subscription_orders.
--
-- Must be applied after:
--   007_subscription_lifecycle_support.sql
--   008_subscription_renewal_support.sql
--   009_subscription_activation_atomicity.sql
--   010_subscription_order_schema_version.sql

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS activation_status TEXT;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS activation_error_code TEXT;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS activation_error_message TEXT;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS activation_claimed_at TIMESTAMPTZ;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS activation_completed_at TIMESTAMPTZ;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS credit_granted_at TIMESTAMPTZ;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS reconciliation_required BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS reconciliation_attempt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS last_reconciliation_at TIMESTAMPTZ;

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS last_reconciliation_error TEXT;

ALTER TABLE public.company_subscription_orders
    DROP CONSTRAINT IF EXISTS cso_activation_status_check;

ALTER TABLE public.company_subscription_orders
    ADD CONSTRAINT cso_activation_status_check
    CHECK (
        activation_status IS NULL
        OR activation_status IN (
            'not_started',
            'claimed',
            'activated',
            'credit_pending',
            'completed',
            'conflict',
            'failed'
        )
    );

CREATE INDEX IF NOT EXISTS idx_cso_reconciliation_required
    ON public.company_subscription_orders (reconciliation_required)
    WHERE reconciliation_required = TRUE;

CREATE INDEX IF NOT EXISTS idx_cso_status_activation_status
    ON public.company_subscription_orders (status, activation_status);

CREATE INDEX IF NOT EXISTS idx_cso_paid_not_completed
    ON public.company_subscription_orders (status, activation_status)
    WHERE status = 'paid'
      AND activation_status IS DISTINCT FROM 'completed';

GRANT SELECT, INSERT, UPDATE, DELETE
ON public.company_subscription_orders
TO service_role;

COMMENT ON COLUMN public.company_subscription_orders.activation_status IS
    'Current activation stage: not_started, claimed, activated, credit_pending, completed, conflict, or failed.';

COMMENT ON COLUMN public.company_subscription_orders.activation_error_code IS
    'Machine-readable activation error code such as activation_already_claimed, source_subscription_changed, or credit_grant_failed.';

COMMENT ON COLUMN public.company_subscription_orders.activation_error_message IS
    'Safe human-readable activation failure description without secrets or stack traces.';

COMMENT ON COLUMN public.company_subscription_orders.activation_claimed_at IS
    'Timestamp when the activation sequence was atomically claimed.';

COMMENT ON COLUMN public.company_subscription_orders.activation_completed_at IS
    'Timestamp when the subscription update completed before credit allocation.';

COMMENT ON COLUMN public.company_subscription_orders.credit_granted_at IS
    'Timestamp when included AI credit was successfully granted.';

COMMENT ON COLUMN public.company_subscription_orders.reconciliation_required IS
    'True when the order requires automated or manual reconciliation.';

COMMENT ON COLUMN public.company_subscription_orders.reconciliation_attempt_count IS
    'Number of reconciliation attempts made for this order.';

COMMENT ON COLUMN public.company_subscription_orders.last_reconciliation_at IS
    'Timestamp of the most recent reconciliation attempt.';

COMMENT ON COLUMN public.company_subscription_orders.last_reconciliation_error IS
    'Safe error message from the most recent reconciliation attempt.';

COMMENT ON COLUMN public.company_subscription_orders.billing_period_key IS
    'Deprecated in favour of activation_sequence_key and retained for historical compatibility.';