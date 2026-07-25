/*
READ-ONLY ORPHAN DISPOSITION REVIEW

This script classifies public.agent_actions and public.crm_leads records for
human disposition review before any cleanup SQL is designed.

Every executable statement is SELECT or WITH ... SELECT. The script does not
delete, update, insert, archive, null, alter, drop, create, or otherwise modify
database rows or schema objects.

Outputs are limited to record identifiers, ownership/relationship identifiers,
status, intent or lead type, timestamps, classifications, disposition-category
suggestions, aggregate counts, and database dependency metadata. Customer
content and other sensitive row fields are intentionally excluded.

Classifications overlap by design:
  - A-D describe chatbot/conversation existence.
  - E identifies a surviving conversation owned by another chatbot.
  - F-G describe whether a null Agent Action company_id is authoritatively
    inferable from a surviving chatbot.
*/

-- 1. Agent Action identifier-only classification rows.
WITH agent_action_relationships AS (
    SELECT
        action.id,
        action.company_id,
        action.chatbot_id,
        action.conversation_id,
        action.status,
        action.intent,
        action.created_at,
        (bot.id IS NOT NULL) AS chatbot_exists,
        bot.company_id AS chatbot_company_id,
        (
            action.conversation_id IS NOT NULL
            AND conversation.id IS NOT NULL
        ) AS conversation_exists,
        conversation.chatbot_id AS conversation_chatbot_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
), classified_agent_actions AS (
    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.intent,
        relationships.created_at,
        'AA-A'::text AS classification,
        'chatbot_exists_and_conversation_exists'::text
            AS classification_description,
        'retain_unchanged_candidate'::text
            AS recommended_disposition_category
    FROM agent_action_relationships AS relationships
    WHERE relationships.chatbot_exists
      AND relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.intent,
        relationships.created_at,
        'AA-B',
        'chatbot_exists_but_conversation_missing',
        'retain_after_clearing_optional_conversation_candidate'
    FROM agent_action_relationships AS relationships
    WHERE relationships.chatbot_exists
      AND relationships.conversation_id IS NOT NULL
      AND NOT relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.intent,
        relationships.created_at,
        'AA-C',
        'chatbot_missing_but_conversation_exists',
        'manual_relationship_review'
    FROM agent_action_relationships AS relationships
    WHERE NOT relationships.chatbot_exists
      AND relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.intent,
        relationships.created_at,
        'AA-D',
        'chatbot_and_conversation_both_missing',
        'export_and_archive_or_delete_pending_approval'
    FROM agent_action_relationships AS relationships
    WHERE NOT relationships.chatbot_exists
      AND relationships.conversation_id IS NOT NULL
      AND NOT relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.intent,
        relationships.created_at,
        'AA-E',
        'conversation_belongs_to_different_chatbot',
        'manual_relationship_review'
    FROM agent_action_relationships AS relationships
    WHERE relationships.conversation_exists
      AND relationships.conversation_chatbot_id
          IS DISTINCT FROM relationships.chatbot_id

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.intent,
        relationships.created_at,
        'AA-F',
        'company_id_can_be_safely_backfilled_from_chatbot',
        'retain_after_ownership_backfill_candidate'
    FROM agent_action_relationships AS relationships
    WHERE relationships.company_id IS NULL
      AND relationships.chatbot_exists
      AND relationships.chatbot_company_id IS NOT NULL

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.intent,
        relationships.created_at,
        'AA-G',
        'company_id_cannot_be_safely_inferred',
        'export_and_archive_or_delete_pending_approval'
    FROM agent_action_relationships AS relationships
    WHERE relationships.company_id IS NULL
      AND (
          NOT relationships.chatbot_exists
          OR relationships.chatbot_company_id IS NULL
      )
)
SELECT
    id AS row_id,
    company_id,
    chatbot_id,
    conversation_id,
    status,
    intent,
    created_at,
    classification,
    classification_description,
    recommended_disposition_category
FROM classified_agent_actions
ORDER BY classification, created_at, id;

