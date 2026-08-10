-- 037_platform_admin_monitoring_aggregates.sql
-- DRAFT ONLY. Do not apply without approved executor, environment,
-- rollback, and verification evidence.
-- Adds a bounded read-only Phase 6 monitoring aggregate RPC because the
-- approved shared-testing PostgREST environment rejects REST aggregate select
-- syntax such as count:id.count().

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
                    'wasender', (
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
                                    FROM public.wasender_channels AS inner_ch
                                    GROUP BY inner_ch.connection_status
                                ) AS grouped
                            )
                        )
                        FROM public.wasender_channels AS ch
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
