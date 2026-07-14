-- 019_set_trial_ai_credit.sql
-- Adds a fixed RM 1.00 AI-credit allowance for the Free trial plan.

UPDATE public.subscription_plans
SET
    included_ai_credit_micro_myr = 1000000
WHERE LOWER(code) = 'free';