-- 2. Agent Action aggregate totals. Every required classification is returned,
-- including categories with zero matching rows.
WITH required_classifications(classification, classification_description) AS (
    VALUES
        ('AA-A', 'chatbot_exists_and_conversation_exists'),
        ('AA-B', 'chatbot_exists_but_conversation_missing'),
        ('AA-C', 'chatbot_missing_but_conversation_exists'),
        ('AA-D', 'chatbot_and_conversation_both_missing'),
        ('AA-E', 'conversation_belongs_to_different_chatbot'),
        ('AA-F', 'company_id_can_be_safely_backfilled_from_chatbot'),
        ('AA-G', 'company_id_cannot_be_safely_inferred')
), agent_action_relationships AS (
    SELECT
        action.id,
        action.company_id,
        action.chatbot_id,
        action.conversation_id,
        (bot.id IS NOT NULL) AS chatbot_exists,
        bot.company_id AS chatbot_company_id,
        (
            action.conversation_id IS NOT NULL
            AND conversation.id IS NOT NULL
        ) AS conversation_exists,
        conversation.chatbot_id AS conversation_chatbot_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
), classified_agent_actions AS (
    SELECT id, 'AA-A'::text AS classification
    FROM agent_action_relationships
    WHERE chatbot_exists AND conversation_exists
    UNION ALL
    SELECT id, 'AA-B'
    FROM agent_action_relationships
    WHERE chatbot_exists
      AND conversation_id IS NOT NULL
      AND NOT conversation_exists
    UNION ALL
    SELECT id, 'AA-C'
    FROM agent_action_relationships
    WHERE NOT chatbot_exists AND conversation_exists
    UNION ALL
    SELECT id, 'AA-D'
    FROM agent_action_relationships
    WHERE NOT chatbot_exists
      AND conversation_id IS NOT NULL
      AND NOT conversation_exists
    UNION ALL
    SELECT id, 'AA-E'
    FROM agent_action_relationships
    WHERE conversation_exists
      AND conversation_chatbot_id IS DISTINCT FROM chatbot_id
    UNION ALL
    SELECT id, 'AA-F'
    FROM agent_action_relationships
    WHERE company_id IS NULL
      AND chatbot_exists
      AND chatbot_company_id IS NOT NULL
    UNION ALL
    SELECT id, 'AA-G'
    FROM agent_action_relationships
    WHERE company_id IS NULL
      AND (NOT chatbot_exists OR chatbot_company_id IS NULL)
)
SELECT
    required.classification,
    required.classification_description,
    count(classified.id) AS row_count
FROM required_classifications AS required
LEFT JOIN classified_agent_actions AS classified
  ON classified.classification = required.classification
GROUP BY required.classification, required.classification_description
ORDER BY required.classification;

-- 3. Agent Actions with no conversation reference are not conversation
-- orphans because conversation_id is intentionally optional. They are reported
-- separately so every row can be reconciled without relabelling NULL as missing.
SELECT
    action.id AS row_id,
    action.company_id,
    action.chatbot_id,
    action.conversation_id,
    action.status,
    action.intent,
    action.created_at,
    'AA-OPTIONAL-CONVERSATION-ABSENT'::text AS classification,
    'retain_subject_to_chatbot_and_ownership_review'::text
        AS recommended_disposition_category
FROM public.agent_actions AS action
WHERE action.conversation_id IS NULL
ORDER BY action.created_at, action.id;

-- 4. Populated Agent Action company ownership mismatches. Zero rows are
-- expected from the confirmed evidence and are required before migration 027.
SELECT
    action.id AS row_id,
    action.company_id,
    action.chatbot_id,
    action.conversation_id,
    action.status,
    action.intent,
    action.created_at,
    'AA-OWNERSHIP-MISMATCH'::text AS classification,
    'manual_relationship_review'::text AS recommended_disposition_category
FROM public.agent_actions AS action
JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
WHERE action.company_id IS NOT NULL
  AND action.company_id IS DISTINCT FROM bot.company_id
ORDER BY action.created_at, action.id;

