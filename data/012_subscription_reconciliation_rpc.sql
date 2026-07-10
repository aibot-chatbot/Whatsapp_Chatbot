-- 012_subscription_reconciliation_rpc.sql
-- Adds atomic reconciliation RPC functions.
--
-- Must be applied after:
--   011_subscription_reconciliation_support.sql

CREATE OR REPLACE FUNCTION public.increment_subscription_reconciliation_attempt(
    p_order_reference UUID,
    p_last_error TEXT DEFAULT NULL
)
RETURNS SETOF public.company_subscription_orders
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.company_subscription_orders
    SET
        reconciliation_attempt_count =
            COALESCE(reconciliation_attempt_count, 0) + 1,
        last_reconciliation_at = NOW(),
        last_reconciliation_error =
            COALESCE(p_last_error, last_reconciliation_error),
        updated_at = NOW()
    WHERE order_reference = p_order_reference
    RETURNING *;
END;
$$;

REVOKE ALL
ON FUNCTION public.increment_subscription_reconciliation_attempt(UUID, TEXT)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.increment_subscription_reconciliation_attempt(UUID, TEXT)
TO service_role;

COMMENT ON FUNCTION public.increment_subscription_reconciliation_attempt(UUID, TEXT) IS
    'Atomically increments reconciliation_attempt_count and updates reconciliation metadata for an order.';


CREATE OR REPLACE FUNCTION public.update_subscription_order_activation_state_rpc(
    p_order_reference UUID,
    p_activation_status TEXT DEFAULT NULL,
    p_activation_error_code TEXT DEFAULT NULL,
    p_activation_error_message TEXT DEFAULT NULL,
    p_reconciliation_required BOOLEAN DEFAULT NULL
)
RETURNS SETOF public.company_subscription_orders
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.company_subscription_orders
    SET
        activation_status =
            COALESCE(p_activation_status, activation_status),

        activation_error_code =
            CASE
                WHEN p_activation_error_code IS NOT NULL
                    THEN p_activation_error_code
                ELSE activation_error_code
            END,

        activation_error_message =
            CASE
                WHEN p_activation_error_message IS NOT NULL
                    THEN p_activation_error_message
                ELSE activation_error_message
            END,

        activation_claimed_at =
            CASE
                WHEN p_activation_status = 'claimed'
                     AND activation_claimed_at IS NULL
                    THEN NOW()
                ELSE activation_claimed_at
            END,

        activation_completed_at =
            CASE
                WHEN p_activation_status = 'activated'
                     AND activation_completed_at IS NULL
                    THEN NOW()
                ELSE activation_completed_at
            END,

        credit_granted_at =
            CASE
                WHEN p_activation_status = 'completed'
                     AND credit_granted_at IS NULL
                    THEN NOW()
                ELSE credit_granted_at
            END,

        reconciliation_required =
            COALESCE(
                p_reconciliation_required,
                reconciliation_required
            ),

        updated_at = NOW()

    WHERE order_reference = p_order_reference
    RETURNING *;
END;
$$;

REVOKE ALL
ON FUNCTION public.update_subscription_order_activation_state_rpc(
    UUID,
    TEXT,
    TEXT,
    TEXT,
    BOOLEAN
)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.update_subscription_order_activation_state_rpc(
    UUID,
    TEXT,
    TEXT,
    TEXT,
    BOOLEAN
)
TO service_role;

COMMENT ON FUNCTION public.update_subscription_order_activation_state_rpc(
    UUID,
    TEXT,
    TEXT,
    TEXT,
    BOOLEAN
) IS
    'Atomically updates activation-state and reconciliation fields for a subscription order.';