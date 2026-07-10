-- 010_subscription_order_schema_version.sql

ALTER TABLE public.company_subscription_orders
    ADD COLUMN IF NOT EXISTS order_schema_version INTEGER;

GRANT ALL ON public.company_subscription_orders TO service_role;

COMMENT ON COLUMN public.company_subscription_orders.order_schema_version IS
    'NULL identifies a historical legacy order. Version 2 identifies an atomic activation order.';