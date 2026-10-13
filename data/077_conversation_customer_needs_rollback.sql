-- Roll back migration 077: drop the customer needs card. The cards are lost;
-- conversations, messages and bookings are untouched.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.conversations DROP COLUMN IF EXISTS customer_needs;

COMMIT;
