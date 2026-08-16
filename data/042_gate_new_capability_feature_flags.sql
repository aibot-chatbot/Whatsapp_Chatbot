-- 042_gate_new_capability_feature_flags.sql
-- Idempotent migration configuring the subscription plan feature flags for
-- three newly built capabilities:
--
--   unified_knowledge_ingestion  POST /api/knowledge/ingest (websites only)
--   ai_derived_persona           persona derived from an uploaded document
--   conversation_memory          conversation graph memory + keyword recall
--
-- Why a new file rather than an edit to 004.
--   004_add_subscription_plan_feature_flags.sql has already been applied to
--   real databases.  Adding keys to it would not re-run there, so the flags
--   would never land and every plan would keep the capability -- see below.
--
-- Why every key must be set on every plan.
--   can_use_plan_feature (app/services/billing_guard.py:435-440) returns True
--   when the feature_flags column is NULL or not an object, AND returns True
--   when the key is simply ABSENT from the map.  The guard therefore fails
--   open twice: registering a key in PLAN_FEATURES gates nothing, and any plan
--   row this migration misses silently keeps the capability for free.  That is
--   why the catch-all below defaults every plan code not named above to false,
--   and why the assertion at the end of this file refuses to let the migration
--   report success while any row is still missing a key.
--
-- Plan matrix (product owner, cost-aligned):
--
--                       free   essential   advanced   pro
--   unified ingestion   false    false       true     true
--   derived persona     false    true        true     true
--   conversation memory false    true        true     true
--
--   conversation_memory adds no LLM call (the fields it stores come from the
--   pure-regex extractor that already runs on every turn); ai_derived_persona
--   costs one LLM call per document upload; unified_knowledge_ingestion is the
--   expensive, unbounded one and stays on the top two plans.
--
--   A company in the trial period sits on the Free plan with status
--   'trialing' (app/services/ai_access_policy.py:124) -- 'trial' is not a plan
--   code -- so trialing tenants are denied all three, by design of the matrix
--   above.  Raise it with the product owner if trials are meant to demo them.
--
-- Uses JSONB merging (||) so existing feature flags survive.  Plan-code
-- matching is case-insensitive, as in 003/004.
--
-- Re-run safety.  Every statement is an overwrite of three known keys, so the
-- file converges on the same state however often it runs, and never removes a
-- key.  Consequence to accept deliberately: re-running RESTORES the sanctioned
-- matrix and discards any manual per-plan grant made in the SQL Editor.  At a
-- revenue boundary that is the correct direction (no application code writes
-- feature_flags, so a manual grant is always an out-of-band exception), but do
-- not re-run this file to "refresh" it without expecting that.
--
-- Atomicity.  The Supabase SQL Editor sends the whole file as one simple-query
-- message, which PostgreSQL wraps in a single implicit transaction: the
-- assertion at the end therefore rolls the whole migration back rather than
-- leaving a half-applied gate.  If you instead run the statements one at a
-- time, you MUST run the assertion too -- a partially applied file leaves the
-- unreached plans fully open.
--
-- Does not modify limits, prices, included AI credits, model-access tiers or
-- any feature key set by an earlier migration.

-- === Free ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'unified_knowledge_ingestion', false,
    'ai_derived_persona', false,
    'conversation_memory', false
)
WHERE LOWER(code) = 'free';

-- === Essential ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'unified_knowledge_ingestion', false,
    'ai_derived_persona', true,
    'conversation_memory', true
)
WHERE LOWER(code) = 'essential';

-- === Advanced ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'unified_knowledge_ingestion', true,
    'ai_derived_persona', true,
    'conversation_memory', true
)
WHERE LOWER(code) = 'advanced';

-- === Pro ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'unified_knowledge_ingestion', true,
    'ai_derived_persona', true,
    'conversation_memory', true
)
WHERE LOWER(code) = 'pro';

-- === Every other plan code: explicit false (fail closed) ===
-- A trial/legacy/enterprise/custom row that this migration does not name would
-- otherwise keep all three capabilities, because an absent key is allowed.
-- Denying an unknown plan is recoverable by a support ticket; an unmonetised
-- capability is not recoverable at all.  Runs last and uses NOT IN, so it can
-- never overwrite the four decisions above.
--
-- "code IS NULL OR" is load-bearing, not defensive noise: NULL NOT IN (...)
-- evaluates to NULL, not TRUE, so a row with a NULL code would match neither
-- the four named statements nor this catch-all and would be the one row shape
-- that still fails OPEN.  Subscriptions resolve their plan by plan_id
-- (billing_service.py:87), never by code, so such a row is reachable.
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'unified_knowledge_ingestion', false,
    'ai_derived_persona', false,
    'conversation_memory', false
)
WHERE code IS NULL OR LOWER(code) NOT IN ('free', 'essential', 'advanced', 'pro');

-- === Assertion: refuse to report success on a gate that does not exist ===
-- Without this, applying the file to a database whose plan catalogue differs
-- from the one assumed above updates 0 rows and still reports success -- and
-- an absent key is ALLOWED, so the "successful" migration would leave the
-- capability free for that plan, silently and permanently.  A raised exception
-- rolls the whole file back (see "Atomicity" in the header), which is the
-- recoverable outcome: no gate and a loud error beats a half gate and silence.
DO $$
DECLARE
    offenders text;
BEGIN
    -- (a) Post-state invariant: every row now carries three JSON booleans.
    --     jsonb_typeof(...) IS DISTINCT FROM 'boolean' catches an absent key,
    --     a JSON null, and a string/number written by hand -- all three of
    --     which can_use_plan_feature treats as something other than "denied".
    SELECT string_agg(COALESCE(p.code, '(null code)'), ', ' ORDER BY COALESCE(p.code, '(null code)'))
      INTO offenders
      FROM subscription_plans p
     WHERE jsonb_typeof(COALESCE(p.feature_flags, '{}'::jsonb) -> 'unified_knowledge_ingestion') IS DISTINCT FROM 'boolean'
        OR jsonb_typeof(COALESCE(p.feature_flags, '{}'::jsonb) -> 'ai_derived_persona') IS DISTINCT FROM 'boolean'
        OR jsonb_typeof(COALESCE(p.feature_flags, '{}'::jsonb) -> 'conversation_memory') IS DISTINCT FROM 'boolean';

    IF offenders IS NOT NULL THEN
        RAISE EXCEPTION
            '034 aborted: subscription_plans rows without an explicit boolean for all three keys (an absent key is ALLOWED, so these plans would keep the capability): %',
            offenders;
    END IF;

    -- (b) The four plan codes the matrix decides must actually exist.  A
    --     missing row is how "0 rows updated" masquerades as success.
    SELECT string_agg(t.expected, ', ' ORDER BY t.expected)
      INTO offenders
      FROM unnest(ARRAY['free', 'essential', 'advanced', 'pro']) AS t(expected)
     WHERE NOT EXISTS (
               SELECT 1 FROM subscription_plans p WHERE LOWER(p.code) = t.expected
           );

    IF offenders IS NOT NULL THEN
        RAISE EXCEPTION
            '034 aborted: no subscription_plans row matches these plan codes, so nothing was gated for them: %',
            offenders;
    END IF;
END
$$;

-- === Verification (optional; the assertion above already enforces it) ===
-- Every row must report three non-null booleans:
--
--   SELECT code,
--          feature_flags -> 'unified_knowledge_ingestion' AS unified_ingestion,
--          feature_flags -> 'ai_derived_persona'          AS derived_persona,
--          feature_flags -> 'conversation_memory'         AS conversation_memory
--   FROM subscription_plans
--   ORDER BY code;
