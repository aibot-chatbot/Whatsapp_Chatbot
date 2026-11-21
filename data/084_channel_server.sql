BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS public.channel_server_channels (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    chatbot_id bigint NOT NULL REFERENCES public.chatbots(id) ON DELETE CASCADE,
    session_name text NOT NULL UNIQUE,
    phone_number text,
    connection_status text NOT NULL DEFAULT 'pending'
        CHECK (connection_status IN ('pending','connected','disconnected','failed')),
    is_active boolean NOT NULL DEFAULT true,
    risk_consent_at timestamptz NOT NULL,
    risk_consent_by bigint NOT NULL,
    connection_attempted_at timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS channel_server_active_bot_idx
    ON public.channel_server_channels(chatbot_id) WHERE is_active;
CREATE UNIQUE INDEX IF NOT EXISTS channel_server_connected_number_idx
    ON public.channel_server_channels(phone_number) WHERE is_active AND connection_status = 'connected';
CREATE INDEX IF NOT EXISTS channel_server_company_idx ON public.channel_server_channels(company_id);
DROP TRIGGER IF EXISTS channel_server_identity_guard ON public.channel_server_channels;
CREATE TRIGGER channel_server_identity_guard BEFORE UPDATE ON public.channel_server_channels
    FOR EACH ROW EXECUTE FUNCTION public.guard_channel_identity('phone_number');

CREATE TABLE IF NOT EXISTS public.processed_channel_server_messages (
    message_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.channel_server_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processed_channel_server_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.channel_server_channels, public.processed_channel_server_messages FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.channel_server_channels_id_seq FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.channel_server_channels TO service_role;
GRANT SELECT, INSERT, DELETE ON public.processed_channel_server_messages TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.channel_server_channels_id_seq TO service_role;

-- Preserve company locking, Telegram reservations, verified identity and attempt ordering.
CREATE OR REPLACE FUNCTION public.activate_verified_channel(p_provider text, p_channel_id bigint, p_chatbot_id bigint, p_company_id bigint, p_channel_limit integer, p_expected_attempt_at timestamp with time zone DEFAULT NULL::timestamp with time zone)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
DECLARE
  v_table text; v_identity text; v_candidate jsonb; v_result jsonb; v_newer boolean;
  v_replacing boolean; v_used bigint;
BEGIN
  v_table := CASE p_provider WHEN 'telegram' THEN 'telegram_channels'
    WHEN 'whatsapp' THEN 'whatsapp_channels'
    WHEN 'whatsapp_link' THEN 'channel_server_channels' END;
  v_identity := CASE p_provider WHEN 'telegram' THEN 'telegram_bot_id'
    WHEN 'whatsapp' THEN 'phone_number_id'
    WHEN 'whatsapp_link' THEN 'phone_number' END;
  IF v_table IS NULL OR p_channel_limit < 0 THEN
    RAISE EXCEPTION 'Invalid activation parameters' USING ERRCODE = '22023';
  END IF;
  PERFORM 1 FROM public.companies WHERE id = p_company_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Company not found' USING ERRCODE = '42501'; END IF;
  PERFORM 1 FROM public.chatbots WHERE id = p_chatbot_id AND company_id = p_company_id
    AND deleted_at IS NULL AND status <> 'archived' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Chatbot ownership does not match' USING ERRCODE = '42501'; END IF;

  EXECUTE format('SELECT to_jsonb(c) FROM public.%I c WHERE id=$1 AND chatbot_id=$2 AND company_id=$3 AND is_active=true AND connection_status=''pending'' FOR UPDATE', v_table)
    INTO v_candidate USING p_channel_id, p_chatbot_id, p_company_id;
  IF v_candidate IS NULL THEN RETURN NULL; END IF;
  IF NULLIF(v_candidate->>v_identity, '') IS NULL
     OR v_candidate->>'verified_at' IS NULL OR v_candidate->>'connection_attempted_at' IS NULL
     OR (v_candidate->>'verified_at')::timestamptz < (v_candidate->>'connection_attempted_at')::timestamptz
     OR (p_expected_attempt_at IS NOT NULL AND (v_candidate->>'connection_attempted_at')::timestamptz <> p_expected_attempt_at) THEN
    RETURN NULL;
  END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I c WHERE chatbot_id=$1 AND company_id=$2 AND id<>$3 AND is_active=true AND connection_status=''connected'' AND (COALESCE(connection_attempted_at,created_at),id) > ($4,$3))', v_table)
    INTO v_newer USING p_chatbot_id,p_company_id,p_channel_id,(v_candidate->>'connection_attempted_at')::timestamptz;
  IF v_newer THEN
    EXECUTE format('UPDATE public.%I SET is_active=false,connection_status=''failed'',last_error=''A newer connection replaced this attempt.'' WHERE id=$1',v_table) USING p_channel_id;
    RETURN NULL;
  END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I WHERE chatbot_id=$1 AND company_id=$2 AND id<>$3 AND is_active=true AND connection_status=''connected'')',v_table)
    INTO v_replacing USING p_chatbot_id,p_company_id,p_channel_id;
  IF p_provider='telegram' AND COALESCE((v_candidate->>'connection_slot_reserved')::boolean,false) THEN
    v_replacing := true;
  END IF;
  SELECT count(*) INTO v_used FROM (
    SELECT c.chatbot_id FROM public.telegram_channels c WHERE company_id=p_company_id AND is_active=true
      AND (connection_status='connected' OR (connection_status='pending' AND connection_slot_reserved=true))
    UNION ALL SELECT c.chatbot_id FROM public.whatsapp_channels c WHERE company_id=p_company_id AND is_active=true AND connection_status='connected'
    UNION ALL SELECT c.chatbot_id FROM public.channel_server_channels c WHERE company_id=p_company_id AND is_active=true AND connection_status='connected'
  ) channels JOIN public.chatbots b ON b.id=channels.chatbot_id
    WHERE b.company_id=p_company_id AND b.deleted_at IS NULL AND b.status <> 'archived';
  IF p_channel_limit IS NOT NULL AND NOT v_replacing AND v_used >= p_channel_limit THEN
    RAISE EXCEPTION 'channel_limit_reached' USING ERRCODE='P0001';
  END IF;
  EXECUTE format('UPDATE public.%I SET is_active=false,connection_status=''disconnected'',last_error=NULL WHERE chatbot_id=$1 AND company_id=$2 AND id<>$3 AND is_active=true AND connection_status<>''pending''',v_table)
    USING p_chatbot_id,p_company_id,p_channel_id;
  EXECUTE format('UPDATE public.%I c SET is_active=true,connection_status=''connected'',last_error=NULL WHERE id=$1 RETURNING to_jsonb(c)',v_table)
    INTO v_result USING p_channel_id;
  RETURN v_result;
