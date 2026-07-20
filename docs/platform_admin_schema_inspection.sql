-- Phase 1 platform-admin schema inspection (read-only).
-- Run this file manually in the Supabase SQL Editor before finalizing or
-- applying any platform-admin migration. Every statement is SELECT-only.

-- 1. Columns, exact PostgreSQL types, nullability, defaults, and identity state.
SELECT
    c.table_schema,
    c.table_name,
    c.ordinal_position,
    c.column_name,
    c.data_type,
    c.udt_schema,
    c.udt_name,
    c.is_nullable,
    c.column_default,
    c.is_identity,
    c.identity_generation
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.table_name IN (
      'users',
      'companies',
      'company_subscriptions',
      'company_subscription_orders',
      'company_ai_credit_balances',
      'ai_credit_transactions',
      'ai_usage_logs'
  )
ORDER BY c.table_name, c.ordinal_position;

-- 2. Primary keys, unique constraints, foreign keys, and check constraints.
-- pg_get_constraintdef preserves details such as composite keys and ON DELETE.
SELECT
    ns.nspname AS table_schema,
    tbl.relname AS table_name,
    con.conname AS constraint_name,
    CASE con.contype
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'u' THEN 'UNIQUE'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'c' THEN 'CHECK'
        WHEN 'x' THEN 'EXCLUSION'
        ELSE con.contype::text
    END AS constraint_type,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS tbl
  ON tbl.oid = con.conrelid
JOIN pg_namespace AS ns
  ON ns.oid = tbl.relnamespace
WHERE ns.nspname = 'public'
  AND tbl.relname IN (
      'users',
      'companies',
      'company_subscriptions',
      'company_subscription_orders',
      'company_ai_credit_balances',
      'ai_credit_transactions',
      'ai_usage_logs'
  )
ORDER BY tbl.relname, constraint_type, con.conname;

-- 3. Foreign keys in column-by-column form, including update/delete behavior.
SELECT
    src_ns.nspname AS source_schema,
    src.relname AS source_table,
    con.conname AS constraint_name,
    src_col.attname AS source_column,
    target_ns.nspname AS target_schema,
    target.relname AS target_table,
    target_col.attname AS target_column,
    CASE con.confupdtype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_update,
    CASE con.confdeltype
        WHEN 'a' THEN 'NO ACTION'
        WHEN 'r' THEN 'RESTRICT'
        WHEN 'c' THEN 'CASCADE'
        WHEN 'n' THEN 'SET NULL'
        WHEN 'd' THEN 'SET DEFAULT'
    END AS on_delete,
    key_cols.position
FROM pg_constraint AS con
JOIN pg_class AS src
  ON src.oid = con.conrelid
JOIN pg_namespace AS src_ns
  ON src_ns.oid = src.relnamespace
JOIN pg_class AS target
  ON target.oid = con.confrelid
JOIN pg_namespace AS target_ns
  ON target_ns.oid = target.relnamespace
CROSS JOIN LATERAL unnest(con.conkey, con.confkey)
    WITH ORDINALITY AS key_cols(source_attnum, target_attnum, position)
JOIN pg_attribute AS src_col
  ON src_col.attrelid = src.oid
 AND src_col.attnum = key_cols.source_attnum
JOIN pg_attribute AS target_col
  ON target_col.attrelid = target.oid
 AND target_col.attnum = key_cols.target_attnum
WHERE con.contype = 'f'
  AND src_ns.nspname = 'public'
  AND src.relname IN (
      'users',
      'companies',
      'company_subscriptions',
      'company_subscription_orders',
      'company_ai_credit_balances',
      'ai_credit_transactions',
      'ai_usage_logs'
  )
ORDER BY src.relname, con.conname, key_cols.position;

-- 4. All indexes, including indexes that enforce uniqueness without a named
-- UNIQUE constraint (for example, partial unique indexes).
SELECT
    schemaname AS table_schema,
    tablename AS table_name,
    indexname AS index_name,
    indexdef AS index_definition
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN (
      'users',
      'companies',
      'company_subscriptions',
      'company_subscription_orders',
      'company_ai_credit_balances',
      'ai_credit_transactions',
      'ai_usage_logs'
  )
ORDER BY tablename, indexname;

-- 5. Every users-table check constraint. This is the authoritative check for
-- whether role is constrained to owner/admin/member in the live schema.
SELECT
    con.conname AS constraint_name,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
WHERE con.conrelid = 'public.users'::regclass
  AND con.contype = 'c'
ORDER BY con.conname;

-- 6. Constraints and indexes whose definitions mention the users.role column.
-- This supplements the prior query in case role enforcement uses an expression
-- or unique index rather than a conventional role-named check constraint.
SELECT 'constraint' AS object_type,
       con.conname AS object_name,
       pg_get_constraintdef(con.oid, true) AS definition
FROM pg_constraint AS con
WHERE con.conrelid = 'public.users'::regclass
  AND pg_get_constraintdef(con.oid, true) ILIKE '%role%'
UNION ALL
SELECT 'index' AS object_type,
       idx.indexname AS object_name,
       idx.indexdef AS definition
FROM pg_indexes AS idx
WHERE idx.schemaname = 'public'
  AND idx.tablename = 'users'
  AND idx.indexdef ILIKE '%role%'
ORDER BY object_type, object_name;

-- 7. Timestamp-maintenance triggers. The repository normally supplies UTC
-- values from the application and uses DEFAULT NOW(); this confirms whether
-- the live database also updates updated_at through a trigger.
SELECT
    event_object_schema AS table_schema,
    event_object_table AS table_name,
    trigger_name,
    event_manipulation,
    action_timing,
    action_statement
FROM information_schema.triggers
WHERE event_object_schema = 'public'
  AND event_object_table IN (
      'users',
      'companies',
      'company_subscriptions',
      'company_subscription_orders',
      'company_ai_credit_balances',
      'ai_credit_transactions',
      'ai_usage_logs'
  )
ORDER BY event_object_table, trigger_name, event_manipulation;