-- 5. CRM Lead identifier-only classification rows.
WITH crm_lead_relationships AS (
    SELECT
        lead.id,
        lead.company_id,
        lead.chatbot_id,
        lead.conversation_id,
        lead.status,
        lead.lead_type,
        lead.created_at,
        (bot.id IS NOT NULL) AS chatbot_exists,
        bot.company_id AS chatbot_company_id,
        (
            lead.conversation_id IS NOT NULL
            AND conversation.id IS NOT NULL
        ) AS conversation_exists,
        conversation.chatbot_id AS conversation_chatbot_id
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
), classified_crm_leads AS (
    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.lead_type,
        relationships.created_at,
        'CRM-A'::text AS classification,
        'chatbot_exists_and_conversation_exists'::text
            AS classification_description,
        'retain_unchanged_candidate'::text
            AS recommended_disposition_category
    FROM crm_lead_relationships AS relationships
    WHERE relationships.chatbot_exists
      AND relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.lead_type,
        relationships.created_at,
        'CRM-B',
        'chatbot_exists_but_conversation_missing',
        'retain_after_clearing_optional_conversation_candidate'
    FROM crm_lead_relationships AS relationships
    WHERE relationships.chatbot_exists
      AND relationships.conversation_id IS NOT NULL
      AND NOT relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.lead_type,
        relationships.created_at,
        'CRM-C',
        'chatbot_missing_but_conversation_exists',
        'manual_relationship_review'
    FROM crm_lead_relationships AS relationships
    WHERE NOT relationships.chatbot_exists
      AND relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.lead_type,
        relationships.created_at,
        'CRM-D',
        'chatbot_and_conversation_both_missing',
        'export_and_archive_or_delete_pending_approval'
    FROM crm_lead_relationships AS relationships
    WHERE NOT relationships.chatbot_exists
      AND relationships.conversation_id IS NOT NULL
      AND NOT relationships.conversation_exists

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.lead_type,
        relationships.created_at,
        'CRM-E',
        'conversation_belongs_to_different_chatbot',
        'manual_relationship_review'
    FROM crm_lead_relationships AS relationships
    WHERE relationships.conversation_exists
      AND relationships.conversation_chatbot_id
          IS DISTINCT FROM relationships.chatbot_id

    UNION ALL

    SELECT
        relationships.id,
        relationships.company_id,
        relationships.chatbot_id,
        relationships.conversation_id,
        relationships.status,
        relationships.lead_type,
        relationships.created_at,
        'CRM-F',
        'company_ownership_mismatch',
        'manual_relationship_review'
    FROM crm_lead_relationships AS relationships
    WHERE relationships.chatbot_exists
      AND relationships.company_id
          IS DISTINCT FROM relationships.chatbot_company_id
)
SELECT
    id AS row_id,
    company_id,
    chatbot_id,
    conversation_id,
    status,
    lead_type,
    created_at,
    classification,
    classification_description,
    recommended_disposition_category
FROM classified_crm_leads
ORDER BY classification, created_at, id;

-- 6. CRM Lead aggregate totals. Every required classification is returned,
-- including categories with zero matching rows.
WITH required_classifications(classification, classification_description) AS (
    VALUES
        ('CRM-A', 'chatbot_exists_and_conversation_exists'),
        ('CRM-B', 'chatbot_exists_but_conversation_missing'),
        ('CRM-C', 'chatbot_missing_but_conversation_exists'),
        ('CRM-D', 'chatbot_and_conversation_both_missing'),
        ('CRM-E', 'conversation_belongs_to_different_chatbot'),
        ('CRM-F', 'company_ownership_mismatch')
), crm_lead_relationships AS (
    SELECT
        lead.id,
        lead.company_id,
        lead.chatbot_id,
        lead.conversation_id,
        (bot.id IS NOT NULL) AS chatbot_exists,
        bot.company_id AS chatbot_company_id,
        (
            lead.conversation_id IS NOT NULL
            AND conversation.id IS NOT NULL
        ) AS conversation_exists,
        conversation.chatbot_id AS conversation_chatbot_id
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
), classified_crm_leads AS (
    SELECT id, 'CRM-A'::text AS classification
    FROM crm_lead_relationships
    WHERE chatbot_exists AND conversation_exists
    UNION ALL
    SELECT id, 'CRM-B'
    FROM crm_lead_relationships
    WHERE chatbot_exists
      AND conversation_id IS NOT NULL
      AND NOT conversation_exists
    UNION ALL
    SELECT id, 'CRM-C'
    FROM crm_lead_relationships
    WHERE NOT chatbot_exists AND conversation_exists
    UNION ALL
    SELECT id, 'CRM-D'
    FROM crm_lead_relationships
    WHERE NOT chatbot_exists
      AND conversation_id IS NOT NULL
      AND NOT conversation_exists
    UNION ALL
    SELECT id, 'CRM-E'
    FROM crm_lead_relationships
    WHERE conversation_exists
      AND conversation_chatbot_id IS DISTINCT FROM chatbot_id
    UNION ALL
    SELECT id, 'CRM-F'
    FROM crm_lead_relationships
    WHERE chatbot_exists
      AND company_id IS DISTINCT FROM chatbot_company_id
)
SELECT
    required.classification,
    required.classification_description,
    count(classified.id) AS row_count
FROM required_classifications AS required
LEFT JOIN classified_crm_leads AS classified
  ON classified.classification = required.classification
GROUP BY required.classification, required.classification_description
ORDER BY required.classification;

-- 7. CRM Leads with no conversation reference are valid under the proposed
-- nullable relationship and are reported separately for reconciliation.
SELECT
    lead.id AS row_id,
    lead.company_id,
    lead.chatbot_id,
    lead.conversation_id,
    lead.status,
    lead.lead_type,
    lead.created_at,
    'CRM-OPTIONAL-CONVERSATION-ABSENT'::text AS classification,
    'retain_subject_to_chatbot_and_ownership_review'::text
        AS recommended_disposition_category
