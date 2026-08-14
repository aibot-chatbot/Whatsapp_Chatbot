-- Targeted repair for company_id=1 / subscription_id=1 monthly period metadata.
--
-- Purpose:
--   Correct a persisted one-year current_period_end on a monthly Pro subscription
--   and the directly coupled AI-credit period metadata.
--
-- Scope:
--   ONLY company_subscriptions.id = 1 AND company_id = 1
--   ONLY company_ai_credit_balances.company_id = 1 AND subscription_id = 1
--   ONLY ai_credit_transactions.company_id = 1 with the exact audited
--        period_start + incorrect period_end pair.
--
-- This file is not a migration. Review before manual execution in Supabase.
-- It intentionally does not change amounts, balances, ownership, status,
-- current_period_start, payment fields, cancellation fields, or transaction
-- timestamps.

BEGIN;

-- ---------------------------------------------------------------------------
-- Constants and hard preconditions. Any mismatch aborts the transaction.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_company_id constant bigint := 1;
    v_subscription_id constant bigint := 1;
    v_plan_code constant text := 'pro';
    v_billing_interval constant text := 'monthly';
    v_start constant timestamptz := '2026-07-28T16:38:37.437543+00:00';
    v_old_end constant timestamptz := '2027-07-28T16:38:37.437543+00:00';
    v_new_end constant timestamptz := '2026-08-28T16:38:37.437543+00:00';
    v_subscription_count integer;
    v_balance_count integer;
    v_tx_count integer;
    v_tx_grant_count integer;
    v_tx_usage_count integer;
BEGIN
    SELECT count(*)
    INTO v_subscription_count
    FROM public.company_subscriptions AS cs
    JOIN public.subscription_plans AS sp
        ON sp.id = cs.plan_id
    WHERE cs.id = v_subscription_id
      AND cs.company_id = v_company_id
      AND sp.code = v_plan_code
      AND sp.billing_interval = v_billing_interval
      AND cs.current_period_start = v_start
      AND cs.current_period_end = v_old_end
      AND v_new_end = v_start + INTERVAL '1 month';

    IF v_subscription_count <> 1 THEN
        RAISE EXCEPTION
            'Precondition failed: expected exactly 1 matching Pro monthly subscription, got %',
            v_subscription_count;
    END IF;

    SELECT count(*)
    INTO v_balance_count
    FROM public.company_ai_credit_balances AS b
    WHERE b.company_id = v_company_id
      AND b.subscription_id = v_subscription_id
      AND b.period_start = v_start
      AND b.period_end = v_old_end;

    IF v_balance_count <> 1 THEN
        RAISE EXCEPTION
            'Precondition failed: expected exactly 1 matching AI-credit balance row, got %',
            v_balance_count;
    END IF;

    SELECT
        count(*),
        count(*) FILTER (WHERE transaction_type = 'included_credit_grant'),
        count(*) FILTER (WHERE transaction_type = 'usage_debit')
    INTO v_tx_count, v_tx_grant_count, v_tx_usage_count
    FROM public.ai_credit_transactions AS tx
    WHERE tx.company_id = v_company_id
      AND tx.period_start = v_start
      AND tx.period_end = v_old_end;

    IF v_tx_count <> 37
       OR v_tx_grant_count <> 1
       OR v_tx_usage_count <> 36
    THEN
        RAISE EXCEPTION
            'Precondition failed: expected 37 tx rows (1 grant, 36 usage), got total=%, grant=%, usage=%',
            v_tx_count, v_tx_grant_count, v_tx_usage_count;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Before snapshot.
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE repair_company_1_before_credit_balance AS
SELECT
    b.company_id,
    b.subscription_id,
    b.period_start,
    b.period_end,
    b.included_balance_micro_myr,
    b.topup_balance_micro_myr
FROM public.company_ai_credit_balances AS b
WHERE b.company_id = 1
  AND b.subscription_id = 1;

