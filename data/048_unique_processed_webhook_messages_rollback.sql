-- Rollback for 048_unique_processed_webhook_messages.sql
--
-- Dropping this constraint returns Meta de-duplication to check-then-insert,
-- which can deliver a duplicate reply to a customer when Meta retries a webhook
-- while the first delivery is still generating. Only roll back if the constraint
-- itself is causing a problem.

ALTER TABLE public.processed_webhook_messages
    DROP CONSTRAINT IF EXISTS processed_webhook_messages_chatbot_id_platform_message_id_key;
