-- 039_unify_bot_config_persona_fields_rollback.sql
--
-- ###########################################################################
-- # NOT A MIGRATION. DO NOT APPLY AS PART OF A SEQUENTIAL RUN OF data/*.sql.#
-- # This file UNDOES the migration whose name it shares. Run it only during #
-- # a deliberate, approved rollback, and only after the application code    #
-- # has been rolled back first.                                            #
-- ###########################################################################
--
-- Filed here rather than in scripts/ only to keep it beside 031. The existing
-- house convention for rollback companions is scripts/<feature>_rollback.sql
-- (see scripts/crm_agent_actions_hardening_rollback.sql, which carries the
-- equivalent banner). Moving this file there would be more consistent; it is
-- left in place because tests/test_bot_config_persona_fields.py:22,538 pin the
-- path. Note also that data/ already contains two 029_ files, so there is no
-- automated in-order runner for this directory to mislead.
--
-- Reverses data/039_unify_bot_config_persona_fields.sql.
--
-- DEPLOY ORDER FOR THE ROLLBACK -- the mirror image of the forward order:
--   1. Roll the application code back first (the old code writes both column
--      names again and reads canonical-first, so it works against either
--      schema state).
--   2. Then run this file.
-- Running this file while the new code is still live is harmless but pointless
-- -- the new code writes NULL into the legacy columns, so it would immediately
-- re-empty what step 1 below refills.
--
-- WHAT THIS RESTORES
--   * Every legacy column is repopulated from its canonical column, so the
--     pre-031 invariant "both names hold the same value" holds again for every
--     row. Old code reading the legacy name gets the value it expects.
--   * Rows the forward migration never touched are unaffected.
--
-- WHAT THIS CANNOT RESTORE
--   * NOT NULL constraints. The forward migration ran DROP NOT NULL without
--     knowing which of the three columns actually had one, because no
--     CREATE TABLE for public.bot_configs exists in this repository and the
--     live definition was never captured here. Step 2 below is commented out
--     for exactly that reason: uncomment only the lines matching the
--     `\d+ public.bot_configs` capture taken before the forward migration.
--     Re-adding a NOT NULL that was never there would be a new, unrelated
--     schema change.
--   * DEFAULT and CHECK definitions are untouched by both files, so there is
--     nothing to restore.
--   * Pre-031 DIVERGENCE. Where a row had both names populated with DIFFERENT
--     values, the forward migration left both alone, but any write by the new
--     application code has since set the legacy column to NULL. Step 1 refills
--     it from the canonical value, so the old, differing legacy string is gone
--     for those rows. It was never served to any user -- every reader in the
--     codebase prefers the canonical column -- but it is not recoverable from
--     this file. Run the divergence report at the bottom of the forward
--     migration BEFORE applying it if that history matters.
--   * Column comments are overwritten below rather than restored. "The columns
--     had no comments before 031" is an assumption, not a fact -- verify it in
--     preflight section 2 (existing_comment). If any of the six columns did
--     carry a comment, step 3 below destroys it; restore it by hand.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Refill the legacy columns from the canonical ones.
--    Unconditional on purpose: after the forward migration the canonical
--    column is the single source of truth, so mirroring it restores the
--    pre-031 "both names agree" invariant for every row, including the rows
--    the new application code NULLed out.
-- ---------------------------------------------------------------------------

UPDATE public.bot_configs
SET business_objective = business_description
WHERE business_objective IS DISTINCT FROM business_description;

UPDATE public.bot_configs
SET response_style = tone
WHERE response_style IS DISTINCT FROM tone;

UPDATE public.bot_configs
SET prompt_text = custom_prompt
WHERE prompt_text IS DISTINCT FROM custom_prompt;

-- ---------------------------------------------------------------------------
-- 2. OPTIONAL, and only with evidence. Uncomment a line ONLY if the preflight
--    capture taken before the forward migration -- section 2 of
--    scripts/bot_configs_persona_unification_preflight.sql, column
--    is_not_null -- shows that column was NOT NULL.
--
--    TWO preconditions, not one. Step 1 above is necessary but NOT sufficient:
--    it copies the canonical column, which may itself be NULL, so a row with a
--    NULL canonical value still holds NULL in the legacy column afterwards and
--    SET NOT NULL then fails with 23502 "column contains null values". Step 1
--    deliberately does not invent a fill value, because writing '' into a
--    column that held NULL before 031 would not be a restoration.
--
--    So, before uncommenting, confirm this returns 0:
--
--      SELECT count(*) FROM public.bot_configs
--      WHERE business_description IS NULL
--         OR tone IS NULL
--         OR custom_prompt IS NULL;
--
--    (Preflight section 10 reports the same figure as null_canonical_rows.)
--    If it is not 0, decide a fill value for those specific rows as a separate,
--    recorded step -- do not blanket-coalesce.
--
-- ALTER TABLE public.bot_configs
--     ALTER COLUMN business_objective SET NOT NULL;
-- ALTER TABLE public.bot_configs
--     ALTER COLUMN response_style SET NOT NULL;
-- ALTER TABLE public.bot_configs
--     ALTER COLUMN prompt_text SET NOT NULL;
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 3. Clear the deprecation notes added by the forward migration.
-- ---------------------------------------------------------------------------

COMMENT ON COLUMN public.bot_configs.business_objective IS NULL;
COMMENT ON COLUMN public.bot_configs.response_style IS NULL;
COMMENT ON COLUMN public.bot_configs.prompt_text IS NULL;
COMMENT ON COLUMN public.bot_configs.business_description IS NULL;
COMMENT ON COLUMN public.bot_configs.tone IS NULL;
COMMENT ON COLUMN public.bot_configs.custom_prompt IS NULL;

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification (run after COMMIT; every count must be 0):
--
--   SELECT count(*) FROM public.bot_configs
--   WHERE business_objective IS DISTINCT FROM business_description
--      OR response_style     IS DISTINCT FROM tone
--      OR prompt_text        IS DISTINCT FROM custom_prompt;
-- ---------------------------------------------------------------------------
