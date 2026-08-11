-- Read-only audit for monthly subscription periods that do not match
-- current_period_start + one calendar month.
--
-- This script intentionally performs no writes.

WITH anomalous_subscriptions AS (
    SELECT
        cs.id AS subscription_id,
        cs.company_id,
        cs.plan_id,
        sp.name AS plan_name,
        sp.code AS plan_code,
        sp.billing_interval,
        cs.status,
        cs.current_period_start,
        cs.current_period_end,
        cs.current_period_start + INTERVAL '1 month' AS expected_period_end,
        cs.current_period_end - (
            cs.current_period_start + INTERVAL '1 month'
        ) AS period_difference,
        cs.updated_at
    FROM public.company_subscriptions AS cs
    JOIN public.subscription_plans AS sp
        ON sp.id = cs.plan_id
    WHERE sp.billing_interval = 'monthly'
      AND cs.current_period_start IS NOT NULL
      AND cs.current_period_end IS NOT NULL
      AND cs.current_period_end IS DISTINCT FROM (
          cs.current_period_start + INTERVAL '1 month'
      )
)
SELECT
    a.subscription_id,
    a.company_id,
    a.plan_id,
    a.plan_name,
    a.plan_code,
    a.billing_interval,
    a.status,
    a.current_period_start,
    a.current_period_end,
    a.expected_period_end,
    a.period_difference,
    a.updated_at,
    b.subscription_id AS credit_balance_subscription_id,
    b.period_start AS credit_balance_period_start,
    b.period_end AS credit_balance_period_end,
    b.included_balance_micro_myr,
    b.topup_balance_micro_myr,
    b.updated_at AS credit_balance_updated_at
FROM anomalous_subscriptions AS a
LEFT JOIN public.company_ai_credit_balances AS b
    ON b.company_id = a.company_id
   AND (
       b.subscription_id = a.subscription_id
       OR b.period_start = a.current_period_start
       OR b.period_end = a.current_period_end
   )
ORDER BY a.company_id, a.subscription_id, b.subscription_id;

-- Related ledger rows to review before any repair. Do not update amounts
-- without a separate confirmed accounting reason.
WITH anomalous_subscriptions AS (
    SELECT
        cs.id AS subscription_id,
        cs.company_id,
        cs.current_period_start,
        cs.current_period_end
    FROM public.company_subscriptions AS cs
    JOIN public.subscription_plans AS sp
        ON sp.id = cs.plan_id
    WHERE sp.billing_interval = 'monthly'
      AND cs.current_period_start IS NOT NULL
      AND cs.current_period_end IS NOT NULL
      AND cs.current_period_end IS DISTINCT FROM (
          cs.current_period_start + INTERVAL '1 month'
      )
)
SELECT
    tx.id AS transaction_id,
    tx.company_id,
    tx.subscription_id,
    tx.transaction_type,
    tx.included_delta_micro_myr,
    tx.topup_delta_micro_myr,
    tx.included_balance_after_micro_myr,
    tx.topup_balance_after_micro_myr,
    tx.period_start,
    tx.period_end,
    tx.created_at,
    tx.description
FROM public.ai_credit_transactions AS tx
JOIN anomalous_subscriptions AS a
    ON a.company_id = tx.company_id
   AND (
       a.subscription_id = tx.subscription_id
       OR a.current_period_start = tx.period_start
       OR a.current_period_end = tx.period_end
   )
ORDER BY tx.company_id, tx.subscription_id, tx.created_at, tx.id;
