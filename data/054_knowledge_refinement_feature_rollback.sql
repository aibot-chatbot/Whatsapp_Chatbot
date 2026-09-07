-- Populate this allowlist with IDs returned by migration 054 before execution.
-- Empty by default: never remove pre-existing entitlement decisions.
-- Review intervening edits before rollback; roll back application gating first.
BEGIN;

UPDATE public.subscription_plans
SET feature_flags = feature_flags - 'knowledge_refinement'
WHERE id = ANY (ARRAY[]::bigint[])
  AND LOWER(code) IN ('free', 'essential', 'advanced', 'pro')
  AND feature_flags -> 'knowledge_refinement' = to_jsonb(LOWER(code) = 'pro');

COMMIT;
