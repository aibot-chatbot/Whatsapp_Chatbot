-- 074_analysis_report_hide_rollback.sql
-- Undo 074. Cleared reports become visible again (hidden_at and its index are dropped).
-- Deploy code that no longer filters on hidden_at BEFORE running this.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP FUNCTION IF EXISTS public.analysis_hide_reports(bigint, bigint, bigint, uuid[]);
DROP INDEX IF EXISTS public.analysis_reports_visible;
ALTER TABLE public.analysis_reports DROP COLUMN IF EXISTS hidden_by;
ALTER TABLE public.analysis_reports DROP COLUMN IF EXISTS hidden_at;

COMMIT;
