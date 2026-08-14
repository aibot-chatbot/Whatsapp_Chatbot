-- Platform-admin Phase 7 billing/subscription oversight.
-- Read-only aggregate RPC. No financial mutation controls are introduced.

CREATE OR REPLACE FUNCTION public.get_platform_admin_billing_overview()
RETURNS JSONB
LANGUAGE SQL
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
WITH
latest_subscriptions AS (
    SELECT DISTINCT ON (cs.company_id)
        cs.company_id,
        cs.status,
        cs.plan_id,
        cs.pending_plan_id,
        cs.cancellation_scheduled_at
    FROM public.company_subscriptions AS cs
    ORDER BY cs.company_id, cs.created_at DESC, cs.id DESC
),
active_plans AS (
    SELECT
        sp.code,
        sp.name,
        sp.billing_interval,
        sp.currency,
        pg_catalog.round(sp.price * 100)::BIGINT AS price_sen,
        sp.included_ai_credit_micro_myr
    FROM public.subscription_plans AS sp
    WHERE sp.is_active IS TRUE
),
notification_groups AS (
    SELECT COALESCE(
        pg_catalog.jsonb_agg(
            pg_catalog.jsonb_build_object(
                'notification_type', grouped.notification_type,
                'severity', grouped.severity,
                'is_read', grouped.is_read,
                'count', grouped.row_count
            )
            ORDER BY grouped.notification_type, grouped.severity, grouped.is_read
        ),
        '[]'::JSONB
    ) AS groups_json
    FROM (
        SELECT
            bn.notification_type,
            bn.severity,
            bn.is_read,
            pg_catalog.count(*)::BIGINT AS row_count
        FROM public.billing_notifications AS bn
        WHERE bn.notification_type IS NOT NULL
          AND bn.severity IN ('info', 'warning', 'critical')
          AND bn.is_read IS NOT NULL
        GROUP BY bn.notification_type, bn.severity, bn.is_read
    ) AS grouped
)
SELECT pg_catalog.jsonb_build_object(
    'generated_at', pg_catalog.now(),
    'subscriptions', pg_catalog.jsonb_build_object(
        'by_status', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count)
            FROM (
                SELECT ls.status, pg_catalog.count(*)::BIGINT AS row_count
                FROM latest_subscriptions AS ls
                WHERE ls.status IN ('trialing', 'active', 'past_due', 'expired', 'cancelled')
                GROUP BY ls.status
            ) AS grouped
        ), '{}'::JSONB),
        'by_plan', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.plan_code, grouped.row_count)
            FROM (
                SELECT sp.code AS plan_code, pg_catalog.count(*)::BIGINT AS row_count
                FROM latest_subscriptions AS ls
                JOIN public.subscription_plans AS sp
                  ON sp.id = ls.plan_id
                WHERE sp.code IS NOT NULL
                GROUP BY sp.code
            ) AS grouped
        ), '{}'::JSONB),
        'active_plan_catalogue', COALESCE((
            SELECT pg_catalog.jsonb_agg(
                pg_catalog.jsonb_build_object(
                    'code', ap.code,
                    'name', ap.name,
                    'billing_interval', ap.billing_interval,
                    'currency', ap.currency,
                    'price_sen', ap.price_sen,
                    'included_ai_credit_micro_myr', ap.included_ai_credit_micro_myr
                )
                ORDER BY ap.code
            )
            FROM active_plans AS ap
        ), '[]'::JSONB)
    ),
    'subscription_orders', pg_catalog.jsonb_build_object(
        'orders_by_status', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count)
            FROM (
                SELECT o.status, pg_catalog.count(*)::BIGINT AS row_count
                FROM public.company_subscription_orders AS o
                WHERE o.status IN ('pending', 'created', 'paid', 'credited', 'failed', 'expired', 'cancelled')
                GROUP BY o.status
            ) AS grouped
        ), '{}'::JSONB),
        'pending_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.company_subscription_orders AS o
            WHERE o.status IN ('pending', 'created')
        ),
        'failed_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.company_subscription_orders AS o
            WHERE o.status = 'failed'
        ),
        'reconciliation_required_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.company_subscription_orders AS o
            WHERE o.reconciliation_required IS TRUE
        ),
        'activation_statuses', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.activation_status, grouped.row_count)
            FROM (
                SELECT o.activation_status, pg_catalog.count(*)::BIGINT AS row_count
                FROM public.company_subscription_orders AS o
                WHERE o.activation_status IN (
                    'not_started', 'claimed', 'activated', 'credit_pending',
                    'completed', 'conflict', 'failed'
                )
                GROUP BY o.activation_status
            ) AS grouped
        ), '{}'::JSONB),
        'activation_status_unset_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.company_subscription_orders AS o
            WHERE o.activation_status IS NULL
        ),
        'activation_types', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.activation_type, grouped.row_count)
            FROM (
                SELECT o.activation_type, pg_catalog.count(*)::BIGINT AS row_count
                FROM public.company_subscription_orders AS o
                WHERE o.activation_type IN ('initial_purchase', 'renewal', 'upgrade')
                GROUP BY o.activation_type
            ) AS grouped
        ), '{}'::JSONB),
        'activation_type_unset_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.company_subscription_orders AS o
            WHERE o.activation_type IS NULL
        )
    ),
    'topup_orders', pg_catalog.jsonb_build_object(
        'orders_by_status', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.status, grouped.row_count)
            FROM (
                SELECT t.status, pg_catalog.count(*)::BIGINT AS row_count
                FROM public.ai_credit_topup_orders AS t
                WHERE t.status IN ('pending', 'claimed', 'paid', 'credited', 'failed', 'expired', 'cancelled')
                GROUP BY t.status
            ) AS grouped
        ), '{}'::JSONB),
        'pending_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.ai_credit_topup_orders AS t
            WHERE t.status = 'pending'
        ),
        'failed_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.ai_credit_topup_orders AS t
            WHERE t.status = 'failed'
        ),
        'credited_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.ai_credit_topup_orders AS t
            WHERE t.status = 'credited'
        )
    ),
    'ai_credit', pg_catalog.jsonb_build_object(
        'balance_row_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.company_ai_credit_balances AS b
        ),
        'depleted_company_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.company_ai_credit_balances AS b
            WHERE COALESCE(b.included_balance_micro_myr, 0) = 0
              AND COALESCE(b.topup_balance_micro_myr, 0) = 0
        ),
        'total_included_balance_micro_myr', (
            SELECT COALESCE(pg_catalog.sum(b.included_balance_micro_myr), 0)::BIGINT
            FROM public.company_ai_credit_balances AS b
        ),
        'total_topup_balance_micro_myr', (
            SELECT COALESCE(pg_catalog.sum(b.topup_balance_micro_myr), 0)::BIGINT
            FROM public.company_ai_credit_balances AS b
        ),
        'transactions_by_type', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.transaction_type, grouped.row_count)
            FROM (
                SELECT tx.transaction_type, pg_catalog.count(*)::BIGINT AS row_count
                FROM public.ai_credit_transactions AS tx
                WHERE tx.transaction_type IN (
                    'included_credit_grant', 'trial_credit_grant', 'usage_debit',
                    'topup_purchase', 'refund', 'manual_adjustment', 'expiry', 'reversal'
                )
                GROUP BY tx.transaction_type
            ) AS grouped
        ), '{}'::JSONB)
    ),
    'ai_usage', pg_catalog.jsonb_build_object(
        'window', pg_catalog.jsonb_build_object(
            'days', 7,
            'since', pg_catalog.now() - '7 days'::INTERVAL
        ),
        'requests_by_status', COALESCE((
            SELECT pg_catalog.jsonb_object_agg(grouped.request_status, grouped.row_count)
            FROM (
                SELECT l.request_status, pg_catalog.count(*)::BIGINT AS row_count
                FROM public.ai_usage_logs AS l
                WHERE l.request_status IN ('completed', 'failed')
                GROUP BY l.request_status
            ) AS grouped
        ), '{}'::JSONB),
        'recent_request_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM public.ai_usage_logs AS l
            WHERE l.created_at >= pg_catalog.now() - '7 days'::INTERVAL
        ),
        'recent_total_tokens', (
            SELECT COALESCE(pg_catalog.sum(l.total_tokens), 0)::BIGINT
            FROM public.ai_usage_logs AS l
            WHERE l.created_at >= pg_catalog.now() - '7 days'::INTERVAL
        )
    ),
    'billing_notifications', pg_catalog.jsonb_build_object(
        'by_type_severity_read_state', (SELECT groups_json FROM notification_groups)
    ),
    'subscription_lifecycle', pg_catalog.jsonb_build_object(
        'pending_plan_change_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM latest_subscriptions AS ls
            WHERE ls.pending_plan_id IS NOT NULL
        ),
        'scheduled_cancellation_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM latest_subscriptions AS ls
            WHERE ls.cancellation_scheduled_at IS NOT NULL
        ),
        'pending_plan_and_cancellation_count', (
            SELECT pg_catalog.count(*)::BIGINT
            FROM latest_subscriptions AS ls
            WHERE ls.pending_plan_id IS NOT NULL
              AND ls.cancellation_scheduled_at IS NOT NULL
        )
    )
);
$function$;

