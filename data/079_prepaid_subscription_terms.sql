-- Add document-approved 1, 3, 6 and 12 month prepaid subscription terms.
-- Omnexa sells Chatbot + GEO together; prices use the "Both products" table
-- in Omnexa_Pricing_Brief_2_Pages_2026-10-10.pdf.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.company_subscription_orders
  ADD COLUMN IF NOT EXISTS billing_term_months smallint NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS monthly_equivalent_sen integer NOT NULL DEFAULT 0;

ALTER TABLE public.company_subscriptions
  ADD COLUMN IF NOT EXISTS billing_term_months smallint NOT NULL DEFAULT 1;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'company_subscription_orders_term_check'
      AND conrelid = 'public.company_subscription_orders'::regclass
  ) THEN
    ALTER TABLE public.company_subscription_orders
      ADD CONSTRAINT company_subscription_orders_term_check
      CHECK (billing_term_months IN (1, 3, 6, 12));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'company_subscription_orders_monthly_equivalent_check'
      AND conrelid = 'public.company_subscription_orders'::regclass
  ) THEN
    ALTER TABLE public.company_subscription_orders
      ADD CONSTRAINT company_subscription_orders_monthly_equivalent_check
      CHECK (monthly_equivalent_sen >= 0 AND monthly_equivalent_sen <= amount_sen);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'company_subscriptions_term_check'
      AND conrelid = 'public.company_subscriptions'::regclass
  ) THEN
    ALTER TABLE public.company_subscriptions
      ADD CONSTRAINT company_subscriptions_term_check
      CHECK (billing_term_months IN (1, 3, 6, 12));
  END IF;
END;
$$;

-- One-month monthly equivalents for the bundled Chatbot + GEO product.
UPDATE public.subscription_plans SET price = 133.50, updated_at = now() WHERE lower(code) = 'essential';
UPDATE public.subscription_plans SET price = 283.50, updated_at = now() WHERE lower(code) = 'advanced';
UPDATE public.subscription_plans SET price = 561.00, updated_at = now() WHERE lower(code) = 'pro';

