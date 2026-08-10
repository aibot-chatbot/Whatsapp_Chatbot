-- 031_unify_bot_config_persona_fields.sql
-- Unify the three persona values in public.bot_configs that were stored under
-- two column names each, onto one canonical column per value:
--
--     business_description   <-  business_objective   (legacy, deprecated)
--     tone                   <-  response_style       (legacy, deprecated)
--     custom_prompt          <-  prompt_text          (legacy, deprecated)
--
-- The canonical names win because they are the only ones read outside this
-- table's two writer services: app/services/rag_service.py:671-672,706 builds
-- the LLM prompt from them, app/services/match_service.py:64-65 reads two of
-- them, the /api/settings response exposes them, and the prompt-template
-- variables advertised to users are {business_description} and {tone}. The
-- legacy trio is written by two files and read by only those same two files as
-- a fallback -- it has no other consumer.
--
-- SHAPE CAVEAT -- read before applying. Same situation as
-- 030_bot_media_attachments.sql:5-8: there is NO CREATE TABLE for
-- public.bot_configs anywhere in this repository. The only descriptions of the
-- relation are the application payloads --
--     app/services/settings_service.py:28-38    (_row_to_settings, SELECT)
--     app/services/settings_service.py:150-160  (update_settings, INSERT/UPDATE)
--     app/services/profile_service.py:71-84     (save_profile, INSERT/UPDATE)
-- -- which prove the six columns exist and hold text, but CANNOT show their
-- NOT NULL, DEFAULT or CHECK definitions. Unlike 030 this file cannot simply
-- reconstruct the DDL, because the table already exists in production and an
-- ALTER against a guessed shape is not a no-op.
--
-- This file is therefore written to be safe to RUN under every possible
-- nullability: it only relaxes, never tightens; it adds, drops and renames
-- nothing; every statement is idempotent and safe to re-run; and the failure
-- modes it does have all abort the transaction rather than corrupt a row.
--
-- Read that claim narrowly. "This file applied cleanly" does NOT imply "the
-- application deploy will work" -- see the SCOPE LIMIT on step 2. DROP NOT NULL
-- relaxes exactly one of the three mechanisms that can reject a NULL write, and
-- only the preflight can rule out the other two.
--
-- REQUIRED BEFORE APPLYING: run scripts/bot_configs_persona_unification_preflight.sql
-- and attach every result set to the change record. (`\d+ public.bot_configs`
-- is the psql equivalent, but migrations here are applied through the Supabase
-- SQL Editor, which cannot run psql meta-commands -- hence the script.) The
-- rollback file needs section 2 of that output to know which NOT NULL
-- constraints step 2 below removed, because this file cannot record what it did
-- not know. Without that capture the rollback is best-effort, not exact.
--
-- The preflight also covers what this file cannot assert about itself: that no
-- CHECK constraint, domain, trigger, view or routine depends on the legacy
-- columns. See "WHAT MUST BE TRUE BEFORE 031 IS APPLIED" at the top of that
-- script; item I in particular must be exported before this file is applied,
-- because divergent legacy values become unrecoverable afterwards.
--
-- DEPLOY ORDER -- ONLY ONE ORDER IS SAFE:
--   1. Apply this migration.
--   2. Then deploy the application change.
-- The new application code writes SQL NULL into the legacy columns; it does not
-- merely omit them (app/services/bot_config_fields.py:74). If those columns are
-- still NOT NULL, deploying the code first makes every bot_configs INSERT *and*
-- UPDATE fail with a 23502 not-null violation, which supabase-py raises and the
-- request surfaces as an error. Explicit NULL is what makes the failure loud on
-- both paths: an omitted column would instead leave a stale mirror behind on
-- UPDATE, and silently accept the default on INSERT, so the read fallback could
-- resurrect a value the user had just deleted. Old code keeps working against
-- the migrated schema (it writes both names and reads canonical-first), so
-- step 1 is safe to apply while old code is live, and the mixed-version window
-- during step 2 converges in both directions.

BEGIN;

-- Step 2 below takes an ACCESS EXCLUSIVE lock on public.bot_configs, which
-- queues behind every in-flight reader and blocks every new one while it waits.
-- The DDL itself is a catalog-only change and is instantaneous; the danger is
-- the wait. Bound it, and retry the whole file if it trips -- every statement
-- here is re-runnable. Precedent for a transaction-level setting: 028:28.
SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 1. Backfill: copy each legacy value into its canonical column wherever the
--    canonical column holds nothing and the legacy column holds something.
--
--    Rows where BOTH are populated are deliberately left alone: the canonical
--    column is the documented winner and _row_to_settings already reads it
--    first, so overwriting would change what those rows resolve to. Rows where
--    both are blank stay blank. The predicates make each statement a no-op on
--    a second run.
--
--    The `IS NULL OR btrim(...) = ''` shape covers both possible shapes of the
--    legacy columns without knowing which one is live: if a column is nullable
--    an untouched row holds NULL, and if it is NOT NULL DEFAULT '' the same row
--    holds ''. Both are treated as "nothing to copy" on the source side and as
--    "safe to fill" on the target side, so the statement is correct either way.
--
--    One deliberate difference from the application: btrim() treats a run of
--    spaces as blank, while the Python read path (`canonical or legacy or ""`)
--    treats ' ' as a real value. For a row whose canonical column holds only
--    spaces the backfill therefore changes what the app serves. Section 10 of
--    the preflight counts those rows as space_only_canonical_rows; expect 0.
-- ---------------------------------------------------------------------------

