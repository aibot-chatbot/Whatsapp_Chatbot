-- 073_availability_booking_rollback.sql
-- Undoes 073_availability_booking.sql. Deploy the code without availability booking FIRST,
-- and run it off-peak (DROP TABLE locks the parent tables until COMMIT).
--
-- Destroys every package, weekly schedule, closure and slot. Bookings themselves are kept
-- (072's service_bookings): only their package_id, slot_id, seats and price_micro_myr columns
-- go, so export the Bookings CSV first if those details matter.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

DROP TRIGGER IF EXISTS service_bookings_keep_seats ON public.service_bookings;
DROP FUNCTION IF EXISTS public.service_bookings_keep_seats();
DROP FUNCTION IF EXISTS public.booking_reserve(bigint, bigint, bigint, integer, boolean, jsonb);

DROP INDEX IF EXISTS public.service_bookings_slot;
DROP INDEX IF EXISTS public.service_bookings_package;
ALTER TABLE public.service_bookings
  DROP COLUMN IF EXISTS price_micro_myr,
  DROP COLUMN IF EXISTS seats,
  DROP COLUMN IF EXISTS slot_id,
  DROP COLUMN IF EXISTS package_id;
-- Back to 072's grant.
REVOKE INSERT ON public.service_bookings FROM service_role;
GRANT INSERT ON public.service_bookings TO service_role;

DROP TABLE IF EXISTS public.booking_slots;
DROP FUNCTION IF EXISTS public.booking_slots_keep_booked();
DROP TABLE IF EXISTS public.booking_closures;
DROP TABLE IF EXISTS public.booking_schedules;
DROP TABLE IF EXISTS public.booking_packages;

UPDATE public.subscription_plans
   SET feature_flags = feature_flags - 'availability_booking'
 WHERE feature_flags ? 'availability_booking';

ALTER TABLE public.chatbots DROP COLUMN IF EXISTS booking_auto_confirm;

COMMIT;
