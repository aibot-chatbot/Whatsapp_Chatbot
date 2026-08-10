-- 032_bot_config_persona_provenance_rollback.sql
-- Undo data/032_bot_config_persona_provenance.sql.
--
-- WHAT THIS CANNOT RESTORE. Everything. The provenance record is information
-- that exists nowhere else: it is created at write time by observing WHO wrote
-- a value, and no later inspection of bot_configs can recover it. Dropping the
-- column destroys, irreversibly, the distinction between "the client typed
-- this" and "we derived this from their document" for every row that had one.
-- Re-applying 032 afterwards brings back an empty column, not the markers.
--
-- The persona VALUES themselves are untouched and survive this file intact --
-- company_name, business_description and tone are separate columns and are not
-- referenced here. What is lost is only the ability to protect a client
-- override from the next document ingest: after this rollback every row is
-- "unknown provenance" again, and bot_config_fields.may_derive falls back to
-- its value-based rule (blank or exact system placeholder is derivable, any
-- other value is preserved). No value is destroyed by that fallback, but a
-- client override that happens to equal a placeholder is no longer protected.
--
-- EXPORT BEFORE RUNNING -- this is the only copy:
--
--   SELECT id, chatbot_id, profile_name, persona_provenance
--   FROM public.bot_configs
--   WHERE persona_provenance <> '{}'::jsonb
--   ORDER BY id;
--
-- DEPLOY ORDER -- roll the APPLICATION back first, then run this file. The
-- 032 application code writes persona_provenance on every bot_configs INSERT
-- and UPDATE; running this against live 032 code makes every settings and
-- profile save fail with PGRST204. Pre-032 code never mentions the column and
-- is unaffected by its absence.

BEGIN;

SET LOCAL lock_timeout = '5s';

-- Dropping the column drops its CHECK constraint and its COMMENT with it; no
-- separate statement is needed, and IF EXISTS keeps the file re-runnable.
ALTER TABLE public.bot_configs
    DROP COLUMN IF EXISTS persona_provenance;

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification (run after COMMIT; expect 0 rows):
--
--   SELECT column_name FROM information_schema.columns
--   WHERE table_schema = 'public' AND table_name = 'bot_configs'
--     AND column_name = 'persona_provenance';
--
-- Forward migration: data/032_bot_config_persona_provenance.sql
-- ---------------------------------------------------------------------------