UPDATE public.bot_configs
SET business_description = business_objective
WHERE (business_description IS NULL OR btrim(business_description) = '')
  AND business_objective IS NOT NULL
  AND btrim(business_objective) <> '';

UPDATE public.bot_configs
SET tone = response_style
WHERE (tone IS NULL OR btrim(tone) = '')
  AND response_style IS NOT NULL
  AND btrim(response_style) <> '';

UPDATE public.bot_configs
SET custom_prompt = prompt_text
WHERE (custom_prompt IS NULL OR btrim(custom_prompt) = '')
  AND prompt_text IS NOT NULL
  AND btrim(prompt_text) <> '';

-- ---------------------------------------------------------------------------
-- 2. Retire the legacy columns as a write obligation.
--
--    DROP NOT NULL is idempotent -- it is a no-op if the column is already
--    nullable, so this is safe without knowing the current definition. The
--    columns are NOT dropped: keeping them is what makes the rollback possible
--    and what lets pre-unification code keep writing during the deploy.
--
--    SCOPE LIMIT -- this is the one place where "the migration succeeded" does
--    not imply "the application deploy will work". DROP NOT NULL clears exactly
--    one thing: the column's attnotnull flag. It does NOT clear
--      * a CHECK constraint that encodes not-null-ness, e.g.
--        CHECK (prompt_text IS NOT NULL)  -> the code deploy then fails 23514;
--      * a NOT NULL carried by the column's DOMAIN type -> fails 23502;
--      * a BEFORE trigger that rejects or re-mirrors NULL -> the NULL write is
--        silently undone and the drift this migration removes comes straight
--        back, with every unit test still green.
--    Preflight sections 2, 3 and 5 exist to rule out all three. There is no way
--    to assert any of it from inside this file.
--
--    Two failure modes that abort the migration outright rather than corrupt
--    anything, both loud and both leaving the transaction rolled back: a legacy
--    column that is part of the primary key or of a REPLICA IDENTITY USING
--    INDEX cannot have its NOT NULL dropped. Preflight sections 1 and 4.
-- ---------------------------------------------------------------------------

ALTER TABLE public.bot_configs
    ALTER COLUMN business_objective DROP NOT NULL;

ALTER TABLE public.bot_configs
    ALTER COLUMN response_style DROP NOT NULL;

ALTER TABLE public.bot_configs
    ALTER COLUMN prompt_text DROP NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. Mark the legacy columns deprecated so the next reader of \d+ sees it.
-- ---------------------------------------------------------------------------

COMMENT ON COLUMN public.bot_configs.business_objective IS
    'DEPRECATED, superseded by business_description (031). Retained only for '
    'rollback and read-fallback during rollout; application code writes NULL.';
COMMENT ON COLUMN public.bot_configs.response_style IS
    'DEPRECATED, superseded by tone (031). Retained only for rollback and '
    'read-fallback during rollout; application code writes NULL.';
COMMENT ON COLUMN public.bot_configs.prompt_text IS
    'DEPRECATED, superseded by custom_prompt (031). Retained only for rollback '
    'and read-fallback during rollout; application code writes NULL.';

COMMENT ON COLUMN public.bot_configs.business_description IS
    'Canonical business description. Read by rag_service and match_service.';
COMMENT ON COLUMN public.bot_configs.tone IS
    'Canonical reply tone. Read by rag_service, match_service and settings.';
COMMENT ON COLUMN public.bot_configs.custom_prompt IS
    'Canonical prompt override template. Read by rag_service.';

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification (run after COMMIT; every count must be 0):
--
--   SELECT count(*) FROM public.bot_configs
--   WHERE (business_description IS NULL OR btrim(business_description) = '')
--     AND btrim(coalesce(business_objective, '')) <> '';
--
--   SELECT count(*) FROM public.bot_configs
--   WHERE (tone IS NULL OR btrim(tone) = '')
--     AND btrim(coalesce(response_style, '')) <> '';
--
--   SELECT count(*) FROM public.bot_configs
--   WHERE (custom_prompt IS NULL OR btrim(custom_prompt) = '')
--     AND btrim(coalesce(prompt_text, '')) <> '';
--
-- Divergence: rows where the two names disagreed. This migration deliberately
-- does NOT touch them -- the canonical value is what the app has always served,
-- so overwriting either side would change behaviour for real tenants, and
-- refusing to proceed would block the migration on a condition that has no
-- automated resolution. Reporting is the right disposition for the VALUE.
--
-- It is the wrong place for the REPORT, though, which is why the manifest now
-- lives in preflight section 11 instead of here. Run it BEFORE applying this
-- file: the divergent legacy string survives this migration, but it is
-- destroyed the first time the new application code saves the row, and the
-- rollback then refills the column from the canonical value. Preflight
-- section 11 is the only copy that will survive.
--
-- Rollback: data/031_unify_bot_config_persona_fields_rollback.sql
-- Preflight: scripts/bot_configs_persona_unification_preflight.sql
-- ---------------------------------------------------------------------------
