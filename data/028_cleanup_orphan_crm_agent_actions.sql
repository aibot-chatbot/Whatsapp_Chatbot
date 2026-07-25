/*
STAGING-FIRST / STAGING-VERIFIED CLEANUP - PRODUCTION NOT APPLIED

Approved deletion scope:
  - CRM-ORPHAN-BATCH-001: CRM lead 1 and 29 exact Agent Action IDs.
  - CRM-ORPHAN-BATCH-002: CRM lead 2 and 3 exact Agent Action IDs.
  - CRM-ORPHAN-BATCH-003: 4 exact standalone Agent Action IDs.

MANDATORY MANUAL PREREQUISITES BEFORE EXECUTION:
  1. Take a restorable staging database backup.
  2. Export the exact 38 approved records to the authorized restricted archive.
  3. Record the export manifest identifier.
  4. Record and independently verify the SHA-256 checksum.
  5. Verify the authorized archive location and restoration owner.

This migration does not claim those prerequisites have been completed. Do not
execute it until their evidence is attached to the approved change record.

Restoration after commit requires the approved database backup/export. This
migration intentionally contains no attempt to reconstruct deleted row data.

Staging result recorded 2026-07-25: exactly 36 Agent Actions and 2 CRM leads
were deleted; verification found zero remaining orphans and no valid-row change.
*/

BEGIN;

SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;

DO $orphan_cleanup$
DECLARE
    batch_001_crm_lead_ids bigint[] := ARRAY[1]::bigint[];
    batch_001_agent_action_ids bigint[] := ARRAY[
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
        22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
        71, 72, 73, 74, 102, 103
    ]::bigint[];
    batch_002_crm_lead_ids bigint[] := ARRAY[2]::bigint[];
    batch_002_agent_action_ids bigint[] := ARRAY[11, 12, 21]::bigint[];
    batch_003_crm_lead_ids bigint[] := ARRAY[]::bigint[];
    batch_003_agent_action_ids bigint[] := ARRAY[13, 35, 36, 75]::bigint[];
    approved_crm_lead_ids bigint[];
    approved_agent_action_ids bigint[];
    actual_count bigint;
    expected_count bigint;
    deleted_agent_action_count bigint;
    deleted_crm_lead_count bigint;
    valid_agent_action_count_before bigint;
    valid_agent_action_count_after bigint;
    valid_crm_lead_count_before bigint;
    valid_crm_lead_count_after bigint;
