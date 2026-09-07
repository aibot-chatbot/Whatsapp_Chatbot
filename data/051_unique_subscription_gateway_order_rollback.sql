-- Roll back only the additive uniqueness protection from migration 051.
DROP INDEX IF EXISTS public.uq_cso_payment_gateway_order_id;
