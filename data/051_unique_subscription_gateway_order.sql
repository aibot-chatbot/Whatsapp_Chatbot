-- Proposed only: do not apply without an explicit production migration approval.
-- Migration 049 belongs to automation events and is intentionally untouched.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.company_subscription_orders
        WHERE payment_gateway IS NOT NULL
          AND gateway_order_id IS NOT NULL
        GROUP BY payment_gateway, gateway_order_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Duplicate subscription gateway order IDs exist; resolve them before migration 051';
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_cso_payment_gateway_order_id
    ON public.company_subscription_orders (payment_gateway, gateway_order_id)
    WHERE payment_gateway IS NOT NULL
      AND gateway_order_id IS NOT NULL;
