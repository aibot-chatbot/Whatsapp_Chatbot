from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "036_platform_admin_company_suspension.sql"


def _sql():
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_migration_036_exists_and_constrains_company_status():
    sql = _sql()
    assert "alter table public.companies" in sql
    assert "alter column status set default 'active'" in sql
    assert "alter column status set not null" in sql
    assert "constraint companies_status_check" in sql
    assert "check (status in ('active', 'inactive'))" in sql
    assert "contains values outside active/inactive" in sql


def test_suspend_restore_rpcs_are_security_invoker_pg_catalog_service_role_only():
    sql = _sql()
    for name in ("suspend_platform_company", "restore_platform_company"):
        assert f"function public.{name}" in sql
    assert sql.count("security invoker") >= 2
    assert sql.count("set search_path to pg_catalog") >= 2
    assert "revoke execute on function public.suspend_platform_company(bigint, bigint)" in sql
    assert "revoke execute on function public.restore_platform_company(bigint, bigint)" in sql
    assert "from public, anon, authenticated, service_role" in sql
    assert "grant execute on function public.suspend_platform_company(bigint, bigint)" in sql
    assert "grant execute on function public.restore_platform_company(bigint, bigint)" in sql
    assert "to service_role" in sql


def test_rpcs_validate_actor_lock_company_reject_noop_and_protected_company():
    sql = _sql()
    assert "require_active_platform_admin_mapping" in sql
    assert "for update" in sql
    assert "company not found" in sql
    assert "company status is unchanged" in sql
    assert "platform_admin_protected_companies" in sql
    assert "protected platform-admin company cannot be suspended" in sql
    assert "v_company.status is distinct from 'active'" in sql
    assert "v_company.status is distinct from 'inactive'" in sql


def test_rpcs_update_only_status_and_updated_at_and_insert_audit_atomically():
    sql = _sql()
    assert re.search(r"update\s+public\.companies\s+set\s+status\s*=\s*'inactive'", sql, re.S)
    assert re.search(r"update\s+public\.companies\s+set\s+status\s*=\s*'active'", sql, re.S)
    assert "updated_at = v_now" in sql
    assert "insert into public.platform_admin_audit_events" in sql
    assert "'platform_admin.company.suspend'" in sql
    assert "'platform_admin.company.restore'" in sql
    assert "p_company_id::text" in sql
    assert "'resource_type'," not in sql
    assert "'company'," in sql
    assert "'endpoint', '/api/platform-admin/companies/<company_id>/suspend'" in sql
    assert "'endpoint', '/api/platform-admin/companies/<company_id>/restore'" in sql
    assert "'company_id', p_company_id" in sql
    assert "'old_status', v_old_status" in sql
    assert "'new_status', 'inactive'" in sql
    assert "'new_status', 'active'" in sql
    assert "v_company.status is distinct from 'active'" in sql
    assert "v_company.status is distinct from 'inactive'" in sql


def test_companies_privilege_hardening_preserves_required_service_role_access():
    sql = _sql()
    assert "revoke all on public.companies from public, anon, authenticated" in sql
    assert "revoke delete, truncate, references, trigger on public.companies from service_role" in sql
    assert "grant select, insert, update on public.companies to service_role" in sql
    assert "grant usage on sequence public.companies_id_seq to service_role" in sql
    assert "enable row level security" not in sql
    assert "force row level security" not in sql


def test_migration_036_does_not_seed_or_hardcode_shared_testing_company():
    sql = _sql()
    assert "company_id = 29" not in sql
    assert "values (29" not in sql
    assert "insert into public.platform_admin_protected_companies" not in sql


def test_migration_036_does_not_mutate_unrelated_tenant_objects():
    sql = _sql()
    assert "delete from public.companies" not in sql
    assert not re.search(r"update\s+public\.users\b", sql)
    assert not re.search(r"update\s+public\.subscriptions\b", sql)
    assert not re.search(r"update\s+public\.chatbots\b", sql)
    assert not re.search(r"update\s+public\.[a-z_]*channels\b", sql)
    assert not re.search(r"delete\s+from\s+public\.(users|subscriptions|chatbots|[a-z_]*channels)\b", sql)


def test_migration_036_remains_numbered_036():
    assert MIGRATION.name == "036_platform_admin_company_suspension.sql"
