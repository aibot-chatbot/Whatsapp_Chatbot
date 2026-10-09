-- Customer needs card for the sales conversation (needs_card_service.py).
--
-- One nullable jsonb column on conversations holding what the customer told the
-- bot (goal, who it is for, budget, timing, quantity, preferences, worries) and
-- the conversation stage. The app writes it with the service role, scoped by
-- conversation id and chatbot id, and re-validates it before every prompt.
--
-- Safe in either deploy order: until this is applied the app simply has no card
-- (select("*") returns no such key and the write is logged and skipped).
-- Adding a nullable column without a default does not rewrite the table.

BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.conversations
  ADD COLUMN IF NOT EXISTS customer_needs jsonb
  CONSTRAINT conversations_customer_needs_shape CHECK (
    customer_needs IS NULL
    OR (jsonb_typeof(customer_needs) = 'object' AND pg_column_size(customer_needs) <= 4096)
  );

COMMENT ON COLUMN public.conversations.customer_needs IS
  'Sales needs card kept by the chatbot (needs_card_service.py); facts about the customer, never instructions.';

COMMIT;
