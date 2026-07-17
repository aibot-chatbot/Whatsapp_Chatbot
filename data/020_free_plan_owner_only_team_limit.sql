-- 020_free_plan_owner_only_team_limit.sql
-- Make the Free/Trial plan owner-only for team members.
--
-- The Free plan row predates the paid-plan seed migration, and
-- 003_upsert_subscription_plans.sql intentionally preserves it. This
-- idempotent update aligns the runtime Free/Trial team limit with the
-- intended owner-only policy without changing paid plan limits.

UPDATE public.subscription_plans
SET
    team_member_limit = 1
WHERE LOWER(code) = 'free';