END;
$function$;
REVOKE ALL ON FUNCTION public.activate_verified_channel(text,bigint,bigint,bigint,integer,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.activate_verified_channel(text,bigint,bigint,bigint,integer,timestamptz) TO service_role;


CREATE OR REPLACE FUNCTION public.get_platform_admin_monitoring_overview()
RETURNS JSONB
LANGUAGE sql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
WITH monitoring_window AS (
    SELECT
        pg_catalog.now() AS generated_at,
        pg_catalog.now() - '7 days'::INTERVAL AS since_at
)
SELECT pg_catalog.jsonb_build_object(
    'active_user_count',
        (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.users AS u
            WHERE u.status = 'active'
        ),
    'support',
        pg_catalog.jsonb_build_object(
            'cases_by_status',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT c.status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.platform_support_cases AS c
                        GROUP BY c.status
                    ) AS grouped
                ),
            'cases_by_priority',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.priority, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT c.priority, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.platform_support_cases AS c
                        GROUP BY c.priority
                    ) AS grouped
                ),
            'tenant_requests_by_status',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT r.status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.tenant_support_requests AS r
                        GROUP BY r.status
                    ) AS grouped
                )
        ),
    'messaging',
        pg_catalog.jsonb_build_object(
            'messages_by_delivery_status',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.delivery_status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT m.delivery_status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.messages AS m
                        GROUP BY m.delivery_status
                    ) AS grouped
                ),
            'retry_backlog_count',
                (
                    SELECT pg_catalog.count(*)::BIGINT
                    FROM public.messages AS m
                    WHERE m.sender_type = 'bot'
                      AND m.ai_generated IS TRUE
                      AND m.delivery_status = 'failed'
                      AND (m.retry_count IS NULL OR m.retry_count < 3)
                      AND (m.next_retry_at IS NULL OR m.next_retry_at <= pg_catalog.now())
                ),
            'channel_health',
                pg_catalog.jsonb_build_object(
                    'telegram', (
                        SELECT pg_catalog.jsonb_build_object(
                            'total', pg_catalog.count(*)::BIGINT,
                            'active', pg_catalog.count(*) FILTER (WHERE ch.is_active IS TRUE)::BIGINT,
                            'inactive', pg_catalog.count(*) FILTER (WHERE ch.is_active IS NOT TRUE)::BIGINT,
                            'attention_required', pg_catalog.count(*) FILTER (
                                WHERE ch.is_active IS NOT TRUE
                                   OR ch.connection_status IN ('disconnected', 'error')
                            )::BIGINT,
                            'by_connection_status', (
                                SELECT COALESCE(
                                    pg_catalog.jsonb_object_agg(grouped.connection_status, grouped.row_count),
                                    '{}'::JSONB
                                )
                                FROM (
                                    SELECT inner_ch.connection_status, pg_catalog.count(*)::BIGINT AS row_count
                                    FROM public.telegram_channels AS inner_ch
                                    GROUP BY inner_ch.connection_status
                                ) AS grouped
                            )
                        )
                        FROM public.telegram_channels AS ch
                    ),
                    'whatsapp_link', (
                        SELECT pg_catalog.jsonb_build_object(
                            'total', pg_catalog.count(*)::BIGINT,
                            'active', pg_catalog.count(*) FILTER (WHERE ch.is_active IS TRUE)::BIGINT,
                            'inactive', pg_catalog.count(*) FILTER (WHERE ch.is_active IS NOT TRUE)::BIGINT,
                            'attention_required', pg_catalog.count(*) FILTER (
                                WHERE ch.is_active IS NOT TRUE
                                   OR ch.connection_status IN ('disconnected', 'failed')
                            )::BIGINT,
                            'by_connection_status', (
                                SELECT COALESCE(
                                    pg_catalog.jsonb_object_agg(grouped.connection_status, grouped.row_count),
                                    '{}'::JSONB
                                )
                                FROM (
                                    SELECT CASE WHEN inner_ch.connection_status='failed' THEN 'error' ELSE inner_ch.connection_status END AS connection_status,
                                           pg_catalog.count(*)::BIGINT AS row_count
                                    FROM public.channel_server_channels AS inner_ch
                                    GROUP BY 1
                                ) AS grouped
                            )
                        )
                        FROM public.channel_server_channels AS ch
                    ),
                    'meta_whatsapp', (
                        SELECT pg_catalog.jsonb_build_object(
                            'total', pg_catalog.count(*)::BIGINT,
                            'active', pg_catalog.count(*) FILTER (WHERE ch.is_active IS TRUE)::BIGINT,
                            'inactive', pg_catalog.count(*) FILTER (WHERE ch.is_active IS NOT TRUE)::BIGINT,
                            'attention_required', pg_catalog.count(*) FILTER (
                                WHERE ch.is_active IS NOT TRUE
                                   OR ch.connection_status IN ('disconnected', 'error')
                            )::BIGINT,
                            'by_connection_status', (
                                SELECT COALESCE(
                                    pg_catalog.jsonb_object_agg(grouped.connection_status, grouped.row_count),
                                    '{}'::JSONB
                                )
                                FROM (
                                    SELECT inner_ch.connection_status, pg_catalog.count(*)::BIGINT AS row_count
                                    FROM public.whatsapp_channels AS inner_ch
                                    GROUP BY inner_ch.connection_status
                                ) AS grouped
                            )
                        )
                        FROM public.whatsapp_channels AS ch
                    )
                ),
            'broadcast_campaigns_by_status',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT c.status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.broadcast_campaigns AS c
                        GROUP BY c.status
                    ) AS grouped
                ),
            'broadcast_recipients_by_status',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT l.status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.broadcast_logs AS l
                        GROUP BY l.status
                    ) AS grouped
                )
        ),
    'billing_attention',
        pg_catalog.jsonb_build_object(
            'orders_by_status',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT o.status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.company_subscription_orders AS o
                        GROUP BY o.status
                    ) AS grouped
                ),
            'reconciliation_required_count',
                (
                    SELECT pg_catalog.count(*)::BIGINT
                    FROM public.company_subscription_orders AS o
                    WHERE o.reconciliation_required IS TRUE
                ),
            'activation_statuses',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.activation_status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT o.activation_status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.company_subscription_orders AS o
                        WHERE o.activation_status IS NOT NULL
                        GROUP BY o.activation_status
                    ) AS grouped
                ),
            'activation_status_unset_count',
                (
                    SELECT pg_catalog.count(*)::BIGINT
                    FROM public.company_subscription_orders AS o
                    WHERE o.activation_status IS NULL
                )
        ),
    'ai_usage',
        pg_catalog.jsonb_build_object(
            'window', pg_catalog.jsonb_build_object(
                'days', 7,
                'since', (SELECT monitoring_window.since_at FROM monitoring_window)
            ),
            'requests_by_status',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.request_status, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT l.request_status, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.ai_usage_logs AS l
                        GROUP BY l.request_status
                    ) AS grouped
                ),
            'recent_request_count',
                (
                    SELECT pg_catalog.count(*)::BIGINT
                    FROM public.ai_usage_logs AS l
                    WHERE l.created_at >= (SELECT monitoring_window.since_at FROM monitoring_window)
                ),
            'recent_total_tokens',
                (
                    SELECT COALESCE(pg_catalog.sum(l.total_tokens), 0)::BIGINT
                    FROM public.ai_usage_logs AS l
                    WHERE l.created_at >= (SELECT monitoring_window.since_at FROM monitoring_window)
                ),
            'credit_transactions_by_type',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.transaction_type, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT t.transaction_type, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.ai_credit_transactions AS t
                        GROUP BY t.transaction_type
                    ) AS grouped
                ),
            'depleted_balance_company_count',
                (
                    SELECT pg_catalog.count(*)::BIGINT
                    FROM public.company_ai_credit_balances AS b
                    WHERE COALESCE(b.included_balance_micro_myr, 0) = 0
                      AND COALESCE(b.topup_balance_micro_myr, 0) = 0
                )
        ),
    'platform_admin_activity',
        pg_catalog.jsonb_build_object(
            'window', pg_catalog.jsonb_build_object(
                'days', 7,
                'since', (SELECT monitoring_window.since_at FROM monitoring_window)
            ),
            'recent_event_count',
                (
                    SELECT pg_catalog.count(*)::BIGINT
                    FROM public.platform_admin_audit_events AS e
                    WHERE e.created_at >= (SELECT monitoring_window.since_at FROM monitoring_window)
                ),
            'events_by_action',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.action, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT e.action, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.platform_admin_audit_events AS e
                        WHERE e.created_at >= (SELECT monitoring_window.since_at FROM monitoring_window)
                          AND e.action IN (
                              'platform_admin.identity.read',
                              'platform_admin.operations.overview.read',
                              'platform_admin.billing.overview.read',
                              'platform_admin.billing.company_list',
                              'platform_admin.company.list',
                              'platform_admin.company.read',
                              'platform_admin.company.subscription.read',
                              'platform_admin.company.ai_credit_usage.read',
                              'platform_admin.company.users.read',
                              'platform_admin.company.chatbots.read',
                              'platform_admin.company.subscription_history.read',
                              'platform_admin.company.ai_credit_transactions.read',
                              'platform_admin.company.billing_orders.read',
                              'platform_admin.company.suspend',
                              'platform_admin.company.restore',
                              'platform_admin.audit_events.list',
                              'platform_admin.support_case.list',
                              'platform_admin.support_case.read',
                              'platform_admin.support_case.create',
                              'platform_admin.support_case.note.create',
                              'platform_admin.support_case.assignee.list',
                              'platform_admin.support_case.assign',
                              'platform_admin.support_case.unassign',
                              'platform_admin.support_case.status.update',
                              'platform_admin.support_case.priority.update',
                              'platform_admin.support_case.reply.list',
                              'platform_admin.support_case.reply.create',
                              'platform_admin.tenant_support_request.list',
                              'platform_admin.tenant_support_request.read',
                              'platform_admin.tenant_support_request.review',
                              'platform_admin.tenant_support_request.close',
                              'platform_admin.tenant_support_request.convert',
                              'platform_admin.user.list',
                              'platform_admin.user.read',
                              'platform_admin.user.create',
                              'platform_admin.user.activate',
                              'platform_admin.user.deactivate'
                          )
                        GROUP BY e.action
                    ) AS grouped
                ),
            'events_by_resource_type',
                (
                    SELECT COALESCE(
                        pg_catalog.jsonb_object_agg(grouped.resource_type, grouped.row_count),
                        '{}'::JSONB
                    )
                    FROM (
                        SELECT e.resource_type, pg_catalog.count(*)::BIGINT AS row_count
                        FROM public.platform_admin_audit_events AS e
                        WHERE e.created_at >= (SELECT monitoring_window.since_at FROM monitoring_window)
                          AND e.resource_type IN (
                              'company',
                              'company_ai_credit_transactions',
                              'company_ai_credit_usage',
                              'company_billing_orders',
                              'company_chatbots',
                              'company_subscription',
                              'company_subscription_history',
                              'company_users',
                              'platform_admin',
                              'platform_admin_audit_events',
                              'platform_admin_users',
                              'platform_billing_overview',
                              'platform_billing_companies',
                              'platform_operations_overview',
                              'platform_support_case_events',
                              'platform_support_cases',
                              'tenant_support_replies',
                              'tenant_support_requests'
                          )
                        GROUP BY e.resource_type
                    ) AS grouped
                )
        )
);
$function$;

ALTER FUNCTION public.get_platform_admin_monitoring_overview()
    OWNER TO postgres;

REVOKE EXECUTE ON FUNCTION public.get_platform_admin_monitoring_overview()
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.get_platform_admin_monitoring_overview()
    TO service_role;

COMMIT;