-- Included AI credit remains monthly even when the paid subscription term is
-- longer. This function derives the current allowance month inside the paid
-- term, expires unused included credit, and grants the next monthly allowance
-- atomically. Top-up credit is never expired by this function.
CREATE OR REPLACE FUNCTION public.ensure_company_ai_credit_period(p_company_id bigint)
RETURNS TABLE(
  company_id bigint,
  subscription_id bigint,
  period_start timestamptz,
  period_end timestamptz,
  included_balance_micro_myr bigint,
  topup_balance_micro_myr bigint,
  included_credit_granted_micro_myr bigint,
  period_changed boolean,
  transaction_id bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_subscription record;
  v_balance public.company_ai_credit_balances%ROWTYPE;
  v_contract_end timestamptz;
  v_allowance_start timestamptz;
  v_allowance_end timestamptz;
  v_candidate_start timestamptz;
  v_grant_amount bigint;
  v_previous_included_balance bigint := 0;
  v_transaction_id bigint := NULL;
  v_period_changed boolean := false;
  v_grant_idempotency_key text;
  v_expiry_idempotency_key text;
  v_month_index integer;
BEGIN
  IF p_company_id IS NULL OR p_company_id <= 0 THEN
    RAISE EXCEPTION 'company_id must be a positive integer' USING ERRCODE = '22023';
  END IF;

  SELECT
    cs.id AS subscription_id,
    cs.company_id,
    cs.current_period_start,
    cs.current_period_end,
    cs.billing_term_months,
    cs.created_at,
    sp.included_ai_credit_micro_myr
  INTO v_subscription
  FROM public.company_subscriptions AS cs
  JOIN public.subscription_plans AS sp ON sp.id = cs.plan_id
  WHERE cs.company_id = p_company_id
    AND cs.status IN ('trialing', 'active', 'past_due')
  ORDER BY CASE cs.status WHEN 'active' THEN 1 WHEN 'trialing' THEN 2 WHEN 'past_due' THEN 3 ELSE 4 END,
           cs.created_at DESC
  LIMIT 1
  FOR UPDATE OF cs;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'No active, trialing, or past-due subscription found for company %', p_company_id
      USING ERRCODE = 'P0002';
  END IF;
  IF v_subscription.current_period_start IS NULL THEN
    RAISE EXCEPTION 'Subscription % has no current period start', v_subscription.subscription_id
      USING ERRCODE = '23502';
  END IF;
  IF COALESCE(v_subscription.billing_term_months, 1) NOT IN (1, 3, 6, 12) THEN
    RAISE EXCEPTION 'Subscription % has an unsupported billing term', v_subscription.subscription_id
      USING ERRCODE = '23514';
  END IF;

  v_contract_end := COALESCE(
    v_subscription.current_period_end,
    v_subscription.current_period_start + INTERVAL '1 month'
  );
  IF v_contract_end <= v_subscription.current_period_start THEN
    RAISE EXCEPTION 'Subscription % has an invalid paid period', v_subscription.subscription_id
      USING ERRCODE = '22007';
  END IF;
  IF now() >= v_contract_end THEN
    RAISE EXCEPTION 'Subscription % paid period has ended', v_subscription.subscription_id
      USING ERRCODE = 'P0002';
  END IF;

  v_allowance_start := v_subscription.current_period_start;
  v_allowance_end := LEAST(
    v_subscription.current_period_start + INTERVAL '1 month',
    v_contract_end
  );
  FOR v_month_index IN 0..(COALESCE(v_subscription.billing_term_months, 1) - 1) LOOP
    v_candidate_start := v_subscription.current_period_start + make_interval(months => v_month_index);
    EXIT WHEN v_candidate_start > now();
    IF now() < LEAST(
      v_subscription.current_period_start + make_interval(months => v_month_index + 1),
      v_contract_end
    ) THEN
      v_allowance_start := v_candidate_start;
      v_allowance_end := LEAST(
        v_subscription.current_period_start + make_interval(months => v_month_index + 1),
        v_contract_end
      );
      EXIT;
    END IF;
  END LOOP;

  v_grant_amount := COALESCE(v_subscription.included_ai_credit_micro_myr, 0);
  IF v_grant_amount < 0 THEN
    RAISE EXCEPTION 'Subscription % has a negative included AI-credit amount', v_subscription.subscription_id
      USING ERRCODE = '23514';
  END IF;

  SELECT balance_row.* INTO v_balance
  FROM public.company_ai_credit_balances AS balance_row
  WHERE balance_row.company_id = p_company_id
  FOR UPDATE;

  IF NOT FOUND THEN
    INSERT INTO public.company_ai_credit_balances (
      company_id, subscription_id, period_start, period_end,
      included_balance_micro_myr, topup_balance_micro_myr
    ) VALUES (
      p_company_id, v_subscription.subscription_id, v_allowance_start,
      v_allowance_end, v_grant_amount, 0
    ) RETURNING * INTO v_balance;
    v_period_changed := true;
  ELSIF v_balance.subscription_id IS DISTINCT FROM v_subscription.subscription_id
     OR v_balance.period_start IS DISTINCT FROM v_allowance_start THEN
    v_previous_included_balance := v_balance.included_balance_micro_myr;
    IF v_previous_included_balance > 0 THEN
      v_expiry_idempotency_key := format(
        'included-credit-expiry:%s:%s', p_company_id, v_balance.period_start
      );
      INSERT INTO public.ai_credit_transactions (
        company_id, subscription_id, transaction_type,
        included_delta_micro_myr, topup_delta_micro_myr,
        included_balance_after_micro_myr, topup_balance_after_micro_myr,
        idempotency_key, period_start, period_end, description
      ) VALUES (
        p_company_id, v_balance.subscription_id, 'expiry',
        -v_previous_included_balance, 0, 0, v_balance.topup_balance_micro_myr,
        v_expiry_idempotency_key, v_balance.period_start, v_balance.period_end,
        'Unused included AI credit expired at monthly allowance reset'
      ) ON CONFLICT (idempotency_key) DO NOTHING;
    END IF;

    UPDATE public.company_ai_credit_balances
    SET subscription_id = v_subscription.subscription_id,
        period_start = v_allowance_start,
        period_end = v_allowance_end,
        included_balance_micro_myr = v_grant_amount,
        updated_at = now()
    WHERE company_ai_credit_balances.company_id = p_company_id
    RETURNING * INTO v_balance;
    v_period_changed := true;
  ELSIF v_balance.period_end IS DISTINCT FROM v_allowance_end THEN
    UPDATE public.company_ai_credit_balances
    SET period_end = v_allowance_end, updated_at = now()
    WHERE company_ai_credit_balances.company_id = p_company_id
    RETURNING * INTO v_balance;
  END IF;

  IF v_period_changed AND v_grant_amount > 0 THEN
    v_grant_idempotency_key := format(
      'included-credit-grant:%s:%s', v_subscription.subscription_id, v_allowance_start
    );
    INSERT INTO public.ai_credit_transactions (
      company_id, subscription_id, transaction_type,
      included_delta_micro_myr, topup_delta_micro_myr,
      included_balance_after_micro_myr, topup_balance_after_micro_myr,
      idempotency_key, period_start, period_end, description
    ) VALUES (
      p_company_id, v_subscription.subscription_id, 'included_credit_grant',
      v_grant_amount, 0, v_balance.included_balance_micro_myr,
      v_balance.topup_balance_micro_myr, v_grant_idempotency_key,
      v_allowance_start, v_allowance_end,
      'Included AI credit granted for the monthly allowance period'
    ) ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_transaction_id;

    IF v_transaction_id IS NULL THEN
      SELECT transaction_row.id INTO v_transaction_id
      FROM public.ai_credit_transactions AS transaction_row
      WHERE transaction_row.idempotency_key = v_grant_idempotency_key
      LIMIT 1;
    END IF;
  END IF;

  RETURN QUERY SELECT
    v_balance.company_id,
    v_balance.subscription_id,
    v_balance.period_start,
    v_balance.period_end,
    v_balance.included_balance_micro_myr,
    v_balance.topup_balance_micro_myr,
    CASE WHEN v_period_changed THEN v_grant_amount ELSE 0 END,
    v_period_changed,
    v_transaction_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.ensure_company_ai_credit_period(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ensure_company_ai_credit_period(bigint) TO service_role;

COMMENT ON COLUMN public.company_subscription_orders.billing_term_months IS
  'Prepaid subscription term selected at checkout. Supported values: 1, 3, 6, 12.';
COMMENT ON COLUMN public.company_subscription_orders.monthly_equivalent_sen IS
  'Document-approved monthly equivalent for the selected prepaid term; amount_sen is the full upfront charge.';
COMMENT ON COLUMN public.company_subscriptions.billing_term_months IS
  'Current prepaid subscription term; monthly allowances reset independently.';

COMMIT;
