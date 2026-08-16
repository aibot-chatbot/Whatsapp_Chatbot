-- 040_bot_config_persona_provenance.sql
-- Record WHERE each persona value in public.bot_configs came from, so a later
-- document ingest can refresh a value the system derived without ever
-- overwriting one the client typed.
--
--     company_name          \
--     business_description   >  each gets a marker in persona_provenance
--     tone                  /
--
-- Marker values, written only by app/services/bot_config_fields.py:
--     'client_entered'  the client typed it   -> a derivation must never touch it
--     'derived'         read out of an ingested document -> refreshable
--     (key absent)      unknown -> adjudicated by value, see BACKFILL below
--
-- SHAPE CAVEAT -- same situation as 030_bot_media_attachments.sql:5-8 and
-- 039_unify_bot_config_persona_fields.sql:17-27: there is NO CREATE TABLE for
-- public.bot_configs anywhere in this repository, so its column list,
-- nullability and constraints are unknown here. Unlike 031 that does not block
-- this file, because everything below is purely ADDITIVE: adding one column
-- needs no knowledge of the columns already present, and ADD COLUMN ... IF NOT
-- EXISTS with a constant DEFAULT is a catalog-only operation on PostgreSQL 11+
-- (Supabase is well past that) -- no table rewrite, no row lock held for a scan.
-- Nothing here relaxes or tightens an existing column.
--
-- The one hazard IF NOT EXISTS creates is silence: if a column of this name
-- already existed with a different type, the ADD would be skipped and the
-- application would then write jsonb into it and fail at runtime. Step 1 turns
-- that into a loud abort before the ADD instead.
--
-- RECOMMENDED BEFORE APPLYING: run scripts/bot_configs_persona_unification_preflight.sql
-- and keep its section 1 output. This file does not require it (nothing here
-- depends on the existing shape) but the column inventory is the record that
-- step 1 had nothing to abort on.
--
-- DEPLOY ORDER -- apply this migration BEFORE deploying the application change.
-- The new code writes persona_provenance on every bot_configs INSERT and
-- UPDATE (app/services/bot_config_fields.py persona_provenance_payload); if
-- the column does not exist yet, PostgREST rejects the write with PGRST204 and
-- every settings/profile save fails loudly. Old code keeps working against the
-- migrated schema -- it simply never writes the column, and the DEFAULT '{}'
-- makes such a row read as "unknown provenance", which is exactly what it is.
--
-- BACKFILL: DELIBERATELY NONE. Every pre-existing row keeps an empty object.
-- Backfilling 'client_entered' everywhere would be a lie -- those rows include
-- every tenant that never opened the settings form and is now stuck with the
-- literal placeholders "Your Company" / "No business description provided.",
-- which is the bug this work exists to fix, and it would freeze them there
-- permanently. Backfilling 'derived' everywhere would be the opposite lie and
-- would license the first ingest to destroy values clients really did type.
-- The honest state for a pre-existing row is "unknown", and the application
-- adjudicates unknown by VALUE, not by guess: bot_config_fields.may_derive
-- allows a derivation to fill an unknown field only when it is blank or holds
-- the exact system placeholder string. Every other value is preserved.

BEGIN;

-- Step 2's ADD COLUMN takes a brief ACCESS EXCLUSIVE lock on the table; it is
-- catalog-only and instantaneous, but it still queues behind in-flight readers.
-- Bound the wait and retry the file if it trips -- every statement is
-- re-runnable. Precedent: 031:75, 028:28.
SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 1. Refuse to proceed if the name is already taken by an incompatible column.
--    ADD COLUMN IF NOT EXISTS would silently skip such a column and leave the
--    application writing a jsonb object into, say, a text or boolean field.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    v_type text;
BEGIN
    SELECT data_type
      INTO v_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name   = 'bot_configs'
       AND column_name  = 'persona_provenance';

    IF v_type IS NOT NULL AND v_type <> 'jsonb' THEN
        RAISE EXCEPTION
            'public.bot_configs.persona_provenance already exists with type %; '
            '032 requires jsonb. Resolve by hand before re-running.', v_type;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. The column. NOT NULL DEFAULT '{}' rather than nullable, so "no marker for
--    this field" has exactly one representation (an absent key) instead of two
--    (absent key, or NULL column). resolve_persona_provenance tolerates NULL
--    anyway, but one representation is one fewer branch to get wrong.
-- ---------------------------------------------------------------------------

ALTER TABLE public.bot_configs
    ADD COLUMN IF NOT EXISTS persona_provenance jsonb NOT NULL DEFAULT '{}'::jsonb;

-- ---------------------------------------------------------------------------
-- 3. Keep it an object. Guarded by pg_constraint so the file stays re-runnable
--    (precedent: 030:44-56). The marker VALUES are intentionally not
--    constrained here: they are an application vocabulary that will grow, and
--    an unrecognised marker already degrades to "unknown" in
--    resolve_persona_provenance rather than breaking a read.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'bot_configs_persona_provenance_object_check'
          AND conrelid = 'public.bot_configs'::regclass
    ) THEN
        ALTER TABLE public.bot_configs
            ADD CONSTRAINT bot_configs_persona_provenance_object_check
            CHECK (jsonb_typeof(persona_provenance) = 'object');
    END IF;
END $$;

COMMENT ON COLUMN public.bot_configs.persona_provenance IS
    'Origin of each persona value: {"company_name"|"business_description"|"tone": '
    '"client_entered"|"derived"}. An absent key means unknown (row predates 032). '
    'Written only by app/services/bot_config_fields.py.';

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification (run after COMMIT):
--
--   -- 1. The column exists and every row holds an object. Expect 0.
--   SELECT count(*) FROM public.bot_configs
--   WHERE persona_provenance IS NULL
--      OR jsonb_typeof(persona_provenance) <> 'object';
--
--   -- 2. No row was backfilled. Expect count(*) = every row in the table.
--   SELECT count(*) FROM public.bot_configs
--   WHERE persona_provenance = '{}'::jsonb;
--
--   -- 3. After the application deploy, markers should only ever be these two.
--   SELECT DISTINCT jsonb_each_text.value
--   FROM public.bot_configs, jsonb_each_text(persona_provenance);
--
-- Rollback: data/040_bot_config_persona_provenance_rollback.sql
-- ---------------------------------------------------------------------------
