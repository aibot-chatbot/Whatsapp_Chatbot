/*
READ-ONLY ORPHAN CLEANUP CANDIDATE REVIEW

This script derives three proposed cleanup batches from current database
relationships. It does not delete, update, insert, archive, null, alter, drop,
create, grant, revoke, or otherwise modify rows or schema objects.

Batch anchors:
  - CRM-ORPHAN-BATCH-001: orphan CRM lead ID 1 and orphan Agent Actions linked
    through the same non-null chatbot_id and conversation_id.
  - CRM-ORPHAN-BATCH-002: orphan CRM lead ID 2 and similarly linked actions.
  - CRM-ORPHAN-BATCH-003: orphan Agent Actions with no matching orphan CRM lead.

Lead IDs 1 and 2 identify the proposed reviewed anchors. Agent Action membership
is never hard-coded: it is derived from current relationships and orphan state.
All outputs contain identifiers and non-sensitive operational metadata only.
*/

-- 1. Identifier-only proposed batch members.
WITH orphan_crm_leads AS (
    SELECT
        lead.id,
        lead.company_id,
        lead.chatbot_id,
        lead.conversation_id,
        lead.status,
        lead.lead_type,
        lead.created_at
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE bot.id IS NULL
      AND lead.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), orphan_agent_actions AS (
    SELECT
        action.id,
        action.company_id,
        action.chatbot_id,
        action.conversation_id,
        action.status,
        action.intent,
        action.created_at
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
      AND action.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), proposed_batch_members AS (
    SELECT
        'CRM-ORPHAN-BATCH-001'::text AS proposed_batch_identifier,
        'crm_lead'::text AS record_type,
        lead.id AS row_id,
        lead.id AS linked_crm_lead_id,
        lead.company_id,
        lead.chatbot_id,
        lead.conversation_id,
        lead.status,
        lead.lead_type::text AS intent_or_lead_type,
        lead.created_at
    FROM orphan_crm_leads AS lead
    WHERE lead.id = 1

    UNION ALL

    SELECT
        'CRM-ORPHAN-BATCH-001',
        'agent_action',
        action.id,
        lead.id,
        action.company_id,
        action.chatbot_id,
        action.conversation_id,
        action.status,
        action.intent::text,
        action.created_at
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 1

    UNION ALL

    SELECT
        'CRM-ORPHAN-BATCH-002',
        'crm_lead',
        lead.id,
        lead.id,
        lead.company_id,
        lead.chatbot_id,
        lead.conversation_id,
        lead.status,
        lead.lead_type::text,
        lead.created_at
    FROM orphan_crm_leads AS lead
    WHERE lead.id = 2

    UNION ALL

    SELECT
        'CRM-ORPHAN-BATCH-002',
        'agent_action',
        action.id,
        lead.id,
        action.company_id,
        action.chatbot_id,
        action.conversation_id,
        action.status,
        action.intent::text,
        action.created_at
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 2

    UNION ALL

    SELECT
        'CRM-ORPHAN-BATCH-003',
        'agent_action',
        action.id,
        NULL::bigint AS linked_crm_lead_id,
        action.company_id,
        action.chatbot_id,
        action.conversation_id,
        action.status,
        action.intent::text,
        action.created_at
    FROM orphan_agent_actions AS action
    WHERE NOT EXISTS (
        SELECT 1
        FROM orphan_crm_leads AS lead
        WHERE lead.chatbot_id = action.chatbot_id
          AND lead.conversation_id = action.conversation_id
    )
)
SELECT
    proposed_batch_identifier,
    record_type,
    row_id,
    linked_crm_lead_id,
    company_id,
    chatbot_id,
    conversation_id,
    status,
    intent_or_lead_type,
    created_at
FROM proposed_batch_members
ORDER BY proposed_batch_identifier, record_type DESC, row_id;

