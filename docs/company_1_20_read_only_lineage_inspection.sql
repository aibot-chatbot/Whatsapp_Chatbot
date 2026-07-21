-- Read-only tenant lineage inspection for public.companies IDs 1 and 20.
-- Run manually in the intended Supabase SQL Editor. Every executable statement
-- is SELECT or WITH ... SELECT. This script does not change database state.
-- It intentionally excludes passwords, OTPs, tokens, API keys, channel
-- credentials, message bodies, prompts, provider payloads, payment references,
-- gateway customer/order identifiers, and checkout URLs.

-- 1. Live schema discovery: direct company_id columns and foreign keys.
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
  AND c.column_name = 'company_id'
ORDER BY c.table_name;

SELECT
    c.table_schema,
    c.table_name,
    c.column_name,
    c.data_type,
    c.udt_name,
    c.is_nullable
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name IN (
      'company_id', 'chatbot_id', 'conversation_id', 'knowledge_file_id',
      'file_id', 'campaign_id', 'telegram_channel_id', 'wasender_channel_id'
  )
ORDER BY c.table_name, c.ordinal_position;

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

-- Recursive FK descendants of companies. Tables missing declared FKs will not
-- appear here; compare this result with the company_id inventory and explicit
-- repository-known queries below.
WITH RECURSIVE fk_edges AS (
    SELECT
        con.oid AS constraint_oid,
        con.conname AS constraint_name,
        con.conrelid AS child_oid,
        con.confrelid AS parent_oid,
        pg_get_constraintdef(con.oid, true) AS constraint_definition
    FROM pg_constraint AS con
    WHERE con.contype = 'f'
), lineage AS (
    SELECT
        1 AS depth,
        e.constraint_oid,
        e.constraint_name,
        e.child_oid,
        e.parent_oid,
        e.constraint_definition,
        ARRAY[e.parent_oid, e.child_oid]::oid[] AS visited
    FROM fk_edges AS e
    WHERE e.parent_oid = 'public.companies'::regclass

    UNION ALL

    SELECT
        l.depth + 1,
        e.constraint_oid,
        e.constraint_name,
        e.child_oid,
        e.parent_oid,
        e.constraint_definition,
        l.visited || e.child_oid
    FROM lineage AS l
    JOIN fk_edges AS e ON e.parent_oid = l.child_oid
    WHERE NOT e.child_oid = ANY(l.visited)
)
SELECT
    l.depth,
    l.parent_oid::regclass AS parent_table,
    l.child_oid::regclass AS child_table,
    l.constraint_name,
    l.constraint_definition
FROM lineage AS l
ORDER BY l.depth, l.parent_oid::regclass::text,
         l.child_oid::regclass::text, l.constraint_name;

-- Constraints, indexes, and triggers that could couple users.email and
-- companies.contact_email. Application code must be reviewed separately.
SELECT
    con.conrelid::regclass AS table_name,
    con.conname AS constraint_name,
    con.contype AS constraint_type,
    pg_get_constraintdef(con.oid, true) AS definition
FROM pg_constraint AS con
WHERE con.conrelid IN ('public.users'::regclass, 'public.companies'::regclass)
  AND pg_get_constraintdef(con.oid, true) ~* '(email|company_id)'
ORDER BY con.conrelid::regclass::text, con.conname;

SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('users', 'companies')
  AND indexdef ~* '(email|company_id)'
ORDER BY tablename, indexname;

SELECT
    t.tgrelid::regclass AS table_name,
    t.tgname AS trigger_name,
    t.tgenabled AS enabled_state,
    pg_get_triggerdef(t.oid, true) AS definition
FROM pg_trigger AS t
WHERE NOT t.tgisinternal
  AND t.tgrelid IN ('public.users'::regclass, 'public.companies'::regclass)
ORDER BY t.tgrelid::regclass::text, t.tgname;

-- 2. Company and account identity. Safe account fields only.
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

-- Detect other company rows sharing either target name or target contact email.
WITH target_identity AS (
    SELECT lower(company_name) AS company_name, lower(contact_email) AS contact_email
    FROM public.companies
    WHERE id IN (1, 20)
)
SELECT
    c.id,
    c.company_name,
    c.status,
    c.contact_email,
    c.created_at,
    c.updated_at
FROM public.companies AS c
WHERE lower(c.company_name) IN (SELECT company_name FROM target_identity)
   OR lower(c.contact_email) IN (SELECT contact_email FROM target_identity)
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
WHERE u.company_id IN (1, 20)
   OR lower(u.email) IN ('iomaths123@gmail.com', 'abc@gmail.com')
