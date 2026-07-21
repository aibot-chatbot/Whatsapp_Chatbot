-- Final production read-only inspection for tenant identity drift.
-- Expected Supabase project reference: parjsxypengvubziwwjp.
-- Confirm the project reference in the Supabase UI before running any section.
-- Targets: companies 1/20, user 3, and chatbots 26/29/38.
--
-- Every executable statement in this file is SELECT or WITH ... SELECT.
-- Run section 1 first, retain its output, then run the generated count queries
-- from sections 3-5 after human review. Generated statements are SELECT-only.
-- Do not change projections to SELECT *. This script intentionally excludes
-- passwords, OTPs, tokens, API keys, channel credentials, webhook/provider
-- payloads, message/prompt content, payment identifiers, and checkout URLs.

-- 1. Catalog-driven ownership discovery.

-- Every public table containing a direct company_id or chatbot_id column.
SELECT
    c.table_schema,
    c.table_name,
    c.column_name,
    c.data_type,
    c.udt_name,
    c.is_nullable,
    c.column_default
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name IN ('company_id', 'chatbot_id')
ORDER BY c.column_name, c.table_name;

-- Every public foreign key that directly references companies.
SELECT
    child_ns.nspname AS child_schema,
    child.relname AS child_table,
    con.conname AS constraint_name,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS child ON child.oid = con.conrelid
JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
WHERE con.contype = 'f'
  AND con.confrelid = 'public.companies'::regclass
ORDER BY child_ns.nspname, child.relname, con.conname;

-- Every public foreign key that directly references chatbots.
SELECT
    child_ns.nspname AS child_schema,
    child.relname AS child_table,
    con.conname AS constraint_name,
    pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_constraint AS con
JOIN pg_class AS child ON child.oid = con.conrelid
JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
WHERE con.contype = 'f'
  AND con.confrelid = 'public.chatbots'::regclass
ORDER BY child_ns.nspname, child.relname, con.conname;

-- Recursive foreign-key descendants of companies and chatbots. This exposes
-- indirect paths even when the child column is not named company_id/chatbot_id.
WITH RECURSIVE roots AS (
    SELECT 'companies'::text AS root_name, 'public.companies'::regclass::oid AS root_oid
    UNION ALL
    SELECT 'chatbots', 'public.chatbots'::regclass::oid
), fk_edges AS (
    SELECT
        con.oid AS constraint_oid,
        con.conname AS constraint_name,
        con.conrelid AS child_oid,
        con.confrelid AS parent_oid,
        pg_get_constraintdef(con.oid, true) AS constraint_definition
    FROM pg_constraint AS con
    JOIN pg_class AS child ON child.oid = con.conrelid
    JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
    WHERE con.contype = 'f'
      AND child_ns.nspname = 'public'
), lineage AS (
    SELECT
        r.root_name,
        1 AS depth,
        e.constraint_oid,
        e.constraint_name,
        e.parent_oid,
        e.child_oid,
        e.constraint_definition,
        ARRAY[e.parent_oid, e.child_oid]::oid[] AS visited
    FROM roots AS r
    JOIN fk_edges AS e ON e.parent_oid = r.root_oid

    UNION ALL

    SELECT
        l.root_name,
        l.depth + 1,
        e.constraint_oid,
        e.constraint_name,
        e.parent_oid,
        e.child_oid,
        e.constraint_definition,
        l.visited || e.child_oid
    FROM lineage AS l
    JOIN fk_edges AS e ON e.parent_oid = l.child_oid
    WHERE NOT e.child_oid = ANY(l.visited)
)
SELECT
    l.root_name,
    l.depth,
    l.parent_oid::regclass AS parent_table,
    l.child_oid::regclass AS child_table,
    l.constraint_name,
    l.constraint_definition
FROM lineage AS l
ORDER BY l.root_name, l.depth, l.parent_oid::regclass::text,
         l.child_oid::regclass::text, l.constraint_name;

-- Ownership-path columns used for indirect count generation.
SELECT
    c.table_schema,
    c.table_name,
    c.column_name,
    c.data_type,
    c.is_nullable
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name IN (
      'company_id', 'chatbot_id', 'conversation_id', 'campaign_id',
      'knowledge_file_id', 'file_id', 'telegram_channel_id',
      'wasender_channel_id', 'whatsapp_channel_id'
  )
ORDER BY c.table_name, c.ordinal_position;

-- Confirm the reported absent table and identify similarly named live objects.
SELECT
    n.nspname AS object_schema,
    c.relname AS object_name,
    c.relkind AS object_kind
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname ILIKE '%media%attachment%'
ORDER BY c.relname;