CREATE TEMP TABLE repair_company_1_before_tx_aggregate AS
SELECT
    count(*) AS matching_transaction_count,
    count(*) FILTER (WHERE transaction_type = 'included_credit_grant') AS included_credit_grant_count,
    count(*) FILTER (WHERE transaction_type = 'usage_debit') AS usage_debit_count,
    sum(included_delta_micro_myr) AS included_delta_sum,
    sum(topup_delta_micro_myr) AS topup_delta_sum,
    sum(customer_charge_micro_myr) AS customer_charge_sum,
    sum(uncovered_charge_micro_myr) AS uncovered_charge_sum
FROM public.ai_credit_transactions AS tx
WHERE tx.company_id = 1
  AND tx.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
  AND tx.period_end = '2027-07-28T16:38:37.437543+00:00'::timestamptz;

SELECT
    'before_subscription' AS snapshot,
    cs.id AS subscription_id,
    cs.company_id,
    cs.plan_id,
    sp.code AS plan_code,
    sp.name AS plan_name,
    sp.billing_interval,
    cs.status,
    cs.current_period_start,
    cs.current_period_end,
    cs.updated_at
FROM public.company_subscriptions AS cs
JOIN public.subscription_plans AS sp
    ON sp.id = cs.plan_id
WHERE cs.id = 1
  AND cs.company_id = 1;

SELECT
    'before_credit_balance' AS snapshot,
    b.company_id,
    b.subscription_id,
    b.period_start,
    b.period_end,
    b.included_balance_micro_myr,
    b.topup_balance_micro_myr,
    b.updated_at
FROM public.company_ai_credit_balances AS b
WHERE b.company_id = 1
  AND b.subscription_id = 1;

SELECT
    'before_credit_transactions' AS snapshot,
    count(*) AS matching_transaction_count,
    count(*) FILTER (WHERE transaction_type = 'included_credit_grant') AS included_credit_grant_count,
    count(*) FILTER (WHERE transaction_type = 'usage_debit') AS usage_debit_count,
    sum(included_delta_micro_myr) AS included_delta_sum,
    sum(topup_delta_micro_myr) AS topup_delta_sum,
    sum(customer_charge_micro_myr) AS customer_charge_sum,
    sum(uncovered_charge_micro_myr) AS uncovered_charge_sum
FROM public.ai_credit_transactions AS tx
WHERE tx.company_id = 1
  AND tx.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
  AND tx.period_end = '2027-07-28T16:38:37.437543+00:00'::timestamptz;

-- ---------------------------------------------------------------------------
-- Repair updates.
-- updated_at is intentionally left unchanged to keep this repair scoped only
-- to incorrect period-boundary metadata.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_updated_count integer;
BEGIN
    UPDATE public.company_subscriptions AS cs
    SET current_period_end = '2026-08-28T16:38:37.437543+00:00'::timestamptz
    FROM public.subscription_plans AS sp
    WHERE cs.id = 1
      AND cs.company_id = 1
      AND sp.id = cs.plan_id
      AND sp.code = 'pro'
      AND sp.billing_interval = 'monthly'
      AND cs.current_period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND cs.current_period_end = '2027-07-28T16:38:37.437543+00:00'::timestamptz;

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;
    IF v_updated_count <> 1 THEN
        RAISE EXCEPTION
            'Expected to update exactly 1 subscription row, updated %',
            v_updated_count;
    END IF;
END $$;

DO $$
DECLARE
    v_updated_count integer;
BEGIN
    UPDATE public.company_ai_credit_balances AS b
    SET period_end = '2026-08-28T16:38:37.437543+00:00'::timestamptz
    WHERE b.company_id = 1
      AND b.subscription_id = 1
      AND b.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND b.period_end = '2027-07-28T16:38:37.437543+00:00'::timestamptz;

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;
    IF v_updated_count <> 1 THEN
        RAISE EXCEPTION
            'Expected to update exactly 1 credit balance row, updated %',
            v_updated_count;
    END IF;
END $$;

DO $$
DECLARE
    v_updated_count integer;
