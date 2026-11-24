BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.conversations
    ADD COLUMN history_summary text NULL CHECK (char_length(history_summary) <= 1500),
    ADD COLUMN history_summary_through_id bigint NULL,
    ADD COLUMN history_summary_updated_at timestamptz NULL;

COMMIT;