-- 2. Focused canonical and candidate-orphan identity.

SELECT
    c.id,
    c.company_name,
    c.business_type,
    c.status,
    c.contact_email,
    c.contact_phone,
    c.created_at,
    c.updated_at
FROM public.companies AS c
WHERE c.id IN (1, 20)
ORDER BY c.id;

SELECT
    u.id,
    u.company_id,
    u.full_name,
    u.email,
    u.role,
    u.status,
    u.is_verified,
    u.created_at,
    u.updated_at
FROM public.users AS u
WHERE u.id = 3
   OR u.company_id IN (1, 20)
   OR lower(u.email) IN ('iomaths123@gmail.com', 'abc@gmail.com')
ORDER BY u.id;

SELECT
    lower(u.email) AS normalized_email,
    count(*) AS user_row_count,
    array_agg(u.id ORDER BY u.id) AS user_ids,
    array_agg(u.company_id ORDER BY u.id) AS company_ids
FROM public.users AS u
WHERE lower(u.email) IN ('iomaths123@gmail.com', 'abc@gmail.com')
GROUP BY lower(u.email)
ORDER BY normalized_email;

SELECT
    b.id,
    b.company_id,
    b.bot_name,
    b.status,
    b.is_active,
    b.deleted_at,
    b.created_at,
    b.updated_at
FROM public.chatbots AS b
WHERE b.id IN (26, 29, 38)
   OR b.company_id IN (1, 20)
ORDER BY b.company_id, b.id;

-- Safe billing ownership summary. Payment and provider identifiers are omitted.
SELECT
    cs.id,
    cs.company_id,
    cs.plan_id,
    sp.code AS plan_code,
    sp.name AS plan_name,
    cs.status,
    cs.current_period_start,
    cs.current_period_end,
    cs.created_at,
    cs.updated_at
FROM public.company_subscriptions AS cs
LEFT JOIN public.subscription_plans AS sp ON sp.id = cs.plan_id
WHERE cs.company_id IN (1, 20)
ORDER BY cs.company_id, cs.created_at, cs.id;

SELECT
    o.company_id,
    count(*) AS subscription_order_count,
    min(o.created_at) AS first_order_at,
    max(o.created_at) AS last_order_at
FROM public.company_subscription_orders AS o
WHERE o.company_id IN (1, 20)
GROUP BY o.company_id
ORDER BY o.company_id;

SELECT
    b.company_id,
    b.subscription_id,
    b.period_start,
    b.period_end,
    b.included_balance_micro_myr,
    b.topup_balance_micro_myr,
    b.created_at,
    b.updated_at
FROM public.company_ai_credit_balances AS b
WHERE b.company_id IN (1, 20)
ORDER BY b.company_id;

SELECT company_id, count(*) AS ai_credit_transaction_count,
       min(created_at) AS first_transaction_at,
       max(created_at) AS last_transaction_at
FROM public.ai_credit_transactions
WHERE company_id IN (1, 20)
GROUP BY company_id
ORDER BY company_id;

SELECT company_id, count(*) AS ai_usage_count,
       min(created_at) AS first_usage_at,
       max(created_at) AS last_usage_at
FROM public.ai_usage_logs
WHERE company_id IN (1, 20)
GROUP BY company_id
ORDER BY company_id;

-- Platform-admin linkage through users. No audit metadata is selected.
SELECT
    pau.id AS platform_admin_user_id,
    pau.user_id,
    pau.is_active,
    pau.created_by_user_id,
    pau.created_at,
    pau.updated_at,
    u.company_id,
    u.email,
    u.role AS tenant_role,
    u.status AS user_status
FROM public.platform_admin_users AS pau
JOIN public.users AS u ON u.id = pau.user_id
WHERE u.id = 3 OR u.company_id IN (1, 20)
ORDER BY pau.id;

SELECT
    u.company_id,
    count(e.id) AS platform_admin_audit_event_count,
    min(e.created_at) AS first_event_at,
    max(e.created_at) AS last_event_at
FROM public.platform_admin_users AS pau
JOIN public.users AS u ON u.id = pau.user_id
LEFT JOIN public.platform_admin_audit_events AS e
       ON e.platform_admin_user_id = pau.id
WHERE u.id = 3 OR u.company_id IN (1, 20)
GROUP BY u.company_id
ORDER BY u.company_id;

-- 3. Known direct and indirect count-only checks for chatbot 26.