ALTER FUNCTION public.get_platform_admin_billing_overview()
    OWNER TO postgres;

REVOKE EXECUTE ON FUNCTION public.get_platform_admin_billing_overview()
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.get_platform_admin_billing_overview()
    TO service_role;


CREATE OR REPLACE FUNCTION public.get_platform_admin_billing_companies(
    p_limit INTEGER,
    p_offset INTEGER,
    p_subscription_status TEXT,
    p_plan TEXT,
    p_attention BOOLEAN
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_limit INTEGER := p_limit;
    v_offset INTEGER := p_offset;
    v_subscription_status TEXT := NULLIF(pg_catalog.lower(pg_catalog.btrim(p_subscription_status)), '');
    v_plan TEXT := NULLIF(pg_catalog.lower(pg_catalog.btrim(p_plan)), '');
    v_result JSONB;
BEGIN
    IF v_limit IS NULL OR v_limit < 1 OR v_limit > 100 THEN
        RAISE EXCEPTION 'Invalid billing directory limit'
            USING ERRCODE = '22023';
    END IF;

    IF v_offset IS NULL OR v_offset < 0 THEN
        RAISE EXCEPTION 'Invalid billing directory offset'
            USING ERRCODE = '22023';
    END IF;

    IF p_subscription_status IS NOT NULL
       AND (
           v_subscription_status IS NULL
           OR v_subscription_status NOT IN ('trialing', 'active', 'past_due', 'expired', 'cancelled')
       ) THEN
        RAISE EXCEPTION 'Invalid billing directory subscription status'
            USING ERRCODE = '22023';
    END IF;

    IF p_plan IS NOT NULL
       AND (
           v_plan IS NULL
           OR pg_catalog.length(v_plan) > 50
       ) THEN
        RAISE EXCEPTION 'Invalid billing directory plan'
            USING ERRCODE = '22023';
    END IF;

    WITH
    latest_subscriptions AS (
        SELECT DISTINCT ON (cs.company_id)
            cs.company_id,
            cs.status,
            cs.plan_id,
            cs.current_period_start,
            cs.current_period_end,
            cs.pending_plan_id,
            cs.cancellation_scheduled_at
        FROM public.company_subscriptions AS cs
        ORDER BY cs.company_id, cs.created_at DESC, cs.id DESC
    ),
    subscription_attention AS (
        SELECT
            o.company_id,
            pg_catalog.count(*) FILTER (WHERE o.status IN ('pending', 'created'))::BIGINT AS pending_count,
            pg_catalog.count(*) FILTER (WHERE o.status = 'failed')::BIGINT AS failed_count,
            pg_catalog.count(*) FILTER (WHERE o.reconciliation_required IS TRUE)::BIGINT AS reconciliation_required_count,
            pg_catalog.count(*) FILTER (WHERE o.activation_status = 'failed')::BIGINT AS activation_failed_count,
            pg_catalog.count(*) FILTER (WHERE o.activation_status = 'conflict')::BIGINT AS activation_conflict_count
        FROM public.company_subscription_orders AS o
        GROUP BY o.company_id
    ),
    topup_attention AS (
        SELECT
            t.company_id,
            pg_catalog.count(*) FILTER (WHERE t.status = 'pending')::BIGINT AS pending_count,
            pg_catalog.count(*) FILTER (WHERE t.status = 'failed')::BIGINT AS failed_count,
            pg_catalog.count(*) FILTER (WHERE t.status = 'credited')::BIGINT AS credited_count
        FROM public.ai_credit_topup_orders AS t
        GROUP BY t.company_id
    ),
    filtered AS (
        SELECT
            c.id AS company_id,
            c.company_name,
            c.status AS company_status,
            sp.code AS plan_code,
            sp.name AS plan_name,
            ls.status AS subscription_status,
            ls.current_period_start,
            ls.current_period_end,
            (ls.pending_plan_id IS NOT NULL) AS pending_plan_change,
            (ls.cancellation_scheduled_at IS NOT NULL) AS cancellation_scheduled,
            (
                COALESCE(b.included_balance_micro_myr, 0)
                + COALESCE(b.topup_balance_micro_myr, 0)
            )::BIGINT AS ai_credit_total_balance_micro_myr,
            COALESCE(sa.pending_count, 0)::BIGINT AS subscription_pending_count,
            COALESCE(sa.failed_count, 0)::BIGINT AS subscription_failed_count,
            COALESCE(sa.reconciliation_required_count, 0)::BIGINT AS subscription_reconciliation_required_count,
            COALESCE(sa.activation_failed_count, 0)::BIGINT AS subscription_activation_failed_count,
            COALESCE(sa.activation_conflict_count, 0)::BIGINT AS subscription_activation_conflict_count,
            COALESCE(ta.pending_count, 0)::BIGINT AS topup_pending_count,
            COALESCE(ta.failed_count, 0)::BIGINT AS topup_failed_count,
            COALESCE(ta.credited_count, 0)::BIGINT AS topup_credited_count
        FROM public.companies AS c
        LEFT JOIN latest_subscriptions AS ls
          ON ls.company_id = c.id
        LEFT JOIN public.subscription_plans AS sp
          ON sp.id = ls.plan_id
        LEFT JOIN public.company_ai_credit_balances AS b
          ON b.company_id = c.id
        LEFT JOIN subscription_attention AS sa
          ON sa.company_id = c.id
        LEFT JOIN topup_attention AS ta
          ON ta.company_id = c.id
        WHERE c.status IN ('active', 'inactive')
          AND (
              ls.status IS NULL
              OR ls.status IN ('trialing', 'active', 'past_due', 'expired', 'cancelled')
          )
          AND (v_subscription_status IS NULL OR ls.status = v_subscription_status)
          AND (v_plan IS NULL OR pg_catalog.lower(sp.code) = v_plan)
          AND (
              p_attention IS NULL
              OR (
                  (
                      COALESCE(sa.pending_count, 0) > 0
                      OR COALESCE(sa.failed_count, 0) > 0
                      OR COALESCE(sa.reconciliation_required_count, 0) > 0
                      OR COALESCE(sa.activation_failed_count, 0) > 0
                      OR COALESCE(sa.activation_conflict_count, 0) > 0
                      OR COALESCE(ta.pending_count, 0) > 0
                      OR COALESCE(ta.failed_count, 0) > 0
                  ) = p_attention
              )
          )
    ),
    counted AS (
        SELECT pg_catalog.count(*)::BIGINT AS total
        FROM filtered
    ),
    paged AS (
        SELECT
            company_id,
            company_name,
            company_status,
            plan_code,
            plan_name,
            subscription_status,
            current_period_start,
            current_period_end,
            pending_plan_change,
            cancellation_scheduled,
            ai_credit_total_balance_micro_myr,
            subscription_pending_count,
            subscription_failed_count,
            subscription_reconciliation_required_count,
            subscription_activation_failed_count,
            subscription_activation_conflict_count,
            topup_pending_count,
            topup_failed_count,
            topup_credited_count
        FROM filtered
        ORDER BY company_id ASC
        LIMIT v_limit
        OFFSET v_offset
    )
    SELECT pg_catalog.jsonb_build_object(
        'companies', COALESCE((
            SELECT pg_catalog.jsonb_agg(
                pg_catalog.jsonb_build_object(
                    'company_id', p.company_id,
                    'company_name', p.company_name,
                    'company_status', p.company_status,
                    'current_plan', CASE
                        WHEN p.plan_code IS NULL THEN NULL
                        ELSE pg_catalog.jsonb_build_object(
                            'code', p.plan_code,
                            'name', p.plan_name
                        )
                    END,
                    'subscription_status', p.subscription_status,
                    'current_period_start', p.current_period_start,
                    'current_period_end', p.current_period_end,
                    'pending_plan_change', p.pending_plan_change,
                    'cancellation_scheduled', p.cancellation_scheduled,
                    'ai_credit_total_balance_micro_myr', p.ai_credit_total_balance_micro_myr,
                    'subscription_order_attention', pg_catalog.jsonb_build_object(
                        'pending_count', p.subscription_pending_count,
                        'failed_count', p.subscription_failed_count,
                        'reconciliation_required_count', p.subscription_reconciliation_required_count,
                        'activation_failed_count', p.subscription_activation_failed_count,
                        'activation_conflict_count', p.subscription_activation_conflict_count
                    ),
                    'topup_order_attention', pg_catalog.jsonb_build_object(
                        'pending_count', p.topup_pending_count,
                        'failed_count', p.topup_failed_count,
                        'credited_count', p.topup_credited_count
                    )
                )
                ORDER BY p.company_id
            )
            FROM paged AS p
        ), '[]'::JSONB),
        'pagination', pg_catalog.jsonb_build_object(
            'total', (SELECT total FROM counted),
            'limit', v_limit,
            'offset', v_offset
        )
    )
    INTO v_result;

    RETURN v_result;
END;
$function$;

ALTER FUNCTION public.get_platform_admin_billing_companies(INTEGER, INTEGER, TEXT, TEXT, BOOLEAN)
    OWNER TO postgres;

REVOKE EXECUTE ON FUNCTION public.get_platform_admin_billing_companies(INTEGER, INTEGER, TEXT, TEXT, BOOLEAN)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.get_platform_admin_billing_companies(INTEGER, INTEGER, TEXT, TEXT, BOOLEAN)
    TO service_role;


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
