-- 001_add_subscription_plan_feature_flags.sql
-- Adds a JSONB column to subscription_plans for boolean feature-access control.
-- This allows adding or removing gated features without schema changes.
-- Default empty object: all features implicitly allowed (backward compatible).

ALTER TABLE subscription_plans
ADD COLUMN IF NOT EXISTS feature_flags jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN subscription_plans.feature_flags IS
'JSONB object mapping feature keys to boolean. true=enabled, false=disabled, missing=allowed (temporary backward compatibility). Example: {"batch_website_scraping": true, "ai_generated_reports": false}'
