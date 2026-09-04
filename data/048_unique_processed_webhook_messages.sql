-- 048: make Meta WhatsApp webhook de-duplication race-proof.
--
-- processed_webhook_messages is the de-dup ledger for inbound Meta messages,
-- but it was the only one of the three ledgers without a uniqueness guarantee:
--
--   processed_telegram_updates    UNIQUE (telegram_channel_id, update_id)   OK
--   processed_wasender_messages   UNIQUE (wasender_channel_id, message_id)  OK
--   processed_webhook_messages    -- none --                                <- this
--
-- Without it the application can only do check-then-insert, which is a race:
-- when Meta retries a delivery while the first one is still generating a reply,
-- both requests read "not processed" and the customer receives the answer twice.
-- With the constraint the INSERT itself becomes the claim, and the loser gets a
-- 23505 it can treat as "already handled".
--
-- Safe to apply: the table was empty at authoring time (0 rows, 0 duplicate
-- groups, no NULLs in either column). If that has changed in your environment,
-- run the preflight below FIRST and clear the duplicates, or the constraint
-- creation will fail and roll back on its own.
--
--   SELECT chatbot_id, platform_message_id, count(*)
--   FROM public.processed_webhook_messages
--   GROUP BY chatbot_id, platform_message_id
--   HAVING count(*) > 1;
--
-- Rollback: 048_unique_processed_webhook_messages_rollback.sql

ALTER TABLE public.processed_webhook_messages
    ADD CONSTRAINT processed_webhook_messages_chatbot_id_platform_message_id_key
    UNIQUE (chatbot_id, platform_message_id);