BEGIN
    UPDATE public.ai_credit_transactions AS tx
    SET period_end = '2026-08-28T16:38:37.437543+00:00'::timestamptz
    WHERE tx.company_id = 1
      AND tx.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND tx.period_end = '2027-07-28T16:38:37.437543+00:00'::timestamptz;

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;
    IF v_updated_count <> 37 THEN
        RAISE EXCEPTION
            'Expected to update exactly 37 credit transaction rows, updated %',
            v_updated_count;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- After validation.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_remaining_old_tx_count integer;
    v_new_tx_count integer;
    v_old_balance_count integer;
    v_subscription_ok_count integer;
BEGIN
    SELECT count(*)
    INTO v_subscription_ok_count
    FROM public.company_subscriptions AS cs
    JOIN public.subscription_plans AS sp
        ON sp.id = cs.plan_id
    WHERE cs.id = 1
      AND cs.company_id = 1
      AND sp.code = 'pro'
      AND sp.billing_interval = 'monthly'
      AND cs.current_period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND cs.current_period_end = '2026-08-28T16:38:37.437543+00:00'::timestamptz
      AND cs.current_period_end = cs.current_period_start + INTERVAL '1 month';

    IF v_subscription_ok_count <> 1 THEN
        RAISE EXCEPTION
            'Postcondition failed: corrected subscription period not found';
    END IF;

    SELECT count(*)
    INTO v_old_balance_count
    FROM public.company_ai_credit_balances AS b
    WHERE b.company_id = 1
      AND b.subscription_id = 1
      AND b.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND b.period_end = '2027-07-28T16:38:37.437543+00:00'::timestamptz;

    IF v_old_balance_count <> 0 THEN
        RAISE EXCEPTION
            'Postcondition failed: old credit balance period_end still present';
    END IF;

    SELECT count(*)
    INTO v_remaining_old_tx_count
    FROM public.ai_credit_transactions AS tx
    WHERE tx.company_id = 1
      AND tx.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND tx.period_end = '2027-07-28T16:38:37.437543+00:00'::timestamptz;

    IF v_remaining_old_tx_count <> 0 THEN
        RAISE EXCEPTION
            'Postcondition failed: old transaction period_end still present on % rows',
            v_remaining_old_tx_count;
    END IF;

    SELECT count(*)
    INTO v_new_tx_count
    FROM public.ai_credit_transactions AS tx
    WHERE tx.company_id = 1
      AND tx.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND tx.period_end = '2026-08-28T16:38:37.437543+00:00'::timestamptz;

    IF v_new_tx_count <> 37 THEN
        RAISE EXCEPTION
            'Postcondition failed: expected 37 corrected transaction rows, got %',
            v_new_tx_count;
    END IF;
END $$;

SELECT
    'after_subscription' AS snapshot,
    cs.id AS subscription_id,
    cs.company_id,
    cs.plan_id,
    sp.code AS plan_code,
    sp.name AS plan_name,
    sp.billing_interval,
    cs.status,
    cs.current_period_start,
    cs.current_period_end,
    cs.updated_at
FROM public.company_subscriptions AS cs
JOIN public.subscription_plans AS sp
    ON sp.id = cs.plan_id
WHERE cs.id = 1
  AND cs.company_id = 1;

SELECT
    'after_credit_balance' AS snapshot,
    b.company_id,
    b.subscription_id,
    b.period_start,
    b.period_end,
    b.included_balance_micro_myr,
    b.topup_balance_micro_myr,
    b.updated_at
FROM public.company_ai_credit_balances AS b
WHERE b.company_id = 1
  AND b.subscription_id = 1;

SELECT
    'after_credit_transactions' AS snapshot,
    count(*) AS matching_transaction_count,
    count(*) FILTER (WHERE transaction_type = 'included_credit_grant') AS included_credit_grant_count,
    count(*) FILTER (WHERE transaction_type = 'usage_debit') AS usage_debit_count,
    sum(included_delta_micro_myr) AS included_delta_sum,
    sum(topup_delta_micro_myr) AS topup_delta_sum,
    sum(customer_charge_micro_myr) AS customer_charge_sum,
    sum(uncovered_charge_micro_myr) AS uncovered_charge_sum
