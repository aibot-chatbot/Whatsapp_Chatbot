/*
READ-ONLY POST-CLEANUP VERIFICATION

Run only after a separately approved staging execution of migration 028.
Every executable statement is SELECT or WITH ... SELECT. This file does not
modify database rows, schema, privileges, or policies.
*/

-- 1. All 36 approved Agent Action identifiers must be absent.
WITH approved_agent_action_ids(id) AS (
    VALUES
        (1::bigint), (2), (3), (4), (5), (6), (7), (8), (9), (10),
        (11), (12), (13), (21), (22), (23), (24), (25), (26), (27),
        (28), (29), (30), (31), (32), (33), (34), (35), (36),
        (71), (72), (73), (74), (75), (102), (103)
)
SELECT
    count(action.id) AS remaining_approved_agent_action_count,
    array_agg(action.id ORDER BY action.id)
        FILTER (WHERE action.id IS NOT NULL) AS remaining_agent_action_ids
FROM approved_agent_action_ids AS approved
LEFT JOIN public.agent_actions AS action ON action.id = approved.id;

-- 2. Both approved CRM lead identifiers must be absent.
WITH approved_crm_lead_ids(id) AS (
    VALUES (1::bigint), (2::bigint)
)
SELECT
    count(lead.id) AS remaining_approved_crm_lead_count,
    array_agg(lead.id ORDER BY lead.id)
        FILTER (WHERE lead.id IS NOT NULL) AS remaining_crm_lead_ids
FROM approved_crm_lead_ids AS approved
LEFT JOIN public.crm_leads AS lead ON lead.id = approved.id;

-- 3. Migration 027 orphan-related gates: every count must be zero.
SELECT
    'agent_actions_missing_chatbot'::text AS check_name,
    count(*) AS failure_count
FROM public.agent_actions AS action
LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
WHERE bot.id IS NULL
UNION ALL
SELECT
    'agent_actions_missing_non_null_conversation',
    count(*)
FROM public.agent_actions AS action
LEFT JOIN public.conversations AS conversation
  ON conversation.id = action.conversation_id
WHERE action.conversation_id IS NOT NULL
  AND conversation.id IS NULL
UNION ALL
SELECT
    'crm_leads_missing_chatbot',
    count(*)
FROM public.crm_leads AS lead
LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
WHERE bot.id IS NULL
UNION ALL
SELECT
    'crm_leads_missing_non_null_conversation',
    count(*)
FROM public.crm_leads AS lead
LEFT JOIN public.conversations AS conversation
  ON conversation.id = lead.conversation_id
WHERE lead.conversation_id IS NOT NULL
  AND conversation.id IS NULL
ORDER BY check_name;

-- 4. Valid operational rows must remain.
SELECT
    count(*) AS valid_agent_action_count,
    (count(*) > 0) AS valid_agent_actions_remain
FROM public.agent_actions AS action
JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
LEFT JOIN public.conversations AS conversation
  ON conversation.id = action.conversation_id
WHERE action.conversation_id IS NULL
   OR (
       conversation.id IS NOT NULL
       AND conversation.chatbot_id = action.chatbot_id
   );

SELECT
    count(*) AS valid_crm_lead_count,
    (count(*) > 0) AS valid_crm_lead_remains
FROM public.crm_leads AS lead
JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
LEFT JOIN public.conversations AS conversation
  ON conversation.id = lead.conversation_id
WHERE lead.conversation_id IS NULL
   OR (
       conversation.id IS NOT NULL
       AND conversation.chatbot_id = lead.chatbot_id
   );

-- 5. Surviving ownership and relationship mismatches must be zero.
SELECT
    'agent_actions_company_vs_chatbot'::text AS check_name,
    count(*) AS mismatch_count
FROM public.agent_actions AS action
JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
WHERE action.company_id IS NOT NULL
  AND action.company_id IS DISTINCT FROM bot.company_id
UNION ALL
SELECT
    'agent_actions_conversation_vs_chatbot',
    count(*)
FROM public.agent_actions AS action
JOIN public.conversations AS conversation
  ON conversation.id = action.conversation_id
WHERE conversation.chatbot_id IS DISTINCT FROM action.chatbot_id
UNION ALL
SELECT
    'crm_leads_company_vs_chatbot',
    count(*)
FROM public.crm_leads AS lead
JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
WHERE lead.company_id IS DISTINCT FROM bot.company_id
UNION ALL
SELECT
    'crm_leads_conversation_vs_chatbot',
    count(*)
FROM public.crm_leads AS lead
JOIN public.conversations AS conversation
  ON conversation.id = lead.conversation_id
WHERE conversation.chatbot_id IS DISTINCT FROM lead.chatbot_id
ORDER BY check_name;

-- 6. Consolidated orphan-readiness signal for migration 027.
WITH orphan_failures AS (
    SELECT count(*) AS failure_count
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
       OR (
           action.conversation_id IS NOT NULL
           AND conversation.id IS NULL
       )

    UNION ALL

    SELECT count(*)
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE bot.id IS NULL
       OR (
           lead.conversation_id IS NOT NULL
           AND conversation.id IS NULL
       )
)
SELECT
    sum(failure_count) AS total_orphan_failures,
    (sum(failure_count) = 0) AS migration_027_orphan_gates_ready
FROM orphan_failures;
