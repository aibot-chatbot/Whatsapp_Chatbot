-- 002_set_subscription_plan_feature_flags.sql
-- Update feature_flags for existing subscription plans.
--
-- THIS IS A TEMPLATE. The Essential, Advanced and Pro plans must first exist
-- in the database (created via Supabase dashboard or a separate INSERT migration)
-- before this UPDATE migration can run.
--
-- The existing Free plan receives all three features as false.
-- Planned paid plans (Essential / Advanced / Pro) receive their intended flags.
-- Unrelated future keys in feature_flags are preserved via merge (||).
--
-- How to run (Supabase SQL Editor):
--   1. Verify that the plan codes match your Supabase rows.
--   2. Run the entire script. It is idempotent (uses UPSERT semantics via merge).
--   3. Features missing from feature_flags for an existing plan are left unchanged.

-- === Free plan (existing, assigned to new companies) ===
-- All three gated features are disabled.
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'batch_website_scraping', false,
    'ai_generated_reports', false,
    'ai_assisted_menu_generation', false
)
WHERE code = 'free';

-- === Essential plan ===
-- Batch scraping: DISABLED
-- AI reports: DISABLED
-- AI menu generation: DISABLED
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'batch_website_scraping', false,
    'ai_generated_reports', false,
    'ai_assisted_menu_generation', false
)
WHERE LOWER(code) = 'essential';

-- === Advanced plan ===
-- Batch scraping: ENABLED
-- AI reports: ENABLED
-- AI menu generation: ENABLED
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'batch_website_scraping', true,
    'ai_generated_reports', true,
    'ai_assisted_menu_generation', true
)
WHERE LOWER(code) = 'advanced';

-- === Pro plan ===
-- Batch scraping: ENABLED
-- AI reports: ENABLED
-- AI menu generation: ENABLED
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'batch_website_scraping', true,
    'ai_generated_reports', true,
    'ai_assisted_menu_generation', true
)
WHERE LOWER(code) = 'pro';

-- === 7-Day Trial plan (if it exists as a separate row) ===
-- All three gated features are disabled during trial.
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'batch_website_scraping', false,
    'ai_generated_reports', false,
    'ai_assisted_menu_generation', false
)
WHERE LOWER(code) IN ('trial', '7_day_trial', 'free_trial');
