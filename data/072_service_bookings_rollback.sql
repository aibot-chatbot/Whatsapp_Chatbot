-- 072_service_bookings_rollback.sql
-- Reverses 072_service_bookings.sql: drops public.service_bookings and
-- chatbots.booking_intake_enabled.
--
-- Effect: EVERY recorded booking request is DELETED, and every chatbot's intake switch is lost.
-- Back up first if the data matters. The bookings.csv files are NOT a backup: they omit
-- intake_key, the ownership ids, version and the confirmed/cancelled times, and they are capped.
-- For example:  pg_dump --data-only --table=public.service_bookings <connection>  > service_bookings_072.sql
-- Roll the application back with it: the pre-072 code never reads either object, but the 072
-- code's Bookings page and intake switch return errors against this schema.
--
-- The private CSV objects (<company_id>/bookings/bookings.csv under the reports storage root)
-- are NOT touched by SQL and become stale; delete them in storage if they should go too.
--
-- Re-applying 072 afterwards starts from an empty table.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP TABLE IF EXISTS public.service_bookings;
ALTER TABLE public.chatbots DROP COLUMN IF EXISTS booking_intake_enabled;

COMMIT;
