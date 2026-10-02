-- 068_automation_workflows_feature_flag.sql
-- Idempotent migration adding the subscription plan feature flag
--
--   automation_workflows   automatic working flows: n8n outbox work, the
--                          Langflow decision layer, scheduled Analysis runs,
--                          customer-request recording (business observations)
--                          and tuition trial reminders
--
-- Product owner decision: automatic working flows are Pro-only.
--
--                          free   essential   advanced   pro
--   automation_workflows   false    false       false     true
--
-- Manual, on-demand Analysis reports are NOT covered by this key; they stay on
-- ai_generated_reports.  Scheduled reports need both keys.
--
-- Why a new file.  004 and 042 have already been applied to real databases, so
-- editing them would never run there.
--
-- Why every plan gets an explicit value.  can_use_plan_feature
-- (app/services/billing_guard.py) fails closed: only an exact JSON true allows.
-- An absent key is therefore already denied, but the sanctioned matrix must be
-- visible in data, and tests/test_plan_feature_gating.py asserts every
-- registered key carries an explicit boolean on every plan.
--
-- Applied by the owner, not by the application: service_role holds SELECT but
-- not UPDATE on subscription_plans (see 057).  Do NOT grant UPDATE to make this
-- easier.
--
-- Re-run safety.  Every statement overwrites one known key, so the file
-- converges on the same state however often it runs and never removes a key.
-- Re-running RESTORES the sanctioned matrix and discards a manual per-plan
-- grant of automation_workflows made in the SQL Editor.
--
-- Atomicity.  The Supabase SQL Editor sends the whole file as one simple-query
-- message, which PostgreSQL wraps in one implicit transaction, so the assertion
-- at the end rolls the whole file back.  If you run statements one at a time,
-- you MUST run the assertion too.
--
-- Does not modify limits, prices, included AI credits, model-access tiers or
-- any other feature key.

-- === Free ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'automation_workflows', false
)
WHERE LOWER(code) = 'free';

-- === Essential ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'automation_workflows', false
)
WHERE LOWER(code) = 'essential';

-- === Advanced ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'automation_workflows', false
)
WHERE LOWER(code) = 'advanced';

-- === Pro ===
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'automation_workflows', true
)
WHERE LOWER(code) = 'pro';

-- === Every other plan code: explicit false (fail closed) ===
-- "code IS NULL OR" is load-bearing: NULL NOT IN (...) is NULL, not TRUE, so a
-- NULL-code row would otherwise match no statement at all.  Runs last and uses
-- NOT IN, so it can never overwrite the four decisions above.
UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || jsonb_build_object(
    'automation_workflows', false
)
WHERE code IS NULL OR LOWER(code) NOT IN ('free', 'essential', 'advanced', 'pro');

-- === Assertion: refuse to report success on a gate that does not exist ===
DO $$
DECLARE
    offenders text;
BEGIN
    -- (a) Every row carries an explicit JSON boolean for the key.
    SELECT string_agg(COALESCE(p.code, '(null code)'), ', ' ORDER BY COALESCE(p.code, '(null code)'))
      INTO offenders
      FROM subscription_plans p
     WHERE jsonb_typeof(COALESCE(p.feature_flags, '{}'::jsonb) -> 'automation_workflows') IS DISTINCT FROM 'boolean';

    IF offenders IS NOT NULL THEN
        RAISE EXCEPTION
            '068 aborted: subscription_plans rows without an explicit boolean automation_workflows: %',
            offenders;
    END IF;

    -- (b) The four plan codes the matrix decides must actually exist.
    SELECT string_agg(t.expected, ', ' ORDER BY t.expected)
      INTO offenders
      FROM unnest(ARRAY['free', 'essential', 'advanced', 'pro']) AS t(expected)
     WHERE NOT EXISTS (
               SELECT 1 FROM subscription_plans p WHERE LOWER(p.code) = t.expected
           );

    IF offenders IS NOT NULL THEN
        RAISE EXCEPTION
            '068 aborted: no subscription_plans row matches these plan codes: %',
            offenders;
    END IF;

    -- (c) Only Pro may carry true.
    SELECT string_agg(COALESCE(p.code, '(null code)'), ', ' ORDER BY COALESCE(p.code, '(null code)'))
      INTO offenders
      FROM subscription_plans p
     WHERE (p.feature_flags -> 'automation_workflows') = 'true'::jsonb
       AND LOWER(COALESCE(p.code, '')) <> 'pro';

    IF offenders IS NOT NULL THEN
        RAISE EXCEPTION
            '068 aborted: automation_workflows is granted outside Pro: %',
            offenders;
    END IF;
END
$$;

-- === Verification (optional; the assertion above already enforces it) ===
--
--   SELECT code, feature_flags -> 'automation_workflows' AS automation_workflows
--   FROM subscription_plans
--   ORDER BY code;