BEGIN
    approved_crm_lead_ids :=
        batch_001_crm_lead_ids
        || batch_002_crm_lead_ids
        || batch_003_crm_lead_ids;
    approved_agent_action_ids :=
        batch_001_agent_action_ids
        || batch_002_agent_action_ids
        || batch_003_agent_action_ids;

    -- The manifest itself must retain the approved cardinalities.
    IF cardinality(batch_001_crm_lead_ids) <> 1
       OR cardinality(batch_001_agent_action_ids) <> 29 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 001 manifest must contain 1 CRM lead and 29 Agent Actions.';
    END IF;

    IF cardinality(batch_002_crm_lead_ids) <> 1
       OR cardinality(batch_002_agent_action_ids) <> 3 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 002 manifest must contain 1 CRM lead and 3 Agent Actions.';
    END IF;

    IF cardinality(batch_003_crm_lead_ids) <> 0
       OR cardinality(batch_003_agent_action_ids) <> 4 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 003 manifest must contain 0 CRM leads and 4 Agent Actions.';
    END IF;

    IF cardinality(approved_crm_lead_ids) <> 2
       OR cardinality(approved_agent_action_ids) <> 36 THEN
        RAISE EXCEPTION
            'Cleanup stopped: combined manifest must contain 2 CRM leads and 36 Agent Actions.';
    END IF;

    -- No identifier may appear in more than one batch.
    SELECT count(DISTINCT manifest.id), count(*)
    INTO actual_count, expected_count
    FROM unnest(approved_crm_lead_ids) AS manifest(id);
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION
            'Cleanup stopped: a CRM lead identifier appears in multiple batches.';
    END IF;

    SELECT count(DISTINCT manifest.id), count(*)
    INTO actual_count, expected_count
    FROM unnest(approved_agent_action_ids) AS manifest(id);
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION
            'Cleanup stopped: an Agent Action identifier appears in multiple batches.';
    END IF;

    -- Lock only the exact approved rows so their state cannot change between
    -- validation and deletion.
    PERFORM lead.id
    FROM public.crm_leads AS lead
    WHERE lead.id = ANY(approved_crm_lead_ids)
    FOR UPDATE;

    PERFORM action.id
    FROM public.agent_actions AS action
    WHERE action.id = ANY(approved_agent_action_ids)
    FOR UPDATE;

    -- Every exact approved identifier must still exist.
    SELECT count(*) INTO actual_count
    FROM public.crm_leads AS lead
    WHERE lead.id = ANY(approved_crm_lead_ids);
    IF actual_count <> 2 THEN
        RAISE EXCEPTION
            'Cleanup stopped: expected 2 exact CRM lead identifiers, found %.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    WHERE action.id = ANY(approved_agent_action_ids);
    IF actual_count <> 36 THEN
        RAISE EXCEPTION
            'Cleanup stopped: expected 36 exact Agent Action identifiers, found %.',
            actual_count;
    END IF;

    -- Every approved row must remain a double orphan: chatbot missing and
    -- non-null conversation reference pointing to a missing conversation.
    SELECT count(*) INTO actual_count
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE lead.id = ANY(approved_crm_lead_ids)
      AND bot.id IS NULL
      AND lead.conversation_id IS NOT NULL
      AND conversation.id IS NULL;
    IF actual_count <> 2 THEN
        RAISE EXCEPTION
            'Cleanup stopped: all 2 approved CRM leads must remain double orphans; found %.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE action.id = ANY(approved_agent_action_ids)
      AND bot.id IS NULL
      AND action.conversation_id IS NOT NULL
      AND conversation.id IS NULL;
    IF actual_count <> 36 THEN
        RAISE EXCEPTION
            'Cleanup stopped: all 36 approved Agent Actions must remain double orphans; found %.',
            actual_count;
    END IF;

    -- Batch 001 must still be lead 1 plus exactly its 29 approved actions,
    -- matched by the same non-null chatbot_id and conversation_id.
    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    JOIN public.crm_leads AS lead
      ON lead.id = batch_001_crm_lead_ids[1]
     AND action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE action.id = ANY(batch_001_agent_action_ids)
      AND lead.conversation_id IS NOT NULL;
    IF actual_count <> 29 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 001 relationship expected 29 matching Agent Actions, found %.',
            actual_count;
    END IF;

    -- No action outside the approved batch 001 manifest may currently share
    -- lead 1's orphan relationship key.
    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    JOIN public.crm_leads AS lead
      ON lead.id = batch_001_crm_lead_ids[1]
     AND action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE NOT (action.id = ANY(batch_001_agent_action_ids));
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 001 relationship has % unapproved Agent Actions.',
            actual_count;
    END IF;

    -- Batch 002 must still be lead 2 plus exactly its 3 approved actions.
    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    JOIN public.crm_leads AS lead
      ON lead.id = batch_002_crm_lead_ids[1]
     AND action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE action.id = ANY(batch_002_agent_action_ids)
      AND lead.conversation_id IS NOT NULL;
    IF actual_count <> 3 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 002 relationship expected 3 matching Agent Actions, found %.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    JOIN public.crm_leads AS lead
      ON lead.id = batch_002_crm_lead_ids[1]
     AND action.chatbot_id = lead.chatbot_id
     AND action.conversation_id = lead.conversation_id
    WHERE NOT (action.id = ANY(batch_002_agent_action_ids));
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 002 relationship has % unapproved Agent Actions.',
            actual_count;
    END IF;

    -- Batch 003 must remain four standalone actions with no CRM lead sharing
    -- either action's non-null chatbot_id and conversation_id.
    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    WHERE action.id = ANY(batch_003_agent_action_ids)
      AND NOT EXISTS (
          SELECT 1
          FROM public.crm_leads AS lead
          WHERE lead.chatbot_id = action.chatbot_id
            AND lead.conversation_id = action.conversation_id
      );
    IF actual_count <> 4 THEN
        RAISE EXCEPTION
            'Cleanup stopped: batch 003 expected 4 standalone Agent Actions, found %.',
            actual_count;
    END IF;

    -- Completeness: the exact manifest must contain every row with either a
    -- missing chatbot or a missing non-null conversation. Any newly discovered
    -- orphan stops the transaction rather than broadening deletion scope.
    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE (
        bot.id IS NULL
        OR (
            action.conversation_id IS NOT NULL
            AND conversation.id IS NULL
        )
    )
      AND NOT (action.id = ANY(approved_agent_action_ids));
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % orphan Agent Actions are omitted from the approved manifest.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE (
        bot.id IS NULL
        OR (
            lead.conversation_id IS NOT NULL
            AND conversation.id IS NULL
        )
    )
      AND NOT (lead.id = ANY(approved_crm_lead_ids));
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % orphan CRM leads are omitted from the approved manifest.',
            actual_count;
    END IF;

    -- Preserve proof that exact-ID deletion does not alter valid rows.
    SELECT count(*) INTO valid_agent_action_count_before
    FROM public.agent_actions AS action
    JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE action.conversation_id IS NULL
       OR (
           conversation.id IS NOT NULL
           AND conversation.chatbot_id = action.chatbot_id
       );

    SELECT count(*) INTO valid_crm_lead_count_before
    FROM public.crm_leads AS lead
    JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE lead.conversation_id IS NULL
       OR (
           conversation.id IS NOT NULL
           AND conversation.chatbot_id = lead.chatbot_id
       );

    -- Delete children first, using only the immutable approved ID array.
    DELETE FROM public.agent_actions AS action
    WHERE action.id = ANY(approved_agent_action_ids);
    GET DIAGNOSTICS deleted_agent_action_count = ROW_COUNT;
    IF deleted_agent_action_count <> 36 THEN
        RAISE EXCEPTION
            'Cleanup stopped: expected to delete 36 Agent Actions, deleted %.',
            deleted_agent_action_count;
    END IF;

    -- Delete the two approved CRM lead anchors second, also by exact ID only.
    DELETE FROM public.crm_leads AS lead
    WHERE lead.id = ANY(approved_crm_lead_ids);
    GET DIAGNOSTICS deleted_crm_lead_count = ROW_COUNT;
    IF deleted_crm_lead_count <> 2 THEN
        RAISE EXCEPTION
            'Cleanup stopped: expected to delete 2 CRM leads, deleted %.',
            deleted_crm_lead_count;
    END IF;

    -- Exact approved identifiers must no longer exist.
    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    WHERE action.id = ANY(approved_agent_action_ids);
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % approved Agent Action identifiers remain.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.crm_leads AS lead
    WHERE lead.id = ANY(approved_crm_lead_ids);
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % approved CRM lead identifiers remain.',
            actual_count;
    END IF;

    -- Migration 027 orphan prerequisites must now be clear.
    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    LEFT JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    WHERE bot.id IS NULL;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % Agent Actions still reference missing chatbots.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.agent_actions AS action
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE action.conversation_id IS NOT NULL
      AND conversation.id IS NULL;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % Agent Actions still reference missing conversations.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.crm_leads AS lead
    LEFT JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    WHERE bot.id IS NULL;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % CRM leads still reference missing chatbots.',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM public.crm_leads AS lead
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE lead.conversation_id IS NOT NULL
      AND conversation.id IS NULL;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION
            'Cleanup stopped: % CRM leads still reference missing conversations.',
            actual_count;
    END IF;

    SELECT count(*) INTO valid_agent_action_count_after
    FROM public.agent_actions AS action
    JOIN public.chatbots AS bot ON bot.id = action.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = action.conversation_id
    WHERE action.conversation_id IS NULL
       OR (
           conversation.id IS NOT NULL
           AND conversation.chatbot_id = action.chatbot_id
       );

    SELECT count(*) INTO valid_crm_lead_count_after
    FROM public.crm_leads AS lead
    JOIN public.chatbots AS bot ON bot.id = lead.chatbot_id
    LEFT JOIN public.conversations AS conversation
      ON conversation.id = lead.conversation_id
    WHERE lead.conversation_id IS NULL
       OR (
           conversation.id IS NOT NULL
           AND conversation.chatbot_id = lead.chatbot_id
       );

    IF valid_agent_action_count_after <> valid_agent_action_count_before THEN
        RAISE EXCEPTION
            'Cleanup stopped: valid Agent Action count changed from % to %.',
            valid_agent_action_count_before,
            valid_agent_action_count_after;
    END IF;

    IF valid_crm_lead_count_after <> valid_crm_lead_count_before THEN
        RAISE EXCEPTION
            'Cleanup stopped: valid CRM lead count changed from % to %.',
            valid_crm_lead_count_before,
            valid_crm_lead_count_after;
    END IF;
END
$orphan_cleanup$;

COMMIT;
