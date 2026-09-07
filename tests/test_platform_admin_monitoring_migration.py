import re
from pathlib import Path

from app.database import platform_admin_repository


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "037_platform_admin_monitoring_aggregates.sql"

# Migration 037 is immutable history. Later audit actions require a later
# migration; they must not retroactively change the approved Phase 6 allowlist.
PHASE_6_ACTIONS = frozenset("""
platform_admin.identity.read
platform_admin.operations.overview.read
platform_admin.company.list
platform_admin.company.read
platform_admin.company.subscription.read
platform_admin.company.ai_credit_usage.read
platform_admin.company.users.read
platform_admin.company.chatbots.read
platform_admin.company.subscription_history.read
platform_admin.company.ai_credit_transactions.read
platform_admin.company.billing_orders.read
platform_admin.company.suspend
platform_admin.company.restore
platform_admin.audit_events.list
platform_admin.support_case.list
platform_admin.support_case.read
platform_admin.support_case.create
platform_admin.support_case.note.create
platform_admin.support_case.assignee.list
platform_admin.support_case.assign
platform_admin.support_case.unassign
platform_admin.support_case.status.update
platform_admin.support_case.priority.update
platform_admin.support_case.reply.list
platform_admin.support_case.reply.create
platform_admin.tenant_support_request.list
platform_admin.tenant_support_request.read
platform_admin.tenant_support_request.review
platform_admin.tenant_support_request.close
platform_admin.tenant_support_request.convert
platform_admin.user.list
platform_admin.user.read
platform_admin.user.create
platform_admin.user.activate
platform_admin.user.deactivate
""".split())
PHASE_6_RESOURCE_TYPES = frozenset("""
company company_ai_credit_transactions company_ai_credit_usage
company_billing_orders company_chatbots company_subscription
company_subscription_history company_users platform_admin
platform_admin_audit_events platform_admin_users platform_operations_overview
platform_support_case_events platform_support_cases tenant_support_replies
tenant_support_requests
""".split())


def _sql():
    return MIGRATION.read_text(encoding="utf-8").lower()


def _function_body(sql):
    match = re.search(
        r"as \$function\$(?P<body>.*?)\$function\$;",
        sql,
        re.S,
    )
    assert match, "function body marker missing"
    return match.group("body")


def test_migration_037_exists_with_exact_monitoring_rpc_signature():
    sql = _sql()
    assert MIGRATION.name == "037_platform_admin_monitoring_aggregates.sql"
    assert "create or replace function public.get_platform_admin_monitoring_overview()" in sql
    assert "returns jsonb" in sql
    assert "language sql" in sql


def test_monitoring_rpc_security_posture_is_service_role_only():
    sql = _sql()
    assert "security invoker" in sql
    assert "set search_path to pg_catalog" in sql
    assert "alter function public.get_platform_admin_monitoring_overview()" in sql
    assert "owner to postgres" in sql
    assert "revoke execute on function public.get_platform_admin_monitoring_overview()" in sql
    assert "from public, anon, authenticated, service_role" in sql
    assert "grant execute on function public.get_platform_admin_monitoring_overview()" in sql
    assert "to service_role" in sql


def test_monitoring_rpc_has_no_dynamic_sql_or_mutations_in_function_body():
    body = _function_body(_sql())
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


def test_monitoring_rpc_uses_plain_coalesce_syntax():
    sql = _sql()
    assert "pg_catalog.coalesce" not in sql
    assert "coalesce(" in sql
    assert "coalesce(pg_catalog.sum(l.total_tokens), 0)::bigint" in sql
    assert "coalesce(b.included_balance_micro_myr, 0) = 0" in sql
    assert "coalesce(b.topup_balance_micro_myr, 0) = 0" in sql