SELECT 'bot_configs' AS reference_name, count(*) AS row_count
FROM public.bot_configs WHERE chatbot_id = 26
UNION ALL
SELECT 'knowledge_files', count(*)
FROM public.knowledge_files WHERE chatbot_id = 26
UNION ALL
SELECT 'knowledge_chunks', count(*)
FROM public.knowledge_chunks WHERE chatbot_id = 26
UNION ALL
SELECT 'knowledge_graph_nodes', count(*)
FROM public.knowledge_graph_nodes WHERE chatbot_id = 26
UNION ALL
SELECT 'knowledge_graph_edges', count(*)
FROM public.knowledge_graph_edges WHERE chatbot_id = 26
UNION ALL
SELECT 'conversations', count(*)
FROM public.conversations WHERE chatbot_id = 26
UNION ALL
SELECT 'messages_via_conversations', count(*)
FROM public.messages AS m
WHERE m.conversation_id IN (
    SELECT c.id FROM public.conversations AS c WHERE c.chatbot_id = 26
)
UNION ALL
SELECT 'crm_leads', count(*)
FROM public.crm_leads WHERE chatbot_id = 26
UNION ALL
SELECT 'agent_actions', count(*)
FROM public.agent_actions WHERE chatbot_id = 26
UNION ALL
SELECT 'ai_usage_logs', count(*)
FROM public.ai_usage_logs WHERE chatbot_id = 26
UNION ALL
SELECT 'whatsapp_channels', count(*)
FROM public.whatsapp_channels WHERE chatbot_id = 26
UNION ALL
SELECT 'telegram_channels', count(*)
FROM public.telegram_channels WHERE chatbot_id = 26
UNION ALL
SELECT 'wasender_channels', count(*)
FROM public.wasender_channels WHERE chatbot_id = 26
UNION ALL
SELECT 'processed_webhook_messages', count(*)
FROM public.processed_webhook_messages WHERE chatbot_id = 26
UNION ALL
SELECT 'processed_telegram_updates_via_channel', count(*)
FROM public.processed_telegram_updates AS ptu
WHERE ptu.telegram_channel_id IN (
    SELECT tc.id FROM public.telegram_channels AS tc WHERE tc.chatbot_id = 26
)
UNION ALL
SELECT 'processed_wasender_messages_via_channel', count(*)
FROM public.processed_wasender_messages AS pwm
WHERE pwm.wasender_channel_id IN (
    SELECT wc.id FROM public.wasender_channels AS wc WHERE wc.chatbot_id = 26
)
UNION ALL
SELECT 'broadcast_campaigns', count(*)
FROM public.broadcast_campaigns WHERE chatbot_id = 26
UNION ALL
SELECT 'broadcast_logs_via_campaign', count(*)
FROM public.broadcast_logs AS bl
WHERE bl.campaign_id IN (
    SELECT bc.id FROM public.broadcast_campaigns AS bc WHERE bc.chatbot_id = 26
)
ORDER BY reference_name;

-- Count-only company 20 checks for known direct-company tables. The confirmed
-- absent bot_media_attachments table is intentionally not referenced.
SELECT 'users' AS reference_name, count(*) AS row_count
FROM public.users WHERE company_id = 20
UNION ALL
SELECT 'chatbots', count(*) FROM public.chatbots WHERE company_id = 20
UNION ALL
SELECT 'company_subscriptions', count(*)
FROM public.company_subscriptions WHERE company_id = 20
UNION ALL
SELECT 'company_subscription_orders', count(*)
FROM public.company_subscription_orders WHERE company_id = 20
UNION ALL
SELECT 'company_ai_credit_balances', count(*)
FROM public.company_ai_credit_balances WHERE company_id = 20
UNION ALL
SELECT 'ai_credit_transactions', count(*)
FROM public.ai_credit_transactions WHERE company_id = 20
UNION ALL
SELECT 'ai_usage_logs', count(*) FROM public.ai_usage_logs WHERE company_id = 20
UNION ALL
SELECT 'ai_credit_topup_orders', count(*)
FROM public.ai_credit_topup_orders WHERE company_id = 20
UNION ALL
SELECT 'billing_notifications', count(*)
FROM public.billing_notifications WHERE company_id = 20
UNION ALL
SELECT 'crm_leads', count(*) FROM public.crm_leads WHERE company_id = 20
UNION ALL
SELECT 'agent_actions', count(*) FROM public.agent_actions WHERE company_id = 20
UNION ALL
SELECT 'invites', count(*) FROM public.invites WHERE company_id = 20
UNION ALL
SELECT 'whatsapp_channels', count(*)
FROM public.whatsapp_channels WHERE company_id = 20
UNION ALL
SELECT 'telegram_channels', count(*)
FROM public.telegram_channels WHERE company_id = 20
UNION ALL
SELECT 'wasender_channels', count(*)
FROM public.wasender_channels WHERE company_id = 20
UNION ALL
SELECT 'broadcast_campaigns', count(*)
FROM public.broadcast_campaigns WHERE company_id = 20
ORDER BY reference_name;