-- 2. Exact identifier manifest for preservation and approval.
WITH orphan_crm_leads AS (
    SELECT lead.id, lead.chatbot_id, lead.conversation_id
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE bot.id IS NULL
      AND lead.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), orphan_agent_actions AS (
    SELECT action.id, action.chatbot_id, action.conversation_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
      AND action.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), proposed_batch_members AS (
    SELECT
        'CRM-ORPHAN-BATCH-001'::text AS proposed_batch_identifier,
        'crm_lead'::text AS record_type,
        lead.id AS row_id
    FROM orphan_crm_leads AS lead
    WHERE lead.id = 1
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-001', 'agent_action', action.id
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 1
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-002', 'crm_lead', lead.id
    FROM orphan_crm_leads AS lead
    WHERE lead.id = 2
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-002', 'agent_action', action.id
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 2
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-003', 'agent_action', action.id
    FROM orphan_agent_actions AS action
    WHERE NOT EXISTS (
        SELECT 1
        FROM orphan_crm_leads AS lead
        WHERE lead.chatbot_id = action.chatbot_id
          AND lead.conversation_id = action.conversation_id
    )
)
SELECT
    proposed_batch_identifier,
    max(row_id) FILTER (WHERE record_type = 'crm_lead') AS crm_lead_id,
    array_agg(row_id ORDER BY row_id)
        FILTER (WHERE record_type = 'agent_action') AS agent_action_ids,
    count(*) FILTER (WHERE record_type = 'crm_lead') AS crm_lead_count,
    count(*) FILTER (WHERE record_type = 'agent_action') AS agent_action_count
FROM proposed_batch_members
GROUP BY proposed_batch_identifier
ORDER BY proposed_batch_identifier;

-- 3. Expected-count gates. Every is_expected_count result must be true.
WITH orphan_crm_leads AS (
    SELECT lead.id, lead.chatbot_id, lead.conversation_id
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE bot.id IS NULL
      AND lead.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), orphan_agent_actions AS (
    SELECT action.id, action.chatbot_id, action.conversation_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
      AND action.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), proposed_batch_members AS (
    SELECT 'CRM-ORPHAN-BATCH-001'::text AS batch_id, 'crm_lead'::text AS record_type, lead.id
    FROM orphan_crm_leads AS lead WHERE lead.id = 1
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-001', 'agent_action', action.id
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 1
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-002', 'crm_lead', lead.id
    FROM orphan_crm_leads AS lead WHERE lead.id = 2
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-002', 'agent_action', action.id
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 2
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-003', 'agent_action', action.id
    FROM orphan_agent_actions AS action
    WHERE NOT EXISTS (
        SELECT 1 FROM orphan_crm_leads AS lead
        WHERE lead.chatbot_id = action.chatbot_id
          AND lead.conversation_id = action.conversation_id
    )
), expected_counts(batch_id, expected_crm_leads, expected_agent_actions) AS (
    VALUES
        ('CRM-ORPHAN-BATCH-001', 1::bigint, 29::bigint),
        ('CRM-ORPHAN-BATCH-002', 1::bigint, 3::bigint),
        ('CRM-ORPHAN-BATCH-003', 0::bigint, 4::bigint)
), actual_counts AS (
    SELECT
        batch_id,
        count(*) FILTER (WHERE record_type = 'crm_lead') AS crm_lead_count,
        count(*) FILTER (WHERE record_type = 'agent_action') AS agent_action_count
    FROM proposed_batch_members
    GROUP BY batch_id
)
SELECT
    expected.batch_id AS proposed_batch_identifier,
    expected.expected_crm_leads,
    coalesce(actual.crm_lead_count, 0) AS actual_crm_leads,
    expected.expected_agent_actions,
    coalesce(actual.agent_action_count, 0) AS actual_agent_actions,
    (
        coalesce(actual.crm_lead_count, 0) = expected.expected_crm_leads
        AND coalesce(actual.agent_action_count, 0)
            = expected.expected_agent_actions
    ) AS is_expected_count
FROM expected_counts AS expected
LEFT JOIN actual_counts AS actual ON actual.batch_id = expected.batch_id
ORDER BY expected.batch_id;