ORDER BY lower(u.email), u.id;

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
    c.id AS company_id,
    c.company_name,
    c.contact_email,
    u.id AS matching_user_id,
    u.company_id AS matching_user_company_id,
    u.email AS matching_user_email,
    (u.company_id = c.id) AS matching_user_belongs_to_company
FROM public.companies AS c
LEFT JOIN public.users AS u ON lower(u.email) = lower(c.contact_email)
WHERE c.id IN (1, 20)
ORDER BY c.id, u.id;

-- Pending registration identity only. Never select password_hash, OTP, or token
-- columns. A remaining row can support an interrupted-registration hypothesis.
SELECT
    pr.email,
    pr.company_name
FROM public.pending_registrations AS pr
WHERE lower(pr.email) IN ('iomaths123@gmail.com', 'abc@gmail.com')
ORDER BY lower(pr.email);

-- 3. Chatbots and direct tenant assets.
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
WHERE b.company_id IN (1, 20)
   OR b.id = 29
ORDER BY b.company_id, b.id;

SELECT 'whatsapp_channels' AS table_name, company_id, count(*) AS row_count,
       count(DISTINCT chatbot_id) AS chatbot_count
FROM public.whatsapp_channels
WHERE company_id IN (1, 20)
GROUP BY company_id
UNION ALL
SELECT 'telegram_channels', company_id, count(*), count(DISTINCT chatbot_id)
FROM public.telegram_channels
WHERE company_id IN (1, 20)
GROUP BY company_id
UNION ALL
SELECT 'wasender_channels', company_id, count(*), count(DISTINCT chatbot_id)
FROM public.wasender_channels
WHERE company_id IN (1, 20)
GROUP BY company_id
ORDER BY table_name, company_id;

SELECT
    company_id,
    count(*) AS attachment_count,
    count(DISTINCT chatbot_id) AS chatbot_count
FROM public.bot_media_attachments
WHERE company_id IN (1, 20)
GROUP BY company_id
ORDER BY company_id;

-- 4. Subscription and payment history. Gateway IDs, payment references,
-- idempotency keys, provider payloads, and checkout URLs are excluded.
SELECT
    cs.id,
    cs.company_id,
    cs.plan_id,
    sp.code AS plan_code,
    sp.name AS plan_name,
    sp.billing_interval,
    sp.currency,
    sp.price,
    sp.included_ai_credit_micro_myr,
    cs.status,
    cs.starts_at,
    cs.current_period_start,
    cs.current_period_end,
    cs.trial_ends_at,
    cs.cancelled_at,
    cs.ends_at,
    cs.pending_plan_id,
    cs.plan_change_effective_at,
    cs.cancellation_scheduled_at,
    cs.cancellation_effective_at,
    cs.created_at,
    cs.updated_at
FROM public.company_subscriptions AS cs
LEFT JOIN public.subscription_plans AS sp ON sp.id = cs.plan_id
WHERE cs.company_id IN (1, 20)
ORDER BY cs.company_id, cs.created_at, cs.id;

SELECT
    o.id,
    o.company_id,
    o.subscription_id,
    o.new_plan_id,
    np.code AS new_plan_code,
    o.source_plan_id,
    sp.code AS source_plan_code,
    o.amount_sen,
    o.status,
    o.payment_status,
    o.activation_status,
    o.reconciliation_required,
    o.created_by_user_id,
    o.created_at,
    o.updated_at,
    o.paid_at,
    o.credited_at,
    o.expires_at
FROM public.company_subscription_orders AS o
LEFT JOIN public.subscription_plans AS np ON np.id = o.new_plan_id
LEFT JOIN public.subscription_plans AS sp ON sp.id = o.source_plan_id
WHERE o.company_id IN (1, 20)
ORDER BY o.company_id, o.created_at, o.id;

SELECT
    o.id,
    o.company_id,
    o.subscription_id,
    o.created_by_user_id,
    o.amount_micro_myr,
    o.currency,
    o.status,
    o.created_at,
    o.updated_at,
    o.paid_at,
    o.credited_at,
    o.expires_at
FROM public.ai_credit_topup_orders AS o
WHERE o.company_id IN (1, 20)
ORDER BY o.company_id, o.created_at, o.id;

-- 5. AI-credit balance, immutable ledger, and usage. No provider generation ID.
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

