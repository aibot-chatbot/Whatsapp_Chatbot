-- 013_subscription_included_credit_rpc.sql

CREATE OR REPLACE FUNCTION public.allocate_subscription_included_credit(
    p_company_id BIGINT,
    p_amount_micro_myr BIGINT,
    p_idempotency_key TEXT,
    p_payment_reference TEXT,
    p_period_start TIMESTAMPTZ,
    p_period_end TIMESTAMPTZ,
    p_plan_code TEXT DEFAULT NULL,
    p_description TEXT DEFAULT NULL
)
RETURNS TABLE(
    status TEXT,
    transaction_id BIGINT,
    company_id BIGINT,
    amount_micro_myr BIGINT,
    included_balance_micro_myr BIGINT,
    topup_balance_micro_myr BIGINT,
    total_balance_micro_myr BIGINT,
    payment_reference TEXT,
    idempotency_key TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_existing_id BIGINT;
    v_txn_id BIGINT;
    v_included_before BIGINT;
    v_topup_before BIGINT;
    v_period_start TIMESTAMPTZ;
    v_period_end TIMESTAMPTZ;
BEGIN
    IF p_amount_micro_myr IS NULL OR p_amount_micro_myr <= 0 THEN
        RAISE EXCEPTION 'Included credit amount must be positive';
    END IF;

    IF p_idempotency_key IS NULL OR BTRIM(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'Idempotency key is required';
    END IF;

    IF p_period_start IS NULL
       OR p_period_end IS NULL
       OR p_period_end <= p_period_start THEN
        RAISE EXCEPTION 'A valid subscription period is required';
    END IF;

    SELECT t.id
    INTO v_existing_id
    FROM public.ai_credit_transactions t
    WHERE t.idempotency_key = p_idempotency_key
      AND t.company_id = p_company_id
    LIMIT 1;

    IF v_existing_id IS NOT NULL THEN
        RETURN QUERY
        SELECT
            'already_applied'::TEXT,
            v_existing_id,
            p_company_id,
            p_amount_micro_myr,
            COALESCE(b.included_balance_micro_myr, 0),
            COALESCE(b.topup_balance_micro_myr, 0),
            COALESCE(b.included_balance_micro_myr, 0)
                + COALESCE(b.topup_balance_micro_myr, 0),
            p_payment_reference,
            p_idempotency_key
        FROM public.company_ai_credit_balances b
        WHERE b.company_id = p_company_id;

        RETURN;
    END IF;

    INSERT INTO public.company_ai_credit_balances (
        company_id,
        included_balance_micro_myr,
        topup_balance_micro_myr
    )
    VALUES (
        p_company_id,
        0,
        0
    )
    ON CONFLICT (company_id) DO NOTHING;

    SELECT
        COALESCE(b.included_balance_micro_myr, 0),
        COALESCE(b.topup_balance_micro_myr, 0),
        b.period_start,
        b.period_end
    INTO
        v_included_before,
        v_topup_before,
        v_period_start,
        v_period_end
    FROM public.company_ai_credit_balances b
    WHERE b.company_id = p_company_id
    FOR UPDATE;

    UPDATE public.company_ai_credit_balances
    SET
        included_balance_micro_myr =
            COALESCE(included_balance_micro_myr, 0)
            + p_amount_micro_myr,
        period_start = p_period_start,
        period_end = p_period_end,
        updated_at = NOW()
    WHERE company_id = p_company_id;

    INSERT INTO public.ai_credit_transactions (
        company_id,
        transaction_type,
        included_delta_micro_myr,
        topup_delta_micro_myr,
        included_balance_after_micro_myr,
        topup_balance_after_micro_myr,
        description,
        payment_reference,
        idempotency_key,
        period_start,
        period_end
    )
    VALUES (
        p_company_id,
        'subscription_included',
        p_amount_micro_myr,
        0,
        v_included_before + p_amount_micro_myr,
        v_topup_before,
        COALESCE(
            p_description,
            'Subscription '
                || COALESCE(p_plan_code, 'plan')
                || ' included AI credit'
        ),
        p_payment_reference,
        p_idempotency_key,
        p_period_start,
        p_period_end
    )
    RETURNING id INTO v_txn_id;

    RETURN QUERY
    SELECT
        'applied'::TEXT,
        v_txn_id,
        p_company_id,
        p_amount_micro_myr,
        v_included_before + p_amount_micro_myr,
        v_topup_before,
        v_included_before + p_amount_micro_myr + v_topup_before,
        p_payment_reference,
        p_idempotency_key;
END;
$$;

REVOKE ALL
ON FUNCTION public.allocate_subscription_included_credit(
    BIGINT,
    BIGINT,
    TEXT,
    TEXT,
    TIMESTAMPTZ,
    TIMESTAMPTZ,
    TEXT,
    TEXT
)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.allocate_subscription_included_credit(
    BIGINT,
    BIGINT,
    TEXT,
    TEXT,
    TIMESTAMPTZ,
    TIMESTAMPTZ,
    TEXT,
    TEXT
)
TO service_role;

COMMENT ON FUNCTION public.allocate_subscription_included_credit(
    BIGINT,
    BIGINT,
    TEXT,
    TEXT,
    TIMESTAMPTZ,
    TIMESTAMPTZ,
    TEXT,
    TEXT
) IS
    'Atomically allocates subscription included AI credit to the included balance bucket while preserving top-up credit.';