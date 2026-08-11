import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "038_platform_admin_billing_oversight.sql"


def _sql():
    return MIGRATION.read_text(encoding="utf-8").lower()


def _function_body(sql, function_name):
    match = re.search(
        rf"create or replace function public\.{function_name}\(.*?as \$function\$(?P<body>.*?)\$function\$;",
        sql,
        re.S,
    )
    assert match, f"{function_name} function body marker missing"
    return match.group("body")


def test_migration_038_exists_with_exact_read_only_rpc_signature():
    sql = _sql()
    assert MIGRATION.name == "038_platform_admin_billing_oversight.sql"
    assert "create or replace function public.get_platform_admin_billing_overview()" in sql
    assert "create or replace function public.get_platform_admin_billing_companies(" in sql
    assert "create or replace function public.get_platform_admin_monitoring_overview()" in sql
    assert "p_limit integer" in sql
    assert "p_offset integer" in sql
    assert "p_subscription_status text" in sql
    assert "p_plan text" in sql
    assert "p_attention boolean" in sql
    assert "returns jsonb" in sql
    assert "language sql" in sql
    assert "language plpgsql" in sql


def test_billing_oversight_rpc_security_posture_is_service_role_only():
    sql = _sql()
    assert "security invoker" in sql
    assert "set search_path to pg_catalog" in sql
    for signature in (
        "public.get_platform_admin_billing_overview()",
        "public.get_platform_admin_billing_companies(integer, integer, text, text, boolean)",
        "public.get_platform_admin_monitoring_overview()",
    ):
        assert f"alter function {signature}" in sql
        assert f"revoke execute on function {signature}" in sql
        assert f"grant execute on function {signature}" in sql
    assert sql.count("owner to postgres") >= 2
    assert sql.count("from public, anon, authenticated, service_role") >= 2
    assert sql.count("to service_role") >= 2


def test_billing_oversight_rpc_has_no_dynamic_sql_or_writes():
    sql = _sql()
    for function_name in (
        "get_platform_admin_billing_overview",
        "get_platform_admin_billing_companies",
        "get_platform_admin_monitoring_overview",
    ):
        body = _function_body(sql, function_name)
        for forbidden in (
            "execute ",
            "insert into",
            "update public.",
            "delete from",
            "truncate",
            "alter table",
            "create table",
            "drop table",
            "grant ",
            "revoke ",
            "platform_admin_audit_events (",
        ):
            assert forbidden not in body


def test_billing_oversight_rpc_uses_only_fixed_approved_tables():
    sql = _sql()
    for table in (
        "public.company_subscriptions",
        "public.subscription_plans",
        "public.company_subscription_orders",
        "public.ai_credit_topup_orders",
        "public.company_ai_credit_balances",
        "public.ai_credit_transactions",
        "public.ai_usage_logs",
        "public.billing_notifications",
        "public.companies",
    ):
        assert table in sql
    assert "select *" not in sql
    overview_body = _function_body(sql, "get_platform_admin_billing_overview")
    assert "public.messages" not in overview_body
    assert "public.users" not in overview_body


def test_billing_oversight_rpc_returns_fixed_safe_sections_and_null_activation_buckets():
    sql = _sql()
    for key in (
        "'generated_at'",
        "'subscriptions'",
        "'subscription_orders'",
        "'topup_orders'",
        "'ai_credit'",
        "'ai_usage'",
        "'billing_notifications'",
        "'subscription_lifecycle'",
        "'by_status'",
        "'by_plan'",
        "'active_plan_catalogue'",
        "'price_sen'",
        "'orders_by_status'",
        "'pending_count'",
        "'failed_count'",
        "'reconciliation_required_count'",
        "'activation_statuses'",
        "'activation_status_unset_count'",
        "'activation_types'",
        "'activation_type_unset_count'",
        "'balance_row_count'",
        "'depleted_company_count'",
        "'transactions_by_type'",
        "'requests_by_status'",
        "'recent_request_count'",
        "'recent_total_tokens'",
        "'by_type_severity_read_state'",
        "'pending_plan_change_count'",
        "'scheduled_cancellation_count'",
    ):
        assert key in sql
    assert "where o.activation_status is null" in sql
    assert "where o.activation_type is null" in sql
    assert "'7 days'::interval" in sql
    assert "'days', 7" in sql
    assert "'price'," not in sql
    assert "pg_catalog.round(sp.price * 100)::bigint as price_sen" in sql


