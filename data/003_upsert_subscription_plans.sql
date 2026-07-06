-- 003_upsert_subscription_plans.sql
-- Idempotent seed migration for the paid subscription plan catalogue.
--
-- Creates Essential, Advanced and Pro plans if they do not already exist.
-- Updates only fields that differ on re-run (idempotent).
-- Preserves the existing Free plan unchanged.
--
-- Plan codes are stored as lowercase strings so that the application-level
-- lookups (get_plan_by_code uses exact .eq match) succeed without
-- case-conversion at query time.
--
-- Price and included_ai_credit_micro_myr are NULL because the commercial
-- values have not been finalised. An ALTER TABLE statement ensures the
-- columns accept NULL values before the INSERT runs.
-- The application code uses str(plan.get("price") or "0") and

-- === Schema adjustment: permit NULL commercial values ===
-- price and included_ai_credit_micro_myr have NOT NULL defaults of 0 in
-- the live schema, but the commercial values are still undecided.
-- This ALTER is idempotent (DROP NOT NULL is a no-op if already nullable).

ALTER TABLE public.subscription_plans
    ALTER COLUMN price DROP NOT NULL,
    ALTER COLUMN included_ai_credit_micro_myr DROP NOT NULL;

-- === Insert or update each plan ===

-- Essential
INSERT INTO subscription_plans (code, name, description, is_active, chatbot_limit, team_member_limit, knowledge_file_limit, knowledge_storage_limit_bytes, channel_limit, model_access_tier, feature_flags, billing_interval, currency, price, included_ai_credit_micro_myr)
SELECT 'essential', 'Essential', 'Essential plan - 1 chatbot, 1 channel, 5 knowledge files, 50 MB storage', TRUE, 1, 1, 5, 52428800, 1, 'economy', '{"batch_website_scraping": false, "ai_generated_reports": false, "ai_assisted_menu_generation": false}'::jsonb, 'monthly', 'MYR', NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM subscription_plans WHERE LOWER(code) = 'essential');

-- Advanced
INSERT INTO subscription_plans (code, name, description, is_active, chatbot_limit, team_member_limit, knowledge_file_limit, knowledge_storage_limit_bytes, channel_limit, model_access_tier, feature_flags, billing_interval, currency, price, included_ai_credit_micro_myr)
SELECT 'advanced', 'Advanced', 'Advanced plan - 2 chatbots, 2 channels, 25 knowledge files, 250 MB storage', TRUE, 2, 3, 25, 262144000, 2, 'standard', '{"batch_website_scraping": false, "ai_generated_reports": false, "ai_assisted_menu_generation": true}'::jsonb, 'monthly', 'MYR', NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM subscription_plans WHERE LOWER(code) = 'advanced');

-- Pro
INSERT INTO subscription_plans (code, name, description, is_active, chatbot_limit, team_member_limit, knowledge_file_limit, knowledge_storage_limit_bytes, channel_limit, model_access_tier, feature_flags, billing_interval, currency, price, included_ai_credit_micro_myr)
SELECT 'pro', 'Pro', 'Pro plan - 3 chatbots, 2 channels, 75 knowledge files, 1 GB storage', TRUE, 3, 5, 75, 1073741824, 2, 'premium', '{"batch_website_scraping": true, "ai_generated_reports": true, "ai_assisted_menu_generation": true}'::jsonb, 'monthly', 'MYR', NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM subscription_plans WHERE LOWER(code) = 'pro');

-- === Update existing rows (idempotent re-run) ===
-- Using lowercase code match to be consistent.
-- COALESCE + || merge preserves any manually set feature_flags that were
-- not part of this migration, while overwriting the three known keys.

UPDATE subscription_plans
SET
    is_active = TRUE,
    chatbot_limit = 1,
    team_member_limit = 1,
    knowledge_file_limit = 5,
    knowledge_storage_limit_bytes = 52428800,
    channel_limit = 1,
    model_access_tier = 'economy',
    billing_interval = COALESCE(billing_interval, 'monthly'),
    currency = COALESCE(currency, 'MYR'),
    feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
        'batch_website_scraping', false,
        'ai_generated_reports', false,
        'ai_assisted_menu_generation', false
    )
WHERE LOWER(code) = 'essential';

UPDATE subscription_plans
SET
    is_active = TRUE,
    chatbot_limit = 2,
    team_member_limit = 3,
    knowledge_file_limit = 25,
    knowledge_storage_limit_bytes = 262144000,
    channel_limit = 2,
    model_access_tier = 'standard',
    billing_interval = COALESCE(billing_interval, 'monthly'),
    currency = COALESCE(currency, 'MYR'),
    feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
        'batch_website_scraping', false,
        'ai_generated_reports', false,
        'ai_assisted_menu_generation', true
    )
WHERE LOWER(code) = 'advanced';

UPDATE subscription_plans
SET
    is_active = TRUE,
    chatbot_limit = 3,
    team_member_limit = 5,
    knowledge_file_limit = 75,
    knowledge_storage_limit_bytes = 1073741824,
    channel_limit = 2,
    model_access_tier = 'premium',
    billing_interval = COALESCE(billing_interval, 'monthly'),
    currency = COALESCE(currency, 'MYR'),
    feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
        'batch_website_scraping', true,
        'ai_generated_reports', true,
        'ai_assisted_menu_generation', true
    )
WHERE LOWER(code) = 'pro';