-- 4. Generated SELECT-only checks for every discovered ownership column.
-- Review and run every returned statement. Zero rows in the generator output
-- is itself evidence that the corresponding ownership-column class is absent.

SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE chatbot_id = 26;',
    c.table_name,
    c.table_schema,
    c.table_name
) AS chatbot_id_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'chatbot_id'
ORDER BY c.table_name;

SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE company_id = 20;',
    c.table_name,
    c.table_schema,
    c.table_name
) AS company_id_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'company_id'
ORDER BY c.table_name;

-- Single-column FK checks catch references whose child column is not named
-- chatbot_id. Composite FKs are listed by section 1 and require a reviewed,
-- manually written count query before retirement can be approved.
WITH direct_chatbot_fks AS (
    SELECT
        child_ns.nspname AS child_schema,
        child.relname AS child_table,
        child_att.attname AS child_column,
        con.conname AS constraint_name
    FROM pg_constraint AS con
    JOIN pg_class AS child ON child.oid = con.conrelid
    JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
    JOIN pg_attribute AS child_att
      ON child_att.attrelid = con.conrelid
     AND child_att.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND con.confrelid = 'public.chatbots'::regclass
      AND child_ns.nspname = 'public'
      AND cardinality(con.conkey) = 1
      AND cardinality(con.confkey) = 1
)
SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE %I = 26;',
    child_table || ' via ' || constraint_name,
    child_schema,
    child_table,
    child_column
) AS direct_chatbot_fk_count_sql
FROM direct_chatbot_fks
ORDER BY child_table, constraint_name;

-- Equivalent check for direct company FKs whose child column may not be named
-- company_id. Composite company FKs remain blocking manual-review items.
WITH direct_company_fks AS (
    SELECT
        child_ns.nspname AS child_schema,
        child.relname AS child_table,
        child_att.attname AS child_column,
        con.conname AS constraint_name
    FROM pg_constraint AS con
    JOIN pg_class AS child ON child.oid = con.conrelid
    JOIN pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
    JOIN pg_attribute AS child_att
      ON child_att.attrelid = con.conrelid
     AND child_att.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND con.confrelid = 'public.companies'::regclass
      AND child_ns.nspname = 'public'
      AND cardinality(con.conkey) = 1
      AND cardinality(con.confkey) = 1
)
SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE %I = 20;',
    child_table || ' via ' || constraint_name,
    child_schema,
    child_table,
    child_column
) AS direct_company_fk_count_sql
FROM direct_company_fks
ORDER BY child_table, constraint_name;

-- 5. Generated count checks for known indirect ownership paths.

SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE conversation_id IN (SELECT id FROM public.conversations WHERE chatbot_id = 26);',
    c.table_name || ' via conversations',
    c.table_schema,
    c.table_name
) AS conversation_path_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'conversation_id'
ORDER BY c.table_name;

SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE campaign_id IN (SELECT id FROM public.broadcast_campaigns WHERE chatbot_id = 26);',
    c.table_name || ' via campaigns',
    c.table_schema,
    c.table_name
) AS campaign_path_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'campaign_id'
ORDER BY c.table_name;

SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE telegram_channel_id IN (SELECT id FROM public.telegram_channels WHERE chatbot_id = 26);',
    c.table_name || ' via telegram_channels',
    c.table_schema,
    c.table_name
) AS telegram_channel_path_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'telegram_channel_id'
ORDER BY c.table_name;

SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE wasender_channel_id IN (SELECT id FROM public.wasender_channels WHERE chatbot_id = 26);',
    c.table_name || ' via wasender_channels',
    c.table_schema,
    c.table_name
) AS wasender_channel_path_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'wasender_channel_id'
ORDER BY c.table_name;

SELECT format(
    'SELECT %L AS reference_name, count(*) AS row_count FROM %I.%I WHERE %I IN (SELECT id FROM public.knowledge_files WHERE chatbot_id = 26);',
    c.table_name || ' via knowledge_files',
    c.table_schema,
    c.table_name,
    c.column_name
) AS knowledge_file_path_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name IN ('knowledge_file_id', 'file_id')
  AND c.table_name <> 'knowledge_files'
ORDER BY c.table_name, c.column_name;

-- Final zero-dependency result must be determined from retained output:
-- (a) every known count above is zero except chatbots=1 for company 20;
-- (b) every generated count statement is run and returns zero for chatbot 26;
-- (c) every composite/recursive FK path is resolved with a safe count query;
-- (d) storage/integration control planes contain no object for chatbot 26.