FROM public.crm_leads AS lead
WHERE lead.conversation_id IS NULL
ORDER BY lead.created_at, lead.id;

-- 8. Incoming foreign keys that directly reference either target table.
-- These catalog rows determine whether another table has declared dependencies
-- on Agent Action or CRM Lead record IDs.
SELECT
    parent_ns.nspname AS referenced_schema,
    parent.relname AS referenced_table,
    parent_att.attname AS referenced_column,
    child_ns.nspname AS dependent_schema,
    child.relname AS dependent_table,
    child_att.attname AS dependent_column,
    constraint_row.conname AS constraint_name,
    CASE constraint_row.confupdtype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_update_action,
    CASE constraint_row.confdeltype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_delete_action,
    constraint_row.convalidated AS is_validated,
    pg_get_constraintdef(constraint_row.oid, true) AS constraint_definition
FROM pg_constraint AS constraint_row
JOIN pg_class AS parent ON parent.oid = constraint_row.confrelid
JOIN pg_namespace AS parent_ns ON parent_ns.oid = parent.relnamespace
JOIN pg_class AS child ON child.oid = constraint_row.conrelid
JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
CROSS JOIN LATERAL unnest(constraint_row.confkey, constraint_row.conkey)
    WITH ORDINALITY AS key_pair(parent_attnum, child_attnum, key_ordinality)
JOIN pg_attribute AS parent_att
  ON parent_att.attrelid = parent.oid
 AND parent_att.attnum = key_pair.parent_attnum
JOIN pg_attribute AS child_att
  ON child_att.attrelid = child.oid
 AND child_att.attnum = key_pair.child_attnum
WHERE constraint_row.contype = 'f'
  AND parent_ns.nspname = 'public'
  AND parent.relname IN ('agent_actions', 'crm_leads')
ORDER BY
    parent.relname,
    child_ns.nspname,
    child.relname,
    constraint_row.conname,
    key_pair.key_ordinality;

-- 9. Candidate non-FK dependency columns, including audit, lifecycle, history,
-- link, and mapping tables. This is catalog evidence only; it does not assume a
-- dependency exists merely because a similarly named column exists.
SELECT
    column_row.table_schema,
    column_row.table_name,
    column_row.column_name,
    column_row.data_type,
    column_row.udt_name,
    column_row.is_nullable,
    column_row.column_default,
    (
        column_row.table_name ~* '(audit|history|lifecycle|event|link|map)'
    ) AS table_name_suggests_audit_or_lifecycle_dependency
FROM information_schema.columns AS column_row
WHERE column_row.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND (
      column_row.column_name IN (
          'agent_action_id',
          'agent_actions_id',
          'crm_lead_id',
          'crm_leads_id',
          'linked_agent_action_id',
          'linked_crm_lead_id',
          'signal_id',
          'lead_id'
      )
      OR (
          column_row.table_name ~* '(agent_action|crm_lead)'
          AND column_row.column_name IN ('id', 'record_id', 'resource_id')
      )
  )
ORDER BY
    column_row.table_schema,
    column_row.table_name,
    column_row.ordinal_position;

-- 10. Views and materialized views that make either table application-visible.
-- Only object metadata and match flags are returned, not view definitions.
WITH view_dependencies AS (
    SELECT
        views.schemaname AS object_schema,
        views.viewname AS object_name,
        'view'::text AS object_type,
        views.definition
    FROM pg_views AS views

    UNION ALL

    SELECT
        materialized.schemaname,
        materialized.matviewname,
        'materialized_view',
        materialized.definition
    FROM pg_matviews AS materialized
)
SELECT
    object_schema,
    object_name,
    object_type,
    (
        definition ~* '(^|[^a-z0-9_])agent_actions([^a-z0-9_]|$)'
    ) AS references_agent_actions,
    (
        definition ~* '(^|[^a-z0-9_])crm_leads([^a-z0-9_]|$)'
    ) AS references_crm_leads
FROM view_dependencies
WHERE definition ~* '(^|[^a-z0-9_])(agent_actions|crm_leads)([^a-z0-9_]|$)'
ORDER BY object_schema, object_name;

