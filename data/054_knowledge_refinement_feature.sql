-- Apply before enabling Knowledge Refinement Q&A in an existing deployment.
-- Save the returned IDs: rollback must target only rows changed by this migration.
-- Existing explicit values (including false/null) and unrelated flags are preserved.
BEGIN;

UPDATE public.subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb)
    || jsonb_build_object('knowledge_refinement', false)
WHERE LOWER(code) = 'free'
  AND (feature_flags IS NULL OR jsonb_typeof(feature_flags) = 'object')
  AND NOT (COALESCE(feature_flags, '{}'::jsonb) ? 'knowledge_refinement')
RETURNING id, code;

UPDATE public.subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb)
    || jsonb_build_object('knowledge_refinement', false)
WHERE LOWER(code) = 'essential'
  AND (feature_flags IS NULL OR jsonb_typeof(feature_flags) = 'object')
  AND NOT (COALESCE(feature_flags, '{}'::jsonb) ? 'knowledge_refinement')
RETURNING id, code;

UPDATE public.subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb)
    || jsonb_build_object('knowledge_refinement', false)
WHERE LOWER(code) = 'advanced'
  AND (feature_flags IS NULL OR jsonb_typeof(feature_flags) = 'object')
  AND NOT (COALESCE(feature_flags, '{}'::jsonb) ? 'knowledge_refinement')
RETURNING id, code;

UPDATE public.subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb)
    || jsonb_build_object('knowledge_refinement', true)
WHERE LOWER(code) = 'pro'
  AND (feature_flags IS NULL OR jsonb_typeof(feature_flags) = 'object')
  AND NOT (COALESCE(feature_flags, '{}'::jsonb) ? 'knowledge_refinement')
RETURNING id, code;

COMMIT;
