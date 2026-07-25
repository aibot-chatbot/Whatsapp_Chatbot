/*
REVIEW-ONLY CANDIDATE ROLLBACK - DO NOT APPLY YET

This reverses schema objects and known table-grant/RLS changes introduced by
data/027_harden_crm_agent_actions.sql. It never deletes records.

Migration 027 intentionally adds no direct company_id foreign keys, so this
rollback does not drop or alter company-deletion constraints.

Important limitations:
  - The authoritative company_id backfill is intentionally not reversed.
    A full data rollback requires restoring the approved pre-migration backup.
  - Prior sequence grants must be restored from the captured preflight output;
    this file does not guess or reintroduce browser-role sequence privileges.
  - The table grants below restore the confirmed live baseline, including its
    insecure browser-role privileges. Use them only for an approved emergency
    rollback, and review the captured preflight grants first.
*/

BEGIN;

DROP INDEX IF EXISTS public.crm_leads_one_open_per_conversation_idx;
DROP INDEX IF EXISTS public.agent_actions_chatbot_status_created_at_idx;

ALTER TABLE public.agent_actions
    DROP CONSTRAINT IF EXISTS agent_actions_confidence_check,
    DROP CONSTRAINT IF EXISTS agent_actions_action_type_check,
    DROP CONSTRAINT IF EXISTS agent_actions_intent_check,
    DROP CONSTRAINT IF EXISTS agent_actions_status_check,
    DROP CONSTRAINT IF EXISTS agent_actions_company_id_not_null_check,
    DROP CONSTRAINT IF EXISTS agent_actions_conversation_id_fkey,
    DROP CONSTRAINT IF EXISTS agent_actions_chatbot_id_fkey,
    ALTER COLUMN company_id DROP NOT NULL;

ALTER TABLE public.crm_leads
    DROP CONSTRAINT IF EXISTS crm_leads_lead_type_check,
    DROP CONSTRAINT IF EXISTS crm_leads_priority_check,
    DROP CONSTRAINT IF EXISTS crm_leads_status_check,
    DROP CONSTRAINT IF EXISTS crm_leads_conversation_id_fkey,
    DROP CONSTRAINT IF EXISTS crm_leads_chatbot_id_fkey;

-- Restore the confirmed pre-migration RLS states.
ALTER TABLE public.agent_actions DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_leads ENABLE ROW LEVEL SECURITY;

-- Restore the confirmed live table grants only after comparing them with the
-- saved preflight output. PUBLIC remains without privileges.
REVOKE ALL PRIVILEGES ON TABLE public.agent_actions
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.agent_actions TO service_role;
GRANT TRUNCATE, TRIGGER, REFERENCES ON TABLE public.agent_actions TO anon, authenticated;

REVOKE ALL PRIVILEGES ON TABLE public.crm_leads
    FROM PUBLIC, anon, authenticated, service_role;
GRANT ALL PRIVILEGES ON TABLE public.crm_leads TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES
    ON TABLE public.crm_leads TO authenticated;
GRANT TRUNCATE, TRIGGER, REFERENCES ON TABLE public.crm_leads TO anon;

COMMIT;