-- 11. Functions/procedures that reference either table. Definitions are
-- inspected but not returned, limiting the result to dependency metadata.
WITH function_dependencies AS (
    SELECT
        function_row.oid,
        function_ns.nspname AS function_schema,
        function_row.proname AS function_name,
        pg_get_function_identity_arguments(function_row.oid)
            AS identity_arguments,
        function_row.prosecdef AS is_security_definer,
        pg_get_functiondef(function_row.oid) AS function_definition
    FROM pg_proc AS function_row
    JOIN pg_namespace AS function_ns
      ON function_ns.oid = function_row.pronamespace
    WHERE function_ns.nspname NOT IN ('pg_catalog', 'information_schema')
      AND function_row.prokind IN ('f', 'p')
)
SELECT
    function_schema,
    function_name,
    identity_arguments,
    is_security_definer,
    (
        function_definition
            ~* '(^|[^a-z0-9_])agent_actions([^a-z0-9_]|$)'
    ) AS references_agent_actions,
    (
        function_definition
            ~* '(^|[^a-z0-9_])crm_leads([^a-z0-9_]|$)'
    ) AS references_crm_leads
FROM function_dependencies
WHERE function_definition
    ~* '(^|[^a-z0-9_])(agent_actions|crm_leads)([^a-z0-9_]|$)'
ORDER BY function_schema, function_name, identity_arguments;

-- 12. Triggers directly attached to either target table.
SELECT
    table_ns.nspname AS table_schema,
    table_row.relname AS table_name,
    trigger_row.tgname AS trigger_name,
    trigger_row.tgenabled AS enabled_status,
    function_ns.nspname AS trigger_function_schema,
    function_row.proname AS trigger_function_name,
    pg_get_triggerdef(trigger_row.oid, true) AS trigger_definition
FROM pg_trigger AS trigger_row
JOIN pg_class AS table_row ON table_row.oid = trigger_row.tgrelid
JOIN pg_namespace AS table_ns ON table_ns.oid = table_row.relnamespace
JOIN pg_proc AS function_row ON function_row.oid = trigger_row.tgfoid
JOIN pg_namespace AS function_ns ON function_ns.oid = function_row.pronamespace
WHERE table_ns.nspname = 'public'
  AND table_row.relname IN ('agent_actions', 'crm_leads')
  AND NOT trigger_row.tgisinternal
ORDER BY table_row.relname, trigger_row.tgname;

-- 13. Orphan Agent Actions with CRM Leads linked indirectly by the same
-- non-null chatbot_id and conversation_id. This does not claim a foreign key.
WITH orphan_agent_actions AS (
    SELECT
        action.id,
        action.chatbot_id,
        action.conversation_id
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE bot.id IS NULL
       OR (
           action.conversation_id IS NOT NULL
           AND conversation.id IS NULL
       )
       OR (
           conversation.id IS NOT NULL
           AND conversation.chatbot_id IS DISTINCT FROM action.chatbot_id
       )
)
SELECT
    orphan.id AS agent_action_row_id,
    orphan.chatbot_id,
    orphan.conversation_id,
    count(lead.id) AS linked_crm_lead_count,
    array_agg(lead.id ORDER BY lead.id)
        FILTER (WHERE lead.id IS NOT NULL) AS linked_crm_lead_ids
FROM orphan_agent_actions AS orphan
LEFT JOIN public.crm_leads AS lead
  ON orphan.conversation_id IS NOT NULL
 AND lead.chatbot_id = orphan.chatbot_id
 AND lead.conversation_id = orphan.conversation_id
GROUP BY orphan.id, orphan.chatbot_id, orphan.conversation_id
ORDER BY orphan.id;

-- 14. Orphan CRM Leads with Agent Actions linked indirectly by the same
-- non-null chatbot_id and conversation_id. This does not claim a foreign key.
WITH orphan_crm_leads AS (
    SELECT
        lead.id,
        lead.chatbot_id,
        lead.conversation_id
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE bot.id IS NULL
       OR (
           lead.conversation_id IS NOT NULL
           AND conversation.id IS NULL
       )
       OR (
           conversation.id IS NOT NULL
           AND conversation.chatbot_id IS DISTINCT FROM lead.chatbot_id
       )
)
SELECT
    orphan.id AS crm_lead_row_id,
    orphan.chatbot_id,
    orphan.conversation_id,
    count(action.id) AS linked_agent_action_count,
    array_agg(action.id ORDER BY action.id)
        FILTER (WHERE action.id IS NOT NULL) AS linked_agent_action_ids
FROM orphan_crm_leads AS orphan
LEFT JOIN public.agent_actions AS action
  ON orphan.conversation_id IS NOT NULL
 AND action.chatbot_id = orphan.chatbot_id
 AND action.conversation_id = orphan.conversation_id
GROUP BY orphan.id, orphan.chatbot_id, orphan.conversation_id
ORDER BY orphan.id;
