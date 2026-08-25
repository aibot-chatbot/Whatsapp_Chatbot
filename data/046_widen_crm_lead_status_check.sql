-- 046_widen_crm_lead_status_check.sql
--
-- Widens crm_leads_status_check for the sales pipeline vocabulary.
--
-- Migration 027 (data/027_harden_crm_agent_actions.sql:396-397) added
--     CHECK (status IN ('new','in_progress','contacted','closed'))
-- and VALIDATEd it. That constraint is live: writing 'qualified' to
-- crm_leads returns Postgres 23514, verified read-and-revert against the
-- current database on 2026-08-21.
--
-- The application now uses new / contacted / qualified / won / lost.
-- Without this migration every qualified/won/lost write raises 23514, which
-- the route layer surfaces as an unhandled 500 rather than a clean 400.
--
-- The two retired values stay in the allow-list for one release, matching the
-- compatibility window the application layer already honours by normalising
-- in_progress -> contacted and closed -> lost on the way in
-- (app/database/crm_lead_repository.py normalize_crm_lead_status). Drop them
-- in a later migration once no client sends them.
--
-- Migration 043 is already used by the platform support-case function; this
-- change is numbered 046 after the existing 044 and 045 files.
-- APPLY THIS BEFORE DEPLOYING THE CODE THAT WRITES THE NEW VOCABULARY.
-- Safe to run on a live table: NOT VALID makes the ALTER take a brief lock
-- without scanning, and VALIDATE then scans without blocking writes.

BEGIN;

ALTER TABLE public.crm_leads
    DROP CONSTRAINT IF EXISTS crm_leads_status_check;

ALTER TABLE public.crm_leads
    ADD CONSTRAINT crm_leads_status_check
    CHECK (status IN (
        'new',
        'contacted',
        'qualified',
        'won',
        'lost',
        -- retired, accepted for one release only:
        'in_progress',
        'closed'
    )) NOT VALID;

ALTER TABLE public.crm_leads
    VALIDATE CONSTRAINT crm_leads_status_check;

-- Migration 027's partial unique index predates the qualified stage. Replace
-- it so every open-stage value, including retired in_progress during the
-- compatibility window, has the same one-open-lead invariant.
DROP INDEX IF EXISTS public.crm_leads_one_open_per_conversation_idx;

CREATE UNIQUE INDEX crm_leads_one_open_per_conversation_idx
    ON public.crm_leads (chatbot_id, conversation_id)
    WHERE conversation_id IS NOT NULL
      AND status IN ('new', 'in_progress', 'contacted', 'qualified');

COMMIT;

-- Rollback:
--   BEGIN;
--   ALTER TABLE public.crm_leads DROP CONSTRAINT IF EXISTS crm_leads_status_check;
--   ALTER TABLE public.crm_leads ADD CONSTRAINT crm_leads_status_check
--       CHECK (status IN ('new','in_progress','contacted','closed')) NOT VALID;
--   ALTER TABLE public.crm_leads VALIDATE CONSTRAINT crm_leads_status_check;
--   COMMIT;
-- Rolling back fails if any row already holds qualified/won/lost; map those
-- back to contacted/closed first.
