-- 017_add_ai_credit_topup_rpc.sql
-- AI-credit top-up RPC.
--
-- Authoritative definition exported from the deployed Supabase database
-- using pg_get_functiondef.

CREATE OR REPLACE FUNCTION public.add_ai_credit_topup(
    p_company_id bigint,
    p_amount_micro_myr bigint,
    p_idempotency_key text,
    p_payment_reference text,
    p_description text DEFAULT NULL::text
)
RETURNS TABLE(
    status text,
    transaction_id bigint,
    company_id bigint,
    subscription_id bigint,
    amount_micro_myr bigint,
    included_balance_micro_myr bigint,
    topup_balance_micro_myr bigint,
    total_balance_micro_myr bigint,
    payment_reference text,
    idempotency_key text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_balance public.company_ai_credit_balances%ROWTYPE;
    v_existing public.ai_credit_transactions%ROWTYPE;

    v_transaction_id bigint;
    v_new_topup_balance bigint;

    v_idempotency_key text;
    v_payment_reference text;
    v_description text;
BEGIN
    IF p_company_id IS NULL OR p_company_id <= 0 THEN
        RAISE EXCEPTION
            'company_id must be a positive integer'
            USING ERRCODE = '22023';
    END IF;

    IF p_amount_micro_myr IS NULL OR p_amount_micro_myr <= 0 THEN
        RAISE EXCEPTION
            'amount_micro_myr must be a positive integer'
            USING ERRCODE = '22023';
    END IF;

    v_idempotency_key := NULLIF(BTRIM(p_idempotency_key), '');
    v_payment_reference := NULLIF(BTRIM(p_payment_reference), '');
    v_description := COALESCE(
        NULLIF(BTRIM(p_description), ''),
        'AI credit top-up purchase'
    );

    IF v_idempotency_key IS NULL THEN
        RAISE EXCEPTION
            'idempotency_key is required'
            USING ERRCODE = '22023';
    END IF;

    IF v_payment_reference IS NULL THEN
        RAISE EXCEPTION
            'payment_reference is required'
            USING ERRCODE = '22023';
    END IF;

    PERFORM 1
    FROM public.ensure_company_ai_credit_period(p_company_id);

    SELECT balance_row.*
    INTO v_balance
    FROM public.company_ai_credit_balances AS balance_row
    WHERE balance_row.company_id = p_company_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'AI-credit balance not found for company %',
            p_company_id
            USING ERRCODE = 'P0002';
    END IF;

    SELECT transaction_row.*
    INTO v_existing
    FROM public.ai_credit_transactions AS transaction_row
    WHERE transaction_row.idempotency_key = v_idempotency_key
    LIMIT 1;

    IF FOUND THEN
        IF v_existing.company_id <> p_company_id
           OR v_existing.transaction_type <> 'topup_purchase'
           OR v_existing.topup_delta_micro_myr <> p_amount_micro_myr
           OR v_existing.payment_reference IS DISTINCT FROM
                v_payment_reference
        THEN
            RAISE EXCEPTION
                'Idempotency key is already used for a different transaction'
                USING ERRCODE = '23505';
        END IF;

        RETURN QUERY
        SELECT
            'already_applied'::text,
            v_existing.id,
            v_balance.company_id,
            v_balance.subscription_id,
            v_existing.topup_delta_micro_myr,
            v_balance.included_balance_micro_myr,
            v_balance.topup_balance_micro_myr,
            v_balance.included_balance_micro_myr
                + v_balance.topup_balance_micro_myr,
            v_existing.payment_reference,
            v_existing.idempotency_key;

        RETURN;
    END IF;

    SELECT transaction_row.*
    INTO v_existing
    FROM public.ai_credit_transactions AS transaction_row
    WHERE transaction_row.transaction_type = 'topup_purchase'
      AND transaction_row.payment_reference = v_payment_reference
    LIMIT 1;

    IF FOUND THEN
        IF v_existing.company_id <> p_company_id
           OR v_existing.topup_delta_micro_myr <> p_amount_micro_myr
        THEN
            RAISE EXCEPTION
                'Payment reference is already used for a different transaction'
                USING ERRCODE = '23505';
        END IF;

        RETURN QUERY
        SELECT
            'already_applied'::text,
            v_existing.id,
            v_balance.company_id,
            v_balance.subscription_id,
            v_existing.topup_delta_micro_myr,
            v_balance.included_balance_micro_myr,
            v_balance.topup_balance_micro_myr,
            v_balance.included_balance_micro_myr
                + v_balance.topup_balance_micro_myr,
            v_existing.payment_reference,
            v_existing.idempotency_key;

        RETURN;
    END IF;

    v_new_topup_balance :=
        v_balance.topup_balance_micro_myr + p_amount_micro_myr;

    INSERT INTO public.ai_credit_transactions (
        company_id,
        subscription_id,
        transaction_type,
        included_delta_micro_myr,
        topup_delta_micro_myr,
        included_balance_after_micro_myr,
        topup_balance_after_micro_myr,
        payment_reference,
        idempotency_key,
        period_start,
        period_end,
        description
    )
    VALUES (
        p_company_id,
        v_balance.subscription_id,
        'topup_purchase',
        0,
        p_amount_micro_myr,
        v_balance.included_balance_micro_myr,
        v_new_topup_balance,
        v_payment_reference,
        v_idempotency_key,
        v_balance.period_start,
        v_balance.period_end,
        v_description
    )
    RETURNING id
    INTO v_transaction_id;

    UPDATE public.company_ai_credit_balances
    SET
        topup_balance_micro_myr = v_new_topup_balance,
        updated_at = NOW()
    WHERE company_ai_credit_balances.company_id = p_company_id
    RETURNING *
    INTO v_balance;

    RETURN QUERY
    SELECT
        'applied'::text,
        v_transaction_id,
        v_balance.company_id,
        v_balance.subscription_id,
        p_amount_micro_myr,
        v_balance.included_balance_micro_myr,
        v_balance.topup_balance_micro_myr,
        v_balance.included_balance_micro_myr
            + v_balance.topup_balance_micro_myr,
        v_payment_reference,
        v_idempotency_key;
END;
$function$;

REVOKE ALL
ON FUNCTION public.add_ai_credit_topup(
    bigint,
    bigint,
    text,
    text,
    text
)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.add_ai_credit_topup(
    bigint,
    bigint,
    text,
    text,
    text
)
TO service_role;

COMMENT ON FUNCTION public.add_ai_credit_topup(
    bigint,
    bigint,
    text,
    text,
    text
) IS
    'Atomically adds top-up AI credit to the top-up balance bucket while preserving included credit.';