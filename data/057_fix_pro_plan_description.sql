-- 057: correct the Pro plan description
--
-- The Pro row carried placeholder copy: "Temporary example plan with unlimited
-- resource limits." That string appears in no migration in this directory, so
-- the row was edited directly against the database at some point rather than
-- through version control.
--
-- Two problems with leaving it.
--
-- It is false. Pro is not unlimited - the same row sets chatbot_limit 3,
-- channel_limit 2, team_member_limit 5, knowledge_file_limit 75 and
-- knowledge_storage_limit_bytes 1 GB. The description contradicts the limits
-- sitting beside it, and /api/billing/plans serves both to the dashboard and
-- the pricing page, so a customer reads "unlimited" and is then capped at 3.
--
-- And it is explicitly banned copy. Both "Temporary example plan" and
-- "unlimited resource limits" are on the forbidden-strings list in
-- tests/test_landing_pricing_frontend.py, which exists to stop placeholder text
-- reaching a customer-facing surface. That guard only reads landing.html, so it
-- never saw this row.
--
-- Applied by hand rather than from the application: service_role holds SELECT
-- but not UPDATE on subscription_plans, which is a deliberate control - the
-- price catalogue must not be rewritable by application code or by a leaked
-- service key. Do NOT grant UPDATE to service_role to make this easier.
--
-- The WHERE clause matches the old text as well as the code, so re-running this
-- migration after it has been applied is a no-op rather than an overwrite.

UPDATE public.subscription_plans
SET description = 'Pro plan - 3 chatbots, 2 channels, 75 knowledge files, 1 GB storage',
    updated_at  = NOW()
WHERE code = 'pro'
  AND description = 'Temporary example plan with unlimited resource limits.';

-- Verification: expect exactly one row updated, and no plan description may
-- contain placeholder copy afterwards.
--
--   SELECT code, name, price, description
--   FROM public.subscription_plans
--   ORDER BY price ASC;
--
--   SELECT count(*) AS placeholders_remaining
--   FROM public.subscription_plans
--   WHERE description ILIKE '%temporary example%'
--      OR description ILIKE '%unlimited resource%';
--   -- expect 0
