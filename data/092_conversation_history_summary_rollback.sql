BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.conversations
    DROP COLUMN history_summary,
    DROP COLUMN history_summary_through_id,
    DROP COLUMN history_summary_updated_at;

COMMIT;
