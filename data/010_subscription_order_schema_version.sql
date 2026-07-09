-- 010_subscription_order_schema_version.sql
-- Idempotent migration to add an explicit schema version marker to
-- company_subscription_orders.
--
-- Adds:
--   order_schema_version  INTEGER  nullable
--
-- Semantics:
--   NULL  — pre-migration historical order (legacy activation allowed)
--   2     — activation-atomicity order (must use Phase 4B atomic path)
--
-- Does not modify existing rows.

-- 1. Add order_schema_version column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'company_subscription_orders'
        AND column_name = 'order_schema_version'
    ) THEN
        ALTER TABLE company_subscription_orders
            ADD COLUMN order_schema_version INTEGER;
    END IF;
END $$;

-- 2. Grant permissions
GRANT ALL ON company_subscription_orders TO service_role;

-- 3. Add column comment
COMMENT ON COLUMN company_subscription_orders.order_schema_version IS
    'Schema version for this order row. NULL = historical pre-010 order (legacy activation path). 2 = activation-atomicity order (must use Phase 4B atomic claim + source-state verification). New orders must always set this to 2.';