def test_billing_directory_rpc_paginates_filters_and_counts_in_postgresql():
    sql = _sql()
    body = _function_body(sql, "get_platform_admin_billing_companies")
    assert "select distinct on (cs.company_id)" in body
    assert "order by cs.company_id, cs.created_at desc, cs.id desc" in body
    assert "from public.companies as c" in body
    assert "left join latest_subscriptions as ls" in body
    assert "on ls.company_id = c.id" in body
    assert "from latest_subscriptions as ls\n        join public.companies" not in body
    assert "filtered as (" in body
    assert "counted as (" in body
    assert "select pg_catalog.count(*)::bigint as total" in body
    assert "paged as (" in body
    assert "order by company_id asc" in body
    assert "limit v_limit" in body
    assert "offset v_offset" in body
    assert "v_subscription_status is null or ls.status = v_subscription_status" in body
    assert "ls.status is null" in body
    assert "v_plan is null or pg_catalog.lower(sp.code) = v_plan" in body
    assert ") = p_attention" in body
    assert "coalesce(ta.credited_count, 0) > 0" not in body
    assert "'pagination'" in body
    assert "'companies'" in body
    assert "directory_scan" not in body
    assert "10000" not in body


def test_billing_directory_rpc_preserves_null_subscription_contract():
    body = _function_body(_sql(), "get_platform_admin_billing_companies")
    assert "'subscription_status', p.subscription_status" in body
    assert "'current_plan', case" in body
    assert "when p.plan_code is null then null" in body
    assert "'current_period_start', p.current_period_start" in body
    assert "'current_period_end', p.current_period_end" in body
    assert "(ls.pending_plan_id is not null) as pending_plan_change" in body
    assert "(ls.cancellation_scheduled_at is not null) as cancellation_scheduled" in body


def test_billing_directory_rpc_validates_arguments_at_sql_boundary():
    body = _function_body(_sql(), "get_platform_admin_billing_companies")
    assert "v_limit is null or v_limit < 1 or v_limit > 100" in body
    assert "v_offset is null or v_offset < 0" in body
    assert "v_subscription_status not in ('trialing', 'active', 'past_due', 'expired', 'cancelled')" in body
    assert "pg_catalog.length(v_plan) > 50" in body
    assert "raise exception 'invalid billing directory limit'" in body
    assert "raise exception 'invalid billing directory subscription status'" in body


def test_migration_038_extends_monitoring_audit_allowlist_for_phase_7_without_obsolete_action():
    body = _function_body(_sql(), "get_platform_admin_monitoring_overview")
    assert "'platform_admin.billing.overview.read'" in body
    assert "'platform_admin.billing.company_list'" in body
    assert "'platform_billing_overview'" in body
    assert "'platform_billing_companies'" in body
    assert "'platform_admin.support_case.update'" not in body
    assert "public.platform_admin_audit_events as e" in body


def test_billing_oversight_rpc_keeps_subscription_and_topup_order_domains_separate():
    sql = _sql()
    subscription_section = sql.index("'subscription_orders'")
    topup_section = sql.index("'topup_orders'")
    assert subscription_section < topup_section
    assert "from public.company_subscription_orders" in sql[subscription_section:topup_section]
    assert "from public.ai_credit_topup_orders" not in sql[subscription_section:topup_section]
    assert "from public.ai_credit_topup_orders" in sql[topup_section:]


def test_billing_oversight_rpc_uses_approved_bounded_domains():
    sql = _sql()
    for value in (
        "'trialing'",
        "'active'",
        "'past_due'",
        "'expired'",
        "'cancelled'",
        "'pending'",
        "'created'",
        "'paid'",
        "'credited'",
        "'failed'",
        "'not_started'",
        "'claimed'",
        "'activated'",
        "'credit_pending'",
        "'completed'",
        "'conflict'",
        "'initial_purchase'",
        "'renewal'",
        "'upgrade'",
        "'included_credit_grant'",
        "'trial_credit_grant'",
        "'usage_debit'",
        "'topup_purchase'",
        "'refund'",
        "'manual_adjustment'",
        "'expiry'",
        "'reversal'",
        "'info'",
        "'warning'",
        "'critical'",
    ):
        assert value in sql
    assert "activation_status null" not in sql
    assert "activation_status is null" in sql
    assert "'activation_failed_count'" in sql


def test_billing_oversight_rpc_does_not_expose_sensitive_financial_or_customer_fields():
    sql = _sql()
    for forbidden in (
        "email",
        "phone",
        "payment_reference",
        "checkout_url",
        "gateway",
        "customer_id",
        "idempotency",
        "payload",
        "raw_error",
        "reconciliation_error",
        "provider_cost",
        "prompt",
        "response_text",
        "message_text",
        "metadata",
    ):
        assert forbidden not in sql
    overview_body = _function_body(sql, "get_platform_admin_billing_overview")
    assert "company_name" not in overview_body
    directory_body = _function_body(sql, "get_platform_admin_billing_companies")
    assert "'company_name'" in directory_body
    assert "'investigation_url'" not in directory_body


def test_billing_oversight_migration_does_not_change_grants_rls_or_browser_table_access():
    sql = _sql()
    assert "enable row level security" not in sql
    assert "force row level security" not in sql
    assert "grant select" not in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "to anon" not in sql
    assert "to authenticated" not in sql