SELECT
    t.id,
    t.company_id,
    t.subscription_id,
    t.transaction_type,
    t.included_delta_micro_myr,
    t.topup_delta_micro_myr,
    t.included_balance_after_micro_myr,
    t.topup_balance_after_micro_myr,
    t.customer_charge_micro_myr,
    t.uncovered_charge_micro_myr,
    t.provider_cost_micro_usd,
    t.ai_usage_log_id,
    t.reversal_of_transaction_id,
    t.period_start,
    t.period_end,
    t.created_at
FROM public.ai_credit_transactions AS t
WHERE t.company_id IN (1, 20)
ORDER BY t.company_id, t.created_at, t.id;

SELECT
    l.company_id,
    l.chatbot_id,
    l.provider,
    l.model,
    l.operation_type,
    l.request_status,
    count(*) AS request_count,
    sum(l.prompt_tokens) AS prompt_tokens,
    sum(l.completion_tokens) AS completion_tokens,
    sum(l.total_tokens) AS total_tokens,
    sum(l.provider_cost_micro_usd) AS provider_cost_micro_usd,
    min(l.created_at) AS first_usage_at,
    max(l.created_at) AS last_usage_at
FROM public.ai_usage_logs AS l
WHERE l.company_id IN (1, 20)
GROUP BY l.company_id, l.chatbot_id, l.provider, l.model,
         l.operation_type, l.request_status
ORDER BY l.company_id, l.chatbot_id, first_usage_at;

SELECT
    company_id,
    notification_type,
    severity,
    count(*) AS notification_count,
    min(created_at) AS first_notification_at,
    max(created_at) AS last_notification_at
FROM public.billing_notifications
WHERE company_id IN (1, 20)
GROUP BY company_id, notification_type, severity
ORDER BY company_id, notification_type, severity;

-- 6. Conversations, messages, CRM, and agent activity. Only counts and time
-- ranges are returned; customer identifiers, message text, lead text, and
-- action payloads are excluded.
SELECT
    b.company_id,
    count(DISTINCT c.id) AS conversation_count,
    min(c.created_at) AS first_conversation_at,
    max(c.updated_at) AS last_conversation_at
FROM public.chatbots AS b
JOIN public.conversations AS c ON c.chatbot_id = b.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT
    b.company_id,
    count(m.id) AS message_count,
    min(m.created_at) AS first_message_at,
    max(m.created_at) AS last_message_at
FROM public.chatbots AS b
JOIN public.conversations AS c ON c.chatbot_id = b.id
JOIN public.messages AS m ON m.conversation_id = c.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT
    company_id,
    status,
    priority,
    count(*) AS lead_count,
    min(created_at) AS first_lead_at,
    max(updated_at) AS last_lead_at
FROM public.crm_leads
WHERE company_id IN (1, 20)
GROUP BY company_id, status, priority
ORDER BY company_id, status, priority;

SELECT
    company_id,
    status,
    action_type,
    count(*) AS action_count,
    min(created_at) AS first_action_at,
    max(created_at) AS last_action_at
FROM public.agent_actions
WHERE company_id IN (1, 20)
GROUP BY company_id, status, action_type
ORDER BY company_id, status, action_type;

-- 7. Knowledge and bot configuration lineage through chatbot_id. No file
-- content, chunk content/embeddings, graph properties, or prompts are selected.
SELECT b.company_id, count(kf.id) AS knowledge_file_count
FROM public.chatbots AS b
JOIN public.knowledge_files AS kf ON kf.chatbot_id = b.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT b.company_id, count(kc.id) AS knowledge_chunk_count
FROM public.chatbots AS b
JOIN public.knowledge_chunks AS kc ON kc.chatbot_id = b.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT b.company_id, count(n.id) AS graph_node_count
FROM public.chatbots AS b
JOIN public.knowledge_graph_nodes AS n ON n.chatbot_id = b.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT b.company_id, count(e.id) AS graph_edge_count
FROM public.chatbots AS b
JOIN public.knowledge_graph_edges AS e ON e.chatbot_id = b.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT b.company_id, count(cfg.id) AS bot_config_count
FROM public.chatbots AS b
JOIN public.bot_configs AS cfg ON cfg.chatbot_id = b.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT b.company_id, count(pwm.id) AS processed_webhook_message_count
FROM public.chatbots AS b
JOIN public.processed_webhook_messages AS pwm ON pwm.chatbot_id = b.id
WHERE b.company_id IN (1, 20)
GROUP BY b.company_id
ORDER BY b.company_id;

SELECT tc.company_id, count(ptu.id) AS processed_telegram_update_count
FROM public.telegram_channels AS tc
JOIN public.processed_telegram_updates AS ptu
  ON ptu.telegram_channel_id = tc.id