-- 4. Exclusivity gate. overlapping_record_count must be zero.
WITH orphan_crm_leads AS (
    SELECT lead.id, lead.chatbot_id, lead.conversation_id
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE bot.id IS NULL
      AND lead.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), orphan_agent_actions AS (
    SELECT action.id, action.chatbot_id, action.conversation_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
      AND action.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), memberships AS (
    SELECT 'CRM-ORPHAN-BATCH-001'::text AS batch_id, 'crm_lead'::text AS record_type, lead.id
    FROM orphan_crm_leads AS lead WHERE lead.id = 1
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-001', 'agent_action', action.id
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 1
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-002', 'crm_lead', lead.id
    FROM orphan_crm_leads AS lead WHERE lead.id = 2
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-002', 'agent_action', action.id
    FROM orphan_crm_leads AS lead
    JOIN orphan_agent_actions AS action
      ON action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE lead.id = 2
    UNION ALL
    SELECT 'CRM-ORPHAN-BATCH-003', 'agent_action', action.id
    FROM orphan_agent_actions AS action
    WHERE NOT EXISTS (
        SELECT 1 FROM orphan_crm_leads AS lead
        WHERE lead.chatbot_id = action.chatbot_id
          AND lead.conversation_id = action.conversation_id
    )
), membership_counts AS (
    SELECT record_type, id, count(DISTINCT batch_id) AS batch_count
    FROM memberships
    GROUP BY record_type, id
)
SELECT
    count(*) FILTER (WHERE batch_count > 1) AS overlapping_record_count,
    array_agg(id ORDER BY id)
        FILTER (WHERE record_type = 'agent_action' AND batch_count > 1)
        AS overlapping_agent_action_ids,
    array_agg(id ORDER BY id)
        FILTER (WHERE record_type = 'crm_lead' AND batch_count > 1)
        AS overlapping_crm_lead_ids
FROM membership_counts;

-- 5. Current-parent validity gate for every proposed row. All valid-parent
-- counts must be zero; all proposed rows must retain missing chatbot and
-- missing non-null conversation parents.
WITH proposed_records AS (
    SELECT
        'crm_lead'::text AS record_type,
        lead.id,
        lead.chatbot_id,
        lead.conversation_id
    FROM public.crm_leads AS lead
    WHERE lead.id IN (1, 2)

    UNION ALL

    SELECT
        'agent_action',
        action.id,
        action.chatbot_id,
        action.conversation_id
    FROM public.agent_actions AS action
    WHERE EXISTS (
        SELECT 1
        FROM public.crm_leads AS lead
        LEFT JOIN public.chatbots AS lead_bot ON lead_bot.id = lead.chatbot_id
        LEFT JOIN public.conversations AS lead_conversation
          ON lead_conversation.id = lead.conversation_id
        WHERE lead.id IN (1, 2)
          AND lead_bot.id IS NULL
          AND lead.conversation_id IS NOT NULL
          AND lead_conversation.id IS NULL
          AND lead.chatbot_id = action.chatbot_id
          AND lead.conversation_id = action.conversation_id
    )
    OR (
        NOT EXISTS (
            SELECT 1
            FROM public.crm_leads AS lead
            LEFT JOIN public.chatbots AS lead_bot ON lead_bot.id = lead.chatbot_id
            LEFT JOIN public.conversations AS lead_conversation
              ON lead_conversation.id = lead.conversation_id
            WHERE lead_bot.id IS NULL
              AND lead.conversation_id IS NOT NULL
              AND lead_conversation.id IS NULL
              AND lead.chatbot_id = action.chatbot_id
              AND lead.conversation_id = action.conversation_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM public.chatbots AS action_bot
            WHERE action_bot.id = action.chatbot_id
        )
        AND action.conversation_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM public.conversations AS action_conversation
            WHERE action_conversation.id = action.conversation_id
        )
    )
), current_parent_state AS (
    SELECT
        proposed.record_type,
        proposed.id,
        (bot.id IS NOT NULL) AS chatbot_now_exists,
        (conversation.id IS NOT NULL) AS conversation_now_exists,
        (proposed.conversation_id IS NULL) AS conversation_reference_is_null
    FROM proposed_records AS proposed
    LEFT JOIN public.chatbots AS bot ON bot.id = proposed.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = proposed.conversation_id
)
SELECT
    count(*) AS proposed_row_count,
    count(*) FILTER (WHERE chatbot_now_exists) AS valid_chatbot_parent_count,
    count(*) FILTER (WHERE conversation_now_exists)
        AS valid_conversation_parent_count,
    count(*) FILTER (WHERE conversation_reference_is_null)
        AS null_conversation_reference_count,
    (
        count(*) FILTER (WHERE chatbot_now_exists) = 0
        AND count(*) FILTER (WHERE conversation_now_exists) = 0
        AND count(*) FILTER (WHERE conversation_reference_is_null) = 0
    ) AS all_proposed_rows_remain_double_orphans
