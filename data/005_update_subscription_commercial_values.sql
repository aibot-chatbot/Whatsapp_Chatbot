-- 005_update_subscription_commercial_values.sql
-- Idempotent migration to set commercial prices and included AI credit amounts.
--
-- Updates only the commercial columns (price, included_ai_credit_micro_myr)
-- without modifying limits, feature_flags, model_access_tier, or
-- billing_interval.
--
-- Each UPDATE matches by lowercase plan code and is idempotent.

-- Free: price = 0, no included credit
UPDATE subscription_plans
SET
    price = 0,
    included_ai_credit_micro_myr = 0
WHERE LOWER(code) = 'free';

-- Essential: RM 39/month, RM 5.00 included AI credit (5,000,000 micro-MYR)
UPDATE subscription_plans
SET
    price = 39,
    included_ai_credit_micro_myr = 5000000
WHERE LOWER(code) = 'essential';

-- Advanced: RM 89/month, RM 20.00 included AI credit (20,000,000 micro-MYR)
UPDATE subscription_plans
SET
    price = 89,
    included_ai_credit_micro_myr = 20000000
WHERE LOWER(code) = 'advanced';

-- Pro: RM 169/month, RM 60.00 included AI credit (60,000,000 micro-MYR)
UPDATE subscription_plans
SET
    price = 169,
    included_ai_credit_micro_myr = 60000000
WHERE LOWER(code) = 'pro';