WHERE tc.company_id IN (1, 20)
GROUP BY tc.company_id
ORDER BY tc.company_id;

SELECT wc.company_id, count(pwm.id) AS processed_wasender_message_count
FROM public.wasender_channels AS wc
JOIN public.processed_wasender_messages AS pwm
  ON pwm.wasender_channel_id = wc.id
WHERE wc.company_id IN (1, 20)
GROUP BY wc.company_id
ORDER BY wc.company_id;

-- 8. Invitations and team lineage. Invitation tokens are excluded.
SELECT
    i.id,
    i.company_id,
    i.email,
    i.role,
    i.status,
    i.created_by,
    i.created_at,
    i.expires_at
FROM public.invites AS i
WHERE i.company_id IN (1, 20)
ORDER BY i.company_id, i.created_at, i.id;

-- 9. Broadcast lineage is count-only to exclude recipients and message text.
SELECT
    bc.company_id,
    count(DISTINCT bc.id) AS campaign_count,
    count(bl.id) AS broadcast_log_count,
    min(bc.created_at) AS first_campaign_at,
    max(bc.created_at) AS last_campaign_at
FROM public.broadcast_campaigns AS bc
LEFT JOIN public.broadcast_logs AS bl ON bl.campaign_id = bc.id
WHERE bc.company_id IN (1, 20)
GROUP BY bc.company_id
ORDER BY bc.company_id;

-- 10. Platform-admin mappings through users. Tenant role is shown only to
-- prove platform access remains independent of users.role.
SELECT
    pau.id AS platform_admin_user_id,
    pau.user_id,
    pau.is_active AS platform_mapping_active,
    pau.created_by_user_id,
    pau.created_at,
    pau.updated_at,
    u.company_id,
    u.email,
    u.role AS tenant_role,
    u.status AS user_status
FROM public.platform_admin_users AS pau
JOIN public.users AS u ON u.id = pau.user_id
WHERE u.company_id IN (1, 20)
ORDER BY u.company_id, pau.id;

SELECT
    u.company_id,
    count(e.id) AS platform_audit_event_count,
    min(e.created_at) AS first_platform_event_at,
    max(e.created_at) AS last_platform_event_at
FROM public.platform_admin_users AS pau
JOIN public.users AS u ON u.id = pau.user_id
LEFT JOIN public.platform_admin_audit_events AS e
       ON e.platform_admin_user_id = pau.id
WHERE u.company_id IN (1, 20)
GROUP BY u.company_id
ORDER BY u.company_id;

-- 11. Generator for any additional live direct-company table not covered
-- above. This SELECT only returns safe count-query text. Review each generated
-- statement, then run it separately; never replace the projection with '*'.
SELECT format(
    'SELECT %L AS table_name, company_id, count(*) AS row_count FROM %I.%I WHERE company_id IN (1, 20) GROUP BY company_id ORDER BY company_id;',
    c.table_name,
    c.table_schema,
    c.table_name
) AS additional_select_only_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'company_id'
  AND c.table_name NOT IN (
      'users', 'chatbots', 'company_subscriptions',
      'company_subscription_orders', 'company_ai_credit_balances',
      'ai_credit_transactions', 'ai_usage_logs', 'ai_credit_topup_orders',
      'billing_notifications', 'crm_leads', 'agent_actions', 'invites',
      'whatsapp_channels', 'telegram_channels', 'wasender_channels',
      'bot_media_attachments', 'broadcast_campaigns'
  )
ORDER BY c.table_name;

-- Review-only generator for additional live chatbot-owned tables. It returns
-- count-query text without executing it or exposing row contents.
SELECT format(
    'SELECT %L AS table_name, b.company_id, count(*) AS row_count FROM public.chatbots AS b JOIN %I.%I AS t ON t.chatbot_id = b.id WHERE b.company_id IN (1, 20) GROUP BY b.company_id ORDER BY b.company_id;',
    c.table_name,
    c.table_schema,
    c.table_name
) AS additional_chatbot_lineage_count_sql
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.column_name = 'chatbot_id'
  AND c.table_name NOT IN (
      'chatbots', 'whatsapp_channels', 'telegram_channels', 'wasender_channels',
      'bot_media_attachments', 'ai_usage_logs', 'crm_leads', 'agent_actions',
      'broadcast_campaigns', 'conversations', 'knowledge_files',
      'knowledge_chunks', 'knowledge_graph_nodes', 'knowledge_graph_edges',
      'bot_configs', 'processed_webhook_messages'
  )
ORDER BY c.table_name;
