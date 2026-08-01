-- 004_add_subscription_plan_feature_flags.sql
-- Idempotent migration to add and configure new subscription plan feature
-- flags: single_website_scraping and crm_lead_assignment.
--
-- Uses JSONB merging (||) to preserve existing feature flags while adding
-- or updating only the two new keys.  Plan-code matching is case-insensitive.
--
-- Does not modify limits, prices, included AI credits, model-access tiers or
-- any feature keys added by earlier migrations.

-- === Free ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'single_website_scraping', false,
    'batch_website_scraping', false,
    'ai_generated_reports', false,
    'ai_assisted_menu_generation', false,
    'crm_lead_assignment', false,
    'knowledge_refinement', false
)
WHERE LOWER(code) = 'free';

-- === Essential ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'single_website_scraping', false,
    'crm_lead_assignment', false,
    'knowledge_refinement', false
)
WHERE LOWER(code) = 'essential';

-- === Advanced ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'single_website_scraping', true,
    'crm_lead_assignment', true,
    'knowledge_refinement', false
)
WHERE LOWER(code) = 'advanced';

-- === Pro ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'single_website_scraping', true,
    'crm_lead_assignment', true,
    'knowledge_refinement', true
)
WHERE LOWER(code) = 'pro';
