-- 042_gate_new_capability_feature_flags_rollback.sql
-- Reverses 042_gate_new_capability_feature_flags.sql by removing the three
-- keys it added, restoring the pre-migration state where the keys were absent.
--
-- !! STOP.  THIS IS NOT A "DISABLE THE FEATURE" SCRIPT.  IT GIVES THE THREE
-- !! CAPABILITIES AWAY TO EVERY PLAN, INCLUDING FREE.
--
-- Removing a key does NOT disable the capability -- it re-opens it for
-- everyone.  can_use_plan_feature (app/services/billing_guard.py:435-440)
-- treats an ABSENT feature key as ALLOWED, so the moment this runs, every
-- plan -- Free included -- can use unified ingestion, derived persona and
-- conversation memory, unmetered and unmonetised, until someone notices.
--
-- Run it ONLY in the same maintenance window as reverting the application code
-- that calls can_use_plan_feature for these keys.  If you want to switch a
-- capability off instead, re-run the forward migration 034 (or set the key to
-- false for that plan) -- do not run this.
--
-- Only the three keys 034 wrote are removed; every other flag is untouched.

UPDATE subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb)
    - 'unified_knowledge_ingestion'
    - 'ai_derived_persona'
    - 'conversation_memory'
-- jsonb_exists_any is the function form of the ?| operator.  Same semantics,
-- but it survives clients that treat a bare ? as a bind placeholder (JDBC,
-- ODBC, some pooler consoles).  The Supabase SQL Editor accepts either.
WHERE jsonb_exists_any(feature_flags, ARRAY[
    'unified_knowledge_ingestion',
    'ai_derived_persona',
    'conversation_memory'
]);
