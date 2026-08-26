-- 047_widen_crm_lead_status_check_rollback.sql
--
-- Reverts 047 to migration 027's original crm_leads_status_check.
--
-- This FAILS if any row already holds 'qualified', 'won' or 'lost'.
-- Map those back first, then run this:
--
--   UPDATE public.crm_leads SET status = 'contacted' WHERE status = 'qualified';
--   UPDATE public.crm_leads SET status = 'closed'    WHERE status IN ('won', 'lost');
--
-- Note this loses the win/loss outcome; it is not recoverable from the status
-- column alone once collapsed back to 'closed'.

BEGIN;

ALTER TABLE public.crm_leads
    DROP CONSTRAINT IF EXISTS crm_leads_status_check;

ALTER TABLE public.crm_leads
    ADD CONSTRAINT crm_leads_status_check
    CHECK (status IN ('new', 'in_progress', 'contacted', 'closed')) NOT VALID;

ALTER TABLE public.crm_leads
    VALIDATE CONSTRAINT crm_leads_status_check;

DROP INDEX IF EXISTS public.crm_leads_one_open_per_conversation_idx;

CREATE UNIQUE INDEX crm_leads_one_open_per_conversation_idx
    ON public.crm_leads (chatbot_id, conversation_id)
    WHERE conversation_id IS NOT NULL
      AND status IN ('new', 'in_progress', 'contacted');

COMMIT;