def test_monitoring_rpc_uses_only_fixed_approved_tables():
    sql = _sql()
    for table in (
        "public.users",
        "public.platform_support_cases",
        "public.tenant_support_requests",
        "public.messages",
        "public.telegram_channels",
        "public.wasender_channels",
        "public.whatsapp_channels",
        "public.broadcast_campaigns",
        "public.broadcast_logs",
        "public.company_subscription_orders",
        "public.ai_usage_logs",
        "public.ai_credit_transactions",
        "public.company_ai_credit_balances",
        "public.platform_admin_audit_events",
    ):
        assert table in sql
    assert "from public.companies" not in sql
    assert "select *" not in sql


def test_monitoring_rpc_preserves_retry_backlog_semantics():
    sql = _sql()
    assert "m.sender_type = 'bot'" in sql
    assert "m.ai_generated is true" in sql
    assert "m.delivery_status = 'failed'" in sql
    assert "m.retry_count is null or m.retry_count < 3" in sql
    assert "m.next_retry_at is null or m.next_retry_at <= pg_catalog.now()" in sql


def test_monitoring_rpc_channel_attention_counts_distinct_rows_once():
    sql = _sql()
    assert "attention_required" in sql
    assert "pg_catalog.count(*) filter" in sql
    assert "ch.is_active is not true" in sql
    assert "ch.connection_status in ('disconnected', 'error')" in sql
    assert "by_connection_status" in sql
    assert "meta_whatsapp" in sql


def test_monitoring_rpc_returns_fixed_safe_sections_and_windows():
    sql = _sql()
    for key in (
        "'active_user_count'",
        "'support'",
        "'messaging'",
        "'billing_attention'",
        "'ai_usage'",
        "'platform_admin_activity'",
        "'cases_by_status'",
        "'cases_by_priority'",
        "'tenant_requests_by_status'",
        "'messages_by_delivery_status'",
        "'retry_backlog_count'",
        "'broadcast_campaigns_by_status'",
        "'broadcast_recipients_by_status'",
        "'orders_by_status'",
        "'reconciliation_required_count'",
        "'activation_statuses'",
        "'activation_status_unset_count'",
        "'requests_by_status'",
        "'recent_request_count'",
        "'recent_total_tokens'",
        "'credit_transactions_by_type'",
        "'depleted_balance_company_count'",
        "'events_by_action'",
        "'events_by_resource_type'",
    ):
        assert key in sql
    assert "'7 days'::interval" in sql
    assert "'days', 7" in sql


def test_monitoring_rpc_filters_audit_activity_to_frozen_phase_6_contract():
    sql = _sql()
    for column, expected in (("action", PHASE_6_ACTIONS), ("resource_type", PHASE_6_RESOURCE_TYPES)):
        allowlist = re.search(rf"and e\.{column} in \((.*?)\)", sql, re.S)
        assert allowlist, f"Missing {column} filter"
        assert set(re.findall(r"'([^']+)'", allowlist.group(1))) == expected
    # The current runtime must continue recognizing every historical metric.
    assert PHASE_6_ACTIONS <= platform_admin_repository.AUDIT_EVENT_SCHEMAS.keys()
    assert PHASE_6_RESOURCE_TYPES <= platform_admin_repository.ALLOWED_RESOURCE_TYPES
    assert "'platform_admin.support_case.update'" not in sql
    assert "delete from public.platform_admin_audit_events" not in sql
    assert "update public.platform_admin_audit_events" not in sql


def test_monitoring_rpc_does_not_select_sensitive_columns_or_payloads():
    sql = _sql()
    for forbidden in (
        "message_text",
        "recipient_phone",
        "phone_number",
        "prompt",
        "response_text",
        "provider_error",
        "provider_payload",
        "webhook_payload",
        "access_token",
        "api_key",
        "authorization",
        "payment_reference",
        "checkout_url",
        "gateway_customer",
        "metadata",
        "request_body",
        "response_body",
        "provider_cost",
    ):
        assert forbidden not in sql


def test_monitoring_migration_does_not_change_grants_rls_or_browser_table_access():
    sql = _sql()
    assert "enable row level security" not in sql
    assert "force row level security" not in sql
    assert "grant select" not in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "to anon" not in sql
    assert "to authenticated" not in sql
