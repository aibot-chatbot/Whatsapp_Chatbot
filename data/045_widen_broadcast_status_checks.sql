-- 045_widen_broadcast_status_checks.sql
--
-- Widens the broadcast status vocabularies so a running send can be stopped.
--
-- Cancelling a campaign introduces two campaign statuses that did not exist
-- before -- 'cancelling' (the operator asked to stop; the worker has not
-- noticed yet) and 'cancelled' (the worker stopped) -- and one recipient
-- status, 'cancelled' (queued, never attempted).
--
-- broadcast_campaigns and broadcast_logs were created outside this directory,
-- so the live CHECK definitions are not in the repository. Both are rebuilt
-- here from the vocabulary the application actually writes. DROP ... IF EXISTS
-- makes the migration correct whether or not a constraint is currently
-- present: if there was none, this adds one; if there was, this replaces it.
--
-- Without this migration, POST /api/broadcast/campaign/<id>/cancel raises
-- Postgres 23514 and the route surfaces it as a 500 -- the same failure shape
-- 043 fixed for crm_leads.
--
-- APPLY THIS BEFORE DEPLOYING THE CODE THAT WRITES THE NEW VOCABULARY.
-- Safe on a live table: NOT VALID takes a brief lock without scanning, and
-- VALIDATE then scans without blocking writes.

BEGIN;

ALTER TABLE public.broadcast_campaigns
    DROP CONSTRAINT IF EXISTS broadcast_campaigns_status_check;

ALTER TABLE public.broadcast_campaigns
    ADD CONSTRAINT broadcast_campaigns_status_check
    CHECK (status IN (
        'draft',
        'sending',
        'completed',
        'failed',
        'cancelling',
        'cancelled'
    )) NOT VALID;

ALTER TABLE public.broadcast_campaigns
    VALIDATE CONSTRAINT broadcast_campaigns_status_check;

ALTER TABLE public.broadcast_logs
    DROP CONSTRAINT IF EXISTS broadcast_logs_status_check;

ALTER TABLE public.broadcast_logs
    ADD CONSTRAINT broadcast_logs_status_check
    CHECK (status IN (
        'pending',
        'sending',
        'sent',
        'failed',
        'cancelled'
    )) NOT VALID;

ALTER TABLE public.broadcast_logs
    VALIDATE CONSTRAINT broadcast_logs_status_check;

COMMIT;

-- Rollback: data/045_widen_broadcast_status_checks_rollback.sql
