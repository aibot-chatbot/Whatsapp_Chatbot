-- 015_ensure_company_ai_credit_period_rpc.sql
-- AI-credit period initialisation RPC.
--
-- Authoritative definition exported from the deployed Supabase database
-- using pg_get_functiondef.

CREATE OR REPLACE FUNCTION public.ensure_company_ai_credit_period(
    p_company_id bigint
)
RETURNS TABLE(
    company_id bigint,
    subscription_id bigint,
    period_start timestamp with time zone,
    period_end timestamp with time zone,
    included_balance_micro_myr bigint,
    topup_balance_micro_myr bigint,
    included_credit_granted_micro_myr bigint,
    period_changed boolean,
    transaction_id bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_subscription record;
    v_balance public.company_ai_credit_balances%ROWTYPE;

    v_period_end timestamp with time zone;
    v_grant_amount bigint;

    v_previous_included_balance bigint := 0;
    v_transaction_id bigint := NULL;
    v_period_changed boolean := false;

    v_grant_idempotency_key text;
    v_expiry_idempotency_key text;
BEGIN
    IF p_company_id IS NULL OR p_company_id <= 0 THEN
        RAISE EXCEPTION
            'company_id must be a positive integer'
            USING ERRCODE = '22023';
    END IF;

    SELECT
        cs.id AS subscription_id,
        cs.company_id,
        cs.current_period_start,
        cs.current_period_end,
        cs.created_at,
        sp.included_ai_credit_micro_myr
    INTO v_subscription
    FROM public.company_subscriptions AS cs
    JOIN public.subscription_plans AS sp
        ON sp.id = cs.plan_id
    WHERE cs.company_id = p_company_id
      AND cs.status IN ('trialing', 'active', 'past_due')
    ORDER BY
        CASE cs.status
            WHEN 'active' THEN 1
            WHEN 'trialing' THEN 2
            WHEN 'past_due' THEN 3
            ELSE 4
        END,
        cs.created_at DESC
    LIMIT 1
    FOR UPDATE OF cs;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'No active, trialing, or past-due subscription found for company %',
            p_company_id
            USING ERRCODE = 'P0002';
    END IF;

    IF v_subscription.current_period_start IS NULL THEN
        RAISE EXCEPTION
            'Subscription % has no current period start',
            v_subscription.subscription_id
            USING ERRCODE = '23502';
    END IF;

    v_period_end := COALESCE(
        v_subscription.current_period_end,
        v_subscription.current_period_start + INTERVAL '1 month'
    );

    IF v_period_end <= v_subscription.current_period_start THEN
        RAISE EXCEPTION
            'Subscription % has an invalid credit period',
            v_subscription.subscription_id
            USING ERRCODE = '22007';
    END IF;

    v_grant_amount := COALESCE(
        v_subscription.included_ai_credit_micro_myr,
        0
    );

    IF v_grant_amount < 0 THEN
        RAISE EXCEPTION
            'Subscription % has a negative included AI-credit amount',
            v_subscription.subscription_id
            USING ERRCODE = '23514';
    END IF;

    SELECT balance_row.*
    INTO v_balance
    FROM public.company_ai_credit_balances AS balance_row
    WHERE balance_row.company_id = p_company_id
    FOR UPDATE;

    IF NOT FOUND THEN
        INSERT INTO public.company_ai_credit_balances (
            company_id,
            subscription_id,
            period_start,
            period_end,
            included_balance_micro_myr,
            topup_balance_micro_myr
        )
        VALUES (
            p_company_id,
            v_subscription.subscription_id,
            v_subscription.current_period_start,
            v_period_end,
            v_grant_amount,
            0
        )
        RETURNING *
        INTO v_balance;

        v_period_changed := true;

        IF v_grant_amount > 0 THEN
            v_grant_idempotency_key := format(
                'included-credit-grant:%s:%s',
                v_subscription.subscription_id,
                v_subscription.current_period_start
            );

            INSERT INTO public.ai_credit_transactions (
                company_id,
                subscription_id,
                transaction_type,
                included_delta_micro_myr,
                topup_delta_micro_myr,
                included_balance_after_micro_myr,
                topup_balance_after_micro_myr,
                idempotency_key,
                period_start,
                period_end,
                description
            )
            VALUES (
                p_company_id,
                v_subscription.subscription_id,
                'included_credit_grant',
                v_grant_amount,
                0,
                v_balance.included_balance_micro_myr,
                v_balance.topup_balance_micro_myr,
                v_grant_idempotency_key,
                v_subscription.current_period_start,
                v_period_end,
                'Initial included AI credit for the subscription period'
            )
            ON CONFLICT (idempotency_key)
            DO NOTHING
            RETURNING id
            INTO v_transaction_id;

            IF v_transaction_id IS NULL THEN
                SELECT transaction_row.id
                INTO v_transaction_id
                FROM public.ai_credit_transactions AS transaction_row
                WHERE transaction_row.idempotency_key =
                    v_grant_idempotency_key
                LIMIT 1;
            END IF;
        END IF;

    ELSIF
        v_balance.subscription_id IS DISTINCT FROM
            v_subscription.subscription_id
        OR v_balance.period_start IS DISTINCT FROM
            v_subscription.current_period_start
    THEN
        v_previous_included_balance :=
            v_balance.included_balance_micro_myr;

        IF v_previous_included_balance > 0 THEN
            v_expiry_idempotency_key := format(
                'included-credit-expiry:%s:%s',
                p_company_id,
                v_balance.period_start
            );

            INSERT INTO public.ai_credit_transactions (
                company_id,
                subscription_id,
                transaction_type,
                included_delta_micro_myr,
                topup_delta_micro_myr,
                included_balance_after_micro_myr,
                topup_balance_after_micro_myr,
                idempotency_key,
                period_start,
                period_end,
                description
            )
            VALUES (
                p_company_id,
                v_balance.subscription_id,
                'expiry',
                -v_previous_included_balance,
                0,
                0,
                v_balance.topup_balance_micro_myr,
                v_expiry_idempotency_key,
                v_balance.period_start,
                v_balance.period_end,
                'Unused included AI credit expired at period change'
            )
            ON CONFLICT (idempotency_key)
            DO NOTHING;
        END IF;

        UPDATE public.company_ai_credit_balances
        SET
            subscription_id = v_subscription.subscription_id,
            period_start = v_subscription.current_period_start,
            period_end = v_period_end,
            included_balance_micro_myr = v_grant_amount,
            updated_at = now()
        WHERE company_ai_credit_balances.company_id = p_company_id
        RETURNING *
        INTO v_balance;

        v_period_changed := true;

        IF v_grant_amount > 0 THEN
            v_grant_idempotency_key := format(
                'included-credit-grant:%s:%s',
                v_subscription.subscription_id,
                v_subscription.current_period_start
            );

            INSERT INTO public.ai_credit_transactions (
                company_id,
                subscription_id,
                transaction_type,
                included_delta_micro_myr,
                topup_delta_micro_myr,
                included_balance_after_micro_myr,
                topup_balance_after_micro_myr,
                idempotency_key,
                period_start,
                period_end,
                description
            )
            VALUES (
                p_company_id,
                v_subscription.subscription_id,
                'included_credit_grant',
                v_grant_amount,
                0,
                v_balance.included_balance_micro_myr,
                v_balance.topup_balance_micro_myr,
                v_grant_idempotency_key,
                v_subscription.current_period_start,
                v_period_end,
                'Included AI credit granted for the new subscription period'
            )
            ON CONFLICT (idempotency_key)
            DO NOTHING
            RETURNING id
            INTO v_transaction_id;

            IF v_transaction_id IS NULL THEN
                SELECT transaction_row.id
                INTO v_transaction_id
                FROM public.ai_credit_transactions AS transaction_row
                WHERE transaction_row.idempotency_key =
                    v_grant_idempotency_key
                LIMIT 1;
            END IF;
        END IF;

    ELSIF v_balance.period_end IS DISTINCT FROM v_period_end THEN
        UPDATE public.company_ai_credit_balances
        SET
            period_end = v_period_end,
            updated_at = now()
        WHERE company_ai_credit_balances.company_id = p_company_id
        RETURNING *
        INTO v_balance;
    END IF;

    RETURN QUERY
    SELECT
        v_balance.company_id,
        v_balance.subscription_id,
        v_balance.period_start,
        v_balance.period_end,
        v_balance.included_balance_micro_myr,
        v_balance.topup_balance_micro_myr,
        CASE
            WHEN v_period_changed THEN v_grant_amount
            ELSE 0
        END,
        v_period_changed,
        v_transaction_id;
END;
$function$;

REVOKE ALL
ON FUNCTION public.ensure_company_ai_credit_period(bigint)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.ensure_company_ai_credit_period(bigint)
TO service_role;

COMMENT ON FUNCTION public.ensure_company_ai_credit_period(bigint) IS
    'Initialises or renews the AI-credit period for a company. Called by charge_ai_usage_credit and add_ai_credit_topup.';