FROM current_parent_state;

-- 6. Completeness gate. Omitted counts must be zero. This detects new or
-- previously unaccounted-for double-orphan rows, including orphan CRM leads
-- other than the two approved anchors and linked Agent Actions outside batches.
WITH all_orphan_crm_leads AS (
    SELECT lead.id, lead.chatbot_id, lead.conversation_id
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE bot.id IS NULL
      AND lead.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), all_orphan_agent_actions AS (
    SELECT action.id, action.chatbot_id, action.conversation_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
      AND action.conversation_id IS NOT NULL
      AND conversation.id IS NULL
), proposed_crm_leads AS (
    SELECT id FROM all_orphan_crm_leads WHERE id IN (1, 2)
), proposed_agent_actions AS (
    SELECT action.id
    FROM all_orphan_agent_actions AS action
    WHERE EXISTS (
        SELECT 1
        FROM proposed_crm_leads AS proposed_lead
        JOIN all_orphan_crm_leads AS lead ON lead.id = proposed_lead.id
        WHERE lead.chatbot_id = action.chatbot_id
          AND lead.conversation_id = action.conversation_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM all_orphan_crm_leads AS lead
        WHERE lead.chatbot_id = action.chatbot_id
          AND lead.conversation_id = action.conversation_id
    )
)
SELECT
    (SELECT count(*) FROM all_orphan_crm_leads) AS all_orphan_crm_lead_count,
    (SELECT count(*) FROM proposed_crm_leads) AS proposed_crm_lead_count,
    (
        SELECT count(*)
        FROM all_orphan_crm_leads AS orphan
        WHERE NOT EXISTS (
            SELECT 1 FROM proposed_crm_leads AS proposed
            WHERE proposed.id = orphan.id
        )
    ) AS omitted_orphan_crm_lead_count,
    (
        SELECT array_agg(orphan.id ORDER BY orphan.id)
        FROM all_orphan_crm_leads AS orphan
        WHERE NOT EXISTS (
            SELECT 1 FROM proposed_crm_leads AS proposed
            WHERE proposed.id = orphan.id
        )
    ) AS omitted_orphan_crm_lead_ids,
    (SELECT count(*) FROM all_orphan_agent_actions)
        AS all_orphan_agent_action_count,
    (SELECT count(DISTINCT id) FROM proposed_agent_actions)
        AS proposed_agent_action_count,
    (
        SELECT count(*)
        FROM all_orphan_agent_actions AS orphan
        WHERE NOT EXISTS (
            SELECT 1 FROM proposed_agent_actions AS proposed
            WHERE proposed.id = orphan.id
        )
    ) AS omitted_orphan_agent_action_count,
    (
        SELECT array_agg(orphan.id ORDER BY orphan.id)
        FROM all_orphan_agent_actions AS orphan
        WHERE NOT EXISTS (
            SELECT 1 FROM proposed_agent_actions AS proposed
            WHERE proposed.id = orphan.id
        )
    ) AS omitted_orphan_agent_action_ids;

-- 7. Ownership evidence for the 36 proposed orphan Agent Actions. Expected:
-- 35 null company_id values and 1 populated company_id value. The populated
-- value is reported as an identifier only and is not treated as inferred.
WITH orphan_agent_actions AS (
    SELECT action.id, action.company_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
      AND action.conversation_id IS NOT NULL
      AND conversation.id IS NULL
)
SELECT
    count(*) AS orphan_agent_action_count,
    count(*) FILTER (WHERE company_id IS NULL) AS null_company_id_count,
    count(*) FILTER (WHERE company_id IS NOT NULL) AS populated_company_id_count,
    array_agg(id ORDER BY id)
        FILTER (WHERE company_id IS NOT NULL)
        AS populated_company_id_agent_action_ids,
    (
        count(*) = 36
        AND count(*) FILTER (WHERE company_id IS NULL) = 35
        AND count(*) FILTER (WHERE company_id IS NOT NULL) = 1
    ) AS matches_confirmed_ownership_counts
FROM orphan_agent_actions;
