-- 016_charge_ai_usage_credit_rpc.sql
-- AI-usage credit-charging RPC.
--
-- Authoritative definition exported from the deployed Supabase database
-- using pg_get_functiondef.

CREATE OR REPLACE FUNCTION public.charge_ai_usage_credit(
    p_ai_usage_log_id bigint,
    p_markup_basis_points integer,
    p_fx_rate_micro_myr_per_usd bigint
)
RETURNS TABLE(
    status text,
    transaction_id bigint,
    company_id bigint,
    subscription_id bigint,
    ai_usage_log_id bigint,
    provider_cost_micro_usd bigint,
    customer_charge_micro_myr bigint,
    included_used_micro_myr bigint,
    topup_used_micro_myr bigint,
    uncovered_charge_micro_myr bigint,
    included_balance_micro_myr bigint,
    topup_balance_micro_myr bigint,
    markup_basis_points integer,
    fx_rate_micro_myr_per_usd bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_usage public.ai_usage_logs%ROWTYPE;
    v_existing public.ai_credit_transactions%ROWTYPE;
    v_balance public.company_ai_credit_balances%ROWTYPE;

    v_active_subscription_id bigint;
    v_transaction_id bigint;

    v_effective_markup integer;
    v_effective_fx_rate bigint;

    v_customer_charge bigint;
    v_included_used bigint := 0;
    v_topup_used bigint := 0;
    v_uncovered_charge bigint := 0;
    v_remaining_charge bigint := 0;
BEGIN
    IF p_ai_usage_log_id IS NULL OR p_ai_usage_log_id <= 0 THEN
        RAISE EXCEPTION
            'ai_usage_log_id must be a positive integer'
            USING ERRCODE = '22023';
    END IF;

    SELECT usage_row.*
    INTO v_usage
    FROM public.ai_usage_logs AS usage_row
    WHERE usage_row.id = p_ai_usage_log_id
    FOR UPDATE;

    IF NOT FOUND THEN
        status := 'usage_not_found';
        transaction_id := NULL;
        company_id := NULL;
        subscription_id := NULL;
        ai_usage_log_id := p_ai_usage_log_id;
        provider_cost_micro_usd := NULL;
        customer_charge_micro_myr := NULL;
        included_used_micro_myr := 0;
        topup_used_micro_myr := 0;
        uncovered_charge_micro_myr := 0;
        included_balance_micro_myr := NULL;
        topup_balance_micro_myr := NULL;
        markup_basis_points := p_markup_basis_points;
        fx_rate_micro_myr_per_usd :=
            p_fx_rate_micro_myr_per_usd;

        RETURN NEXT;
        RETURN;
    END IF;

    SELECT transaction_row.*
    INTO v_existing
    FROM public.ai_credit_transactions AS transaction_row
    WHERE transaction_row.ai_usage_log_id = p_ai_usage_log_id
    LIMIT 1;

    IF FOUND THEN
        status := 'already_charged';
        transaction_id := v_existing.id;
        company_id := v_existing.company_id;
        subscription_id := v_existing.subscription_id;
        ai_usage_log_id := v_existing.ai_usage_log_id;
        provider_cost_micro_usd :=
            v_existing.provider_cost_micro_usd;
        customer_charge_micro_myr :=
            v_existing.customer_charge_micro_myr;
        included_used_micro_myr :=
            GREATEST(-v_existing.included_delta_micro_myr, 0);
        topup_used_micro_myr :=
            GREATEST(-v_existing.topup_delta_micro_myr, 0);
        uncovered_charge_micro_myr :=
            v_existing.uncovered_charge_micro_myr;
        included_balance_micro_myr :=
            v_existing.included_balance_after_micro_myr;
        topup_balance_micro_myr :=
            v_existing.topup_balance_after_micro_myr;
        markup_basis_points :=
            v_existing.markup_basis_points;
        fx_rate_micro_myr_per_usd :=
            v_existing.fx_rate_micro_myr_per_usd;

        RETURN NEXT;
        RETURN;
    END IF;

    IF p_markup_basis_points IS NULL
       OR p_markup_basis_points < 0 THEN
        RAISE EXCEPTION
            'markup_basis_points must be a non-negative integer'
            USING ERRCODE = '22023';
    END IF;

    IF p_fx_rate_micro_myr_per_usd IS NULL
       OR p_fx_rate_micro_myr_per_usd <= 0 THEN
        RAISE EXCEPTION
            'fx_rate_micro_myr_per_usd must be a positive integer'
            USING ERRCODE = '22023';
    END IF;

    v_effective_markup := COALESCE(
        v_usage.billing_markup_basis_points,
        p_markup_basis_points
    );

    v_effective_fx_rate := COALESCE(
        v_usage.billing_fx_rate_micro_myr_per_usd,
        p_fx_rate_micro_myr_per_usd
    );

    UPDATE public.ai_usage_logs AS usage_row
    SET
        billing_markup_basis_points = COALESCE(
            usage_row.billing_markup_basis_points,
            p_markup_basis_points
        ),
        billing_fx_rate_micro_myr_per_usd = COALESCE(
            usage_row.billing_fx_rate_micro_myr_per_usd,
            p_fx_rate_micro_myr_per_usd
        )
    WHERE usage_row.id = p_ai_usage_log_id
    RETURNING usage_row.*
    INTO v_usage;

    SELECT subscription_row.id
    INTO v_active_subscription_id
    FROM public.company_subscriptions AS subscription_row
    WHERE subscription_row.company_id = v_usage.company_id
      AND subscription_row.status IN (
          'trialing',
          'active',
          'past_due'
      )
    ORDER BY
        CASE subscription_row.status
            WHEN 'active' THEN 1
            WHEN 'trialing' THEN 2
            WHEN 'past_due' THEN 3
            ELSE 4
        END,
        subscription_row.created_at DESC
    LIMIT 1
    FOR UPDATE;

    IF NOT FOUND THEN
        status := 'no_active_subscription';
        transaction_id := NULL;
        company_id := v_usage.company_id;
        subscription_id := NULL;
        ai_usage_log_id := v_usage.id;
        provider_cost_micro_usd :=
            v_usage.provider_cost_micro_usd;
        customer_charge_micro_myr := NULL;
        included_used_micro_myr := 0;
        topup_used_micro_myr := 0;
        uncovered_charge_micro_myr := 0;
        included_balance_micro_myr := NULL;
        topup_balance_micro_myr := NULL;
        markup_basis_points := v_effective_markup;
        fx_rate_micro_myr_per_usd := v_effective_fx_rate;

        RETURN NEXT;
        RETURN;
    END IF;

    IF v_usage.provider_cost_micro_usd IS NULL THEN
        status := 'unknown_cost';
        transaction_id := NULL;
        company_id := v_usage.company_id;
        subscription_id := v_active_subscription_id;
        ai_usage_log_id := v_usage.id;
        provider_cost_micro_usd := NULL;
        customer_charge_micro_myr := NULL;
        included_used_micro_myr := 0;
        topup_used_micro_myr := 0;
        uncovered_charge_micro_myr := 0;
        included_balance_micro_myr := NULL;
        topup_balance_micro_myr := NULL;
        markup_basis_points := v_effective_markup;
        fx_rate_micro_myr_per_usd := v_effective_fx_rate;

        RETURN NEXT;
        RETURN;
    END IF;

    IF v_usage.provider_cost_micro_usd < 0 THEN
        RAISE EXCEPTION
            'AI usage log % has a negative provider cost',
            p_ai_usage_log_id
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
    FROM public.ensure_company_ai_credit_period(
        v_usage.company_id
    );

    SELECT balance_row.*
    INTO v_balance
    FROM public.company_ai_credit_balances AS balance_row
    WHERE balance_row.company_id = v_usage.company_id
    FOR UPDATE;

    IF NOT FOUND THEN
        status := 'no_balance';
        transaction_id := NULL;
        company_id := v_usage.company_id;
        subscription_id := v_active_subscription_id;
        ai_usage_log_id := v_usage.id;
        provider_cost_micro_usd :=
            v_usage.provider_cost_micro_usd;
        customer_charge_micro_myr := NULL;
        included_used_micro_myr := 0;
        topup_used_micro_myr := 0;
        uncovered_charge_micro_myr := 0;
        included_balance_micro_myr := NULL;
        topup_balance_micro_myr := NULL;
        markup_basis_points := v_effective_markup;
        fx_rate_micro_myr_per_usd := v_effective_fx_rate;

        RETURN NEXT;
        RETURN;
    END IF;

    v_customer_charge := CEIL(
        (
            v_usage.provider_cost_micro_usd::numeric
            * v_effective_fx_rate::numeric
            * (
                10000::numeric
                + v_effective_markup::numeric
            )
        )
        /
        (
            1000000::numeric
            * 10000::numeric
        )
    )::bigint;

    v_included_used := LEAST(
        v_balance.included_balance_micro_myr,
        v_customer_charge
    );

    v_remaining_charge :=
        v_customer_charge - v_included_used;

    v_topup_used := LEAST(
        v_balance.topup_balance_micro_myr,
        v_remaining_charge
    );

    v_uncovered_charge :=
        v_remaining_charge - v_topup_used;

    UPDATE public.company_ai_credit_balances AS balance_row
    SET
        included_balance_micro_myr =
            balance_row.included_balance_micro_myr
            - v_included_used,
        topup_balance_micro_myr =
            balance_row.topup_balance_micro_myr
            - v_topup_used,
        updated_at = now()
    WHERE balance_row.company_id = v_usage.company_id
    RETURNING balance_row.*
    INTO v_balance;

    INSERT INTO public.ai_credit_transactions (
        company_id,
        subscription_id,
        transaction_type,
        included_delta_micro_myr,
        topup_delta_micro_myr,
        included_balance_after_micro_myr,
        topup_balance_after_micro_myr,
        provider_cost_micro_usd,
        customer_charge_micro_myr,
        uncovered_charge_micro_myr,
        markup_basis_points,
        fx_rate_micro_myr_per_usd,
        ai_usage_log_id,
        idempotency_key,
        period_start,
        period_end,
        description
    )
    VALUES (
        v_usage.company_id,
        v_balance.subscription_id,
        'usage_debit',
        -v_included_used,
        -v_topup_used,
        v_balance.included_balance_micro_myr,
        v_balance.topup_balance_micro_myr,
        v_usage.provider_cost_micro_usd,
        v_customer_charge,
        v_uncovered_charge,
        v_effective_markup,
        v_effective_fx_rate,
        v_usage.id,
        format(
            'ai-usage-debit:%s',
            v_usage.id
        ),
        v_balance.period_start,
        v_balance.period_end,
        'AI usage credit charge in MYR'
    )
    RETURNING id
    INTO v_transaction_id;

    status := 'charged';
    transaction_id := v_transaction_id;
    company_id := v_usage.company_id;
    subscription_id := v_balance.subscription_id;
    ai_usage_log_id := v_usage.id;
    provider_cost_micro_usd :=
        v_usage.provider_cost_micro_usd;
    customer_charge_micro_myr :=
        v_customer_charge;
    included_used_micro_myr :=
        v_included_used;
    topup_used_micro_myr :=
        v_topup_used;
    uncovered_charge_micro_myr :=
        v_uncovered_charge;
    included_balance_micro_myr :=
        v_balance.included_balance_micro_myr;
    topup_balance_micro_myr :=
        v_balance.topup_balance_micro_myr;
    markup_basis_points :=
        v_effective_markup;
    fx_rate_micro_myr_per_usd :=
        v_effective_fx_rate;

    RETURN NEXT;
END;
$function$;

REVOKE ALL
ON FUNCTION public.charge_ai_usage_credit(bigint, integer, bigint)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.charge_ai_usage_credit(bigint, integer, bigint)
TO service_role;

COMMENT ON FUNCTION public.charge_ai_usage_credit(bigint, integer, bigint) IS
    'Atomically charges AI usage against a company credit balance. Deducts included balance first, then top-up balance.';