-- 018_ai_credit_topup_checkout_rpcs.sql
-- AI-credit top-up checkout RPCs (claim, complete, fail).
--
-- Authoritative definitions exported from the deployed Supabase database
-- using pg_get_functiondef.
-- All order_reference and claim_token parameters are UUID, not TEXT.

-- ============================================================
-- claim_ai_credit_topup_checkout
-- ============================================================

CREATE OR REPLACE FUNCTION public.claim_ai_credit_topup_checkout(
    p_order_reference uuid,
    p_claim_token uuid,
    p_claim_timeout_seconds integer DEFAULT 300
)
RETURNS TABLE(
    claimed boolean,
    reason text,
    order_id bigint,
    returned_order_reference uuid,
    order_status text,
    returned_gateway_order_id text,
    returned_checkout_url text,
    active_claim_token uuid,
    claimed_at timestamp with time zone
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_order public.ai_credit_topup_orders%ROWTYPE;
BEGIN
    IF p_order_reference IS NULL THEN
        RAISE EXCEPTION 'Order reference is required';
    END IF;

    IF p_claim_token IS NULL THEN
        RAISE EXCEPTION 'Claim token is required';
    END IF;

    IF p_claim_timeout_seconds < 30
       OR p_claim_timeout_seconds > 3600 THEN
        RAISE EXCEPTION
            'Claim timeout must be between 30 and 3600 seconds';
    END IF;

    SELECT *
    INTO v_order
    FROM public.ai_credit_topup_orders
    WHERE order_reference = p_order_reference
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Top-up order not found';
    END IF;

    IF v_order.status <> 'pending' THEN
        RETURN QUERY
        SELECT
            false,
            'invalid_status'::text,
            v_order.id,
            v_order.order_reference,
            v_order.status,
            v_order.gateway_order_id,
            v_order.checkout_url,
            v_order.checkout_claim_token,
            v_order.checkout_claimed_at;
        RETURN;
    END IF;

    IF v_order.gateway_order_id IS NOT NULL
       AND v_order.checkout_url IS NOT NULL THEN
        RETURN QUERY
        SELECT
            false,
            'checkout_exists'::text,
            v_order.id,
            v_order.order_reference,
            v_order.status,
            v_order.gateway_order_id,
            v_order.checkout_url,
            v_order.checkout_claim_token,
            v_order.checkout_claimed_at;
        RETURN;
    END IF;

    IF v_order.checkout_claim_token = p_claim_token THEN
        RETURN QUERY
        SELECT
            true,
            'already_claimed_by_caller'::text,
            v_order.id,
            v_order.order_reference,
            v_order.status,
            v_order.gateway_order_id,
            v_order.checkout_url,
            v_order.checkout_claim_token,
            v_order.checkout_claimed_at;
        RETURN;
    END IF;

    IF v_order.checkout_claim_token IS NULL
       OR v_order.checkout_claimed_at <
          now() - make_interval(secs => p_claim_timeout_seconds) THEN

        UPDATE public.ai_credit_topup_orders
        SET
            checkout_claim_token = p_claim_token,
            checkout_claimed_at = now(),
            updated_at = now()
        WHERE id = v_order.id
        RETURNING *
        INTO v_order;

        RETURN QUERY
        SELECT
            true,
            'claimed'::text,
            v_order.id,
            v_order.order_reference,
            v_order.status,
            v_order.gateway_order_id,
            v_order.checkout_url,
            v_order.checkout_claim_token,
            v_order.checkout_claimed_at;
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        false,
        'checkout_in_progress'::text,
        v_order.id,
        v_order.order_reference,
        v_order.status,
        v_order.gateway_order_id,
        v_order.checkout_url,
        v_order.checkout_claim_token,
        v_order.checkout_claimed_at;
END;
$function$;

REVOKE ALL
ON FUNCTION public.claim_ai_credit_topup_checkout(
    uuid,
    uuid,
    integer
)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.claim_ai_credit_topup_checkout(
    uuid,
    uuid,
    integer
)
TO service_role;

COMMENT ON FUNCTION public.claim_ai_credit_topup_checkout(
    uuid,
    uuid,
    integer
) IS
    'Claims a top-up checkout for creation. Returns whether the claim was granted and the current order state.';

-- ============================================================
-- complete_ai_credit_topup_checkout
-- ============================================================

CREATE OR REPLACE FUNCTION public.complete_ai_credit_topup_checkout(
    p_order_reference uuid,
    p_claim_token uuid,
    p_gateway_order_id text,
    p_checkout_url text,
    p_expires_at timestamp with time zone DEFAULT NULL::timestamp with time zone
)
RETURNS SETOF public.ai_credit_topup_orders
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_order public.ai_credit_topup_orders%ROWTYPE;
BEGIN
    IF p_order_reference IS NULL OR p_claim_token IS NULL THEN
        RAISE EXCEPTION
            'Order reference and claim token are required';
    END IF;

    IF NULLIF(trim(p_gateway_order_id), '') IS NULL THEN
        RAISE EXCEPTION 'Gateway order ID is required';
    END IF;

    IF NULLIF(trim(p_checkout_url), '') IS NULL THEN
        RAISE EXCEPTION 'Checkout URL is required';
    END IF;

    SELECT *
    INTO v_order
    FROM public.ai_credit_topup_orders
    WHERE order_reference = p_order_reference
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Top-up order not found';
    END IF;

    IF v_order.gateway_order_id IS NOT NULL
       OR v_order.checkout_url IS NOT NULL THEN

        IF v_order.gateway_order_id = trim(p_gateway_order_id)
           AND v_order.checkout_url = trim(p_checkout_url) THEN
            RETURN NEXT v_order;
            RETURN;
        END IF;

        RAISE EXCEPTION 'Conflicting gateway checkout details';
    END IF;

    IF v_order.status <> 'pending' THEN
        RAISE EXCEPTION
            'Only pending orders can complete checkout creation';
    END IF;

    IF v_order.checkout_claim_token IS DISTINCT FROM p_claim_token THEN
        RAISE EXCEPTION
            'Checkout claim is not owned by this caller';
    END IF;

    UPDATE public.ai_credit_topup_orders
    SET
        gateway_order_id = trim(p_gateway_order_id),
        checkout_url = trim(p_checkout_url),
        expires_at = COALESCE(p_expires_at, expires_at),
        checkout_claim_token = NULL,
        checkout_claimed_at = NULL,
        updated_at = now()
    WHERE id = v_order.id
    RETURNING *
    INTO v_order;

    RETURN NEXT v_order;
END;
$function$;

REVOKE ALL
ON FUNCTION public.complete_ai_credit_topup_checkout(
    uuid,
    uuid,
    text,
    text,
    timestamp with time zone
)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.complete_ai_credit_topup_checkout(
    uuid,
    uuid,
    text,
    text,
    timestamp with time zone
)
TO service_role;

COMMENT ON FUNCTION public.complete_ai_credit_topup_checkout(
    uuid,
    uuid,
    text,
    text,
    timestamp with time zone
) IS
    'Completes top-up checkout creation by storing the gateway order ID and checkout URL. Idempotent for identical gateway details.';

-- ============================================================
-- fail_ai_credit_topup_checkout
-- ============================================================

CREATE OR REPLACE FUNCTION public.fail_ai_credit_topup_checkout(
    p_order_reference uuid,
    p_claim_token uuid,
    p_failure_reason text DEFAULT NULL::text
)
RETURNS SETOF public.ai_credit_topup_orders
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_order public.ai_credit_topup_orders%ROWTYPE;
BEGIN
    IF p_order_reference IS NULL OR p_claim_token IS NULL THEN
        RAISE EXCEPTION
            'Order reference and claim token are required';
    END IF;

    SELECT *
    INTO v_order
    FROM public.ai_credit_topup_orders
    WHERE order_reference = p_order_reference
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Top-up order not found';
    END IF;

    IF v_order.status = 'failed' THEN
        RETURN NEXT v_order;
        RETURN;
    END IF;

    IF v_order.status <> 'pending' THEN
        RAISE EXCEPTION
            'Only pending orders can be marked failed';
    END IF;

    IF v_order.checkout_claim_token IS DISTINCT FROM p_claim_token THEN
        RAISE EXCEPTION
            'Checkout claim is not owned by this caller';
    END IF;

    UPDATE public.ai_credit_topup_orders
    SET
        status = 'failed',
        failed_at = now(),
        failure_reason = left(
            COALESCE(
                NULLIF(trim(p_failure_reason), ''),
                'Checkout creation failed'
            ),
            500
        ),
        checkout_claim_token = NULL,
        checkout_claimed_at = NULL,
        updated_at = now()
    WHERE id = v_order.id
    RETURNING *
    INTO v_order;

    RETURN NEXT v_order;
END;
$function$;

REVOKE ALL
ON FUNCTION public.fail_ai_credit_topup_checkout(
    uuid,
    uuid,
    text
)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.fail_ai_credit_topup_checkout(
    uuid,
    uuid,
    text
)
TO service_role;

COMMENT ON FUNCTION public.fail_ai_credit_topup_checkout(
    uuid,
    uuid,
    text
) IS
    'Marks a top-up checkout creation as failed. Idempotent; re-calling with an already-failed order returns the order as-is.';