FROM public.ai_credit_transactions AS tx
WHERE tx.company_id = 1
  AND tx.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
  AND tx.period_end = '2026-08-28T16:38:37.437543+00:00'::timestamptz;

-- Prove monetary/balance values did not change.
DO $$
DECLARE
    v_balance_mismatch_count integer;
    v_before_tx record;
    v_after_tx record;
BEGIN
    SELECT count(*)
    INTO v_balance_mismatch_count
    FROM repair_company_1_before_credit_balance AS before_balance
    JOIN public.company_ai_credit_balances AS after_balance
      ON after_balance.company_id = before_balance.company_id
     AND after_balance.subscription_id = before_balance.subscription_id
    WHERE after_balance.included_balance_micro_myr IS DISTINCT FROM
              before_balance.included_balance_micro_myr
       OR after_balance.topup_balance_micro_myr IS DISTINCT FROM
              before_balance.topup_balance_micro_myr;

    IF v_balance_mismatch_count <> 0 THEN
        RAISE EXCEPTION
            'Postcondition failed: credit balance monetary values changed';
    END IF;

    SELECT *
    INTO v_before_tx
    FROM repair_company_1_before_tx_aggregate;

    SELECT
        count(*) AS matching_transaction_count,
        count(*) FILTER (WHERE transaction_type = 'included_credit_grant') AS included_credit_grant_count,
        count(*) FILTER (WHERE transaction_type = 'usage_debit') AS usage_debit_count,
        sum(included_delta_micro_myr) AS included_delta_sum,
        sum(topup_delta_micro_myr) AS topup_delta_sum,
        sum(customer_charge_micro_myr) AS customer_charge_sum,
        sum(uncovered_charge_micro_myr) AS uncovered_charge_sum
    INTO v_after_tx
    FROM public.ai_credit_transactions AS tx
    WHERE tx.company_id = 1
      AND tx.period_start = '2026-07-28T16:38:37.437543+00:00'::timestamptz
      AND tx.period_end = '2026-08-28T16:38:37.437543+00:00'::timestamptz;

    IF v_after_tx.matching_transaction_count IS DISTINCT FROM
           v_before_tx.matching_transaction_count
       OR v_after_tx.included_credit_grant_count IS DISTINCT FROM
           v_before_tx.included_credit_grant_count
       OR v_after_tx.usage_debit_count IS DISTINCT FROM
           v_before_tx.usage_debit_count
       OR v_after_tx.included_delta_sum IS DISTINCT FROM
           v_before_tx.included_delta_sum
       OR v_after_tx.topup_delta_sum IS DISTINCT FROM
           v_before_tx.topup_delta_sum
       OR v_after_tx.customer_charge_sum IS DISTINCT FROM
           v_before_tx.customer_charge_sum
       OR v_after_tx.uncovered_charge_sum IS DISTINCT FROM
           v_before_tx.uncovered_charge_sum
    THEN
        RAISE EXCEPTION
            'Postcondition failed: credit transaction count/type/amount aggregates changed unexpectedly';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- General monthly-period audit should return zero affected rows after this
-- targeted repair, given the current preflight found only company_id=1.
-- ---------------------------------------------------------------------------
SELECT
    count(*) AS affected_monthly_subscription_count_after_repair
FROM public.company_subscriptions AS cs
JOIN public.subscription_plans AS sp
    ON sp.id = cs.plan_id
WHERE sp.billing_interval = 'monthly'
  AND cs.current_period_start IS NOT NULL
  AND cs.current_period_end IS NOT NULL
  AND cs.current_period_end IS DISTINCT FROM (
      cs.current_period_start + INTERVAL '1 month'
  );

COMMIT;

-- Post-execution read-only API expectations:
--   GET /api/billing/subscription current_period_end:
--     2026-08-28T16:38:37.437543+00:00
--   GET /api/billing/usage period.end:
--     2026-08-28T16:38:37.437543+00:00
--   GET /api/billing/usage period.end_source:
--     stored
