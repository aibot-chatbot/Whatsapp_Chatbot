-- 068_automation_workflows_feature_flag_rollback.sql
-- Reverses 068_automation_workflows_feature_flag.sql by removing the one key it
-- added.  Every other flag is untouched.
--
-- Effect: can_use_plan_feature (app/services/billing_guard.py) fails closed on
-- an absent key, so after this runs automation_workflows is DENIED on every
-- plan, Pro included, for as long as the application still registers the key.
-- Pro tenants lose scheduled Analysis, recording, reminders and n8n/Langflow
-- automation until the forward migration is re-applied or the application code
-- that checks the key is reverted in the same window.

UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) - 'automation_workflows'
-- jsonb_exists is the function form of the ? operator; it survives clients that
-- treat a bare ? as a bind placeholder.
WHERE jsonb_exists(feature_flags, 'automation_workflows');
