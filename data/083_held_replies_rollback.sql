-- Disable holding and resolve pending reviews before rollback. Dropping this table deletes its drafts.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
ALTER TABLE public.chatbots DROP COLUMN IF EXISTS hold_risky_replies;
DROP TABLE IF EXISTS public.held_replies;
COMMIT;
