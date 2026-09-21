-- PROPOSAL: apply before enabling CHIP; not applied by this coding task.
-- Adds provider-mode binding. Historical payment rows and RPC/RLS stay intact.
BEGIN;
ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS gateway_environment text,
    ADD COLUMN IF NOT EXISTS gateway_brand_id uuid,
    ADD COLUMN IF NOT EXISTS currency text NOT NULL DEFAULT 'MYR';
ALTER TABLE public.ai_credit_topup_orders
    ADD COLUMN IF NOT EXISTS gateway_environment text,
    ADD COLUMN IF NOT EXISTS gateway_brand_id uuid;
-- NULL is valid for historical providers and not-yet-claimed top-ups.
ALTER TABLE public.company_subscription_orders
    ADD CONSTRAINT cso_chip_environment_check CHECK (
        payment_gateway IS DISTINCT FROM 'chip' OR
        (gateway_environment IS NOT NULL AND gateway_environment IN ('test', 'live')
         AND gateway_brand_id IS NOT NULL AND currency = 'MYR')
    );
ALTER TABLE public.ai_credit_topup_orders
    ADD CONSTRAINT topup_chip_environment_check CHECK (
        payment_gateway IS DISTINCT FROM 'chip' OR gateway_order_id IS NULL OR
        (gateway_environment IS NOT NULL AND gateway_environment IN ('test', 'live')
         AND gateway_brand_id IS NOT NULL AND currency = 'MYR')
    );
CREATE INDEX IF NOT EXISTS ix_cso_pending_chip
    ON public.company_subscription_orders (updated_at, id)
    WHERE status = 'pending' AND payment_gateway = 'chip';
CREATE INDEX IF NOT EXISTS ix_topup_pending_chip
    ON public.ai_credit_topup_orders (updated_at, id)
    WHERE status IN ('pending', 'paid') AND payment_gateway = 'chip';
COMMIT;
