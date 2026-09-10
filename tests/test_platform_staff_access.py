"""Mocked role/module regression tests; no external calls or live credentials."""

import logging

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest
from flask import Flask

from app.decorators.platform_admin_decorator import platform_access_context
from app.routes.platform_admin_routes import platform_admin_bp
from app.services import platform_staff_service as service
from app.services.platform_admin_service import PlatformAdminServiceError
from app.database import platform_staff_repository as repository
from app.database import platform_admin_repository


def mapping(role="admin", **grants):
    return {"id": 3, "user_id": 7, "is_active": True, "platform_role": role,
            "modules": {name: grants.get(name, False) for name in ("billing", "support", "customers")}}


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(platform_admin_bp)
    with patch("app.decorators.auth_decorator.get_jwt_secret", return_value="test"), \
         patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 7, "role": "owner", "platform_role": "super_admin"}), \
         patch("app.database.user_repository.get_user_by_id", return_value={"id": 7, "company_id": 99, "status": "active", "role": "member"}), \
         patch("app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id", return_value=mapping()) as lookup:
        yield app.test_client(), lookup


HEADERS = {"Authorization": "Bearer mocked-token"}


@pytest.mark.parametrize("value", [None, {}, {"is_active": True}, {"is_active": True, "platform_role": "owner"}, {"is_active": False, "platform_role": "super_admin"}])
def test_unmapped_revoked_and_unknown_role_fail_closed(value):
    assert platform_access_context(value) is None


def test_exact_boolean_grants_and_super_full_control():
    value = mapping(billing=True, support="true", customers=1)
    assert platform_access_context(value)["modules"] == {"billing": True, "support": False, "customers": False}
    assert all(platform_access_context(mapping("super_admin"))["modules"].values())


@pytest.mark.parametrize("method,path", [
    ("get", "/overview"), ("get", "/audit-events"), ("get", "/platform-admin-users"),
    ("get", "/help/articles"), ("post", "/help/articles"),
    ("get", "/companies/9/users"), ("get", "/companies/9/chatbots"),
    ("post", "/companies/9/suspend"), ("post", "/companies/9/restore"),
    ("patch", "/platform-admin-users/8/active"), ("patch", "/platform-admin-users/8/access"),
    ("get", "/tenant-support-requests/4"), ("post", "/tenant-support-requests/4/convert"),
    ("post", "/approval-requests/4/decision"), ("post", "/support-cases"),
])
def test_staff_cannot_bypass_using_old_or_privileged_urls(client, method, path):
    browser, lookup = client
    lookup.return_value = mapping(billing=True, support=True, customers=True)
    response = getattr(browser, method)("/api/platform-admin" + path, headers=HEADERS, json={})
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/billing/overview", "/companies", "/support-cases", "/companies/9/subscription"])
def test_unassigned_module_denied(client, path):
    browser, _ = client
    assert browser.get("/api/platform-admin" + path, headers=HEADERS).status_code == 403


def test_missing_role_mapping_cannot_borrow_jwt_or_tenant_role(client):
    browser, lookup = client
    lookup.return_value = {"id": 3, "user_id": 7, "is_active": True}
    assert browser.get("/api/platform-admin/me", headers=HEADERS).status_code == 503


def test_permission_change_applies_next_request(client):
    browser, lookup = client
    lookup.side_effect = [mapping(billing=True), mapping()]
    with patch("app.services.platform_admin_service.get_billing_overview", return_value={}) as operation:
        assert browser.get("/api/platform-admin/billing/overview", headers=HEADERS).status_code == 200
        assert browser.get("/api/platform-admin/billing/overview", headers=HEADERS).status_code == 403
    operation.assert_called_once_with(3)


def test_own_requests_scoped_before_query_and_no_execution():
    row = {"id": 5, "status": "approved"}
    with patch.object(repository, "list_requests", return_value=([row], 1)) as query, \
         patch.object(repository, "audit_read"):
        result = service.list_approval_requests(mapping(), limit="10", offset="0")
    query.assert_called_once_with(requester_id=3, limit=10, offset=0, status=None)
    assert result["requests"][0]["execution_status"] == "not_executed"


def test_foreign_request_detail_returns_not_found():
    with patch.object(repository, "get_request", return_value=None) as query:
        with pytest.raises(PlatformAdminServiceError) as error:
            service.get_approval_request(9, mapping())
    assert error.value.status_code == 404
    query.assert_called_once_with(9, requester_id=3)


def test_requester_server_derived_and_spoofed_fields_rejected():
    payload = {"type": "refund", "company_id": 9, "summary": "Review refund", "reason": "Duplicate payment"}
    with patch.object(repository, "create_request", return_value={"id": 4}) as create:
        service.create_approval_request(payload, mapping(billing=True))
        create.assert_called_once_with(3, request_type="refund", company_id=9, summary="Review refund", reason="Duplicate payment")
        with pytest.raises(PlatformAdminServiceError) as error:
            service.create_approval_request({**payload, "requester_platform_admin_user_id": 1}, mapping(billing=True))
    assert error.value.status_code == 400


def test_request_type_requires_corresponding_module():
    with patch.object(repository, "create_request") as create:
        with pytest.raises(PlatformAdminServiceError) as error:
            service.create_approval_request({"type": "suspension", "company_id": 9, "summary": "Review", "reason": "Reason"}, mapping(billing=True))
    assert error.value.status_code == 403
    create.assert_not_called()


def test_admin_cannot_decide_and_super_requires_reason():
    with patch.object(repository, "decide_request") as decide:
        for actor, reason, code in [(mapping(billing=True), "Reason", 403), (mapping("super_admin"), "  ", 400)]:
            with pytest.raises(PlatformAdminServiceError) as error:
                service.decide_approval_request(4, {"status": "approved", "reason": reason}, actor)
            assert error.value.status_code == code
    decide.assert_not_called()


def test_duplicate_decision_conflict_and_database_error_sanitized():
    class Conflict(Exception):
        code = "23505"
    with patch.object(repository, "decide_request", side_effect=Conflict("private SQL details")):
        with pytest.raises(PlatformAdminServiceError) as error:
            service.decide_approval_request(4, {"status": "approved", "reason": "Verified"}, mapping("super_admin"))
    assert error.value.status_code == 409
    assert "SQL" not in error.value.message


def test_unexpected_repository_error_logs_traceback_and_preserves_503(caplog):
    private_error = "private database response body"
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger=service.logger.name):
        with pytest.raises(PlatformAdminServiceError) as error:
            service._call(lambda: (_ for _ in ()).throw(RuntimeError(private_error)))

    assert error.value.status_code == 503
    assert error.value.code == "platform_staff_data_unavailable"
    assert error.value.message == "Platform staff data is temporarily unavailable."
    records = [record for record in caplog.records if record.name == service.logger.name]
    assert len(records) == 1
    assert records[0].getMessage() == "Platform staff data operation failed"
    assert records[0].exc_info is not None
    assert private_error not in records[0].getMessage()


@pytest.mark.parametrize(
    "sqlstate,status,code,message",
    [
        ("P0002", 404, "platform_record_not_found", "The requested record was not found."),
        ("23505", 409, "approval_already_decided", "This request already has a decision. Refresh to view it."),
        ("42501", 403, "platform_change_denied", "This change is not permitted; retain an active Super Admin and your own access."),
        ("22023", 400, "invalid_request", "The requested change is invalid."),
        ("23514", 400, "invalid_request", "The requested change is invalid."),
    ],
)
def test_recognized_repository_errors_preserve_mapping_without_unexpected_log(
    sqlstate, status, code, message, caplog
):
    class RecognizedError(Exception):
        pass

    failure = RecognizedError("private database response body")
    failure.code = sqlstate
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger=service.logger.name):
        with pytest.raises(PlatformAdminServiceError) as error:
            service._call(lambda: (_ for _ in ()).throw(failure))

    assert error.value.status_code == status
    assert error.value.code == code
    assert error.value.message == message
    assert not [record for record in caplog.records if record.name == service.logger.name]


def test_self_demotion_denied_before_persistence():
    with patch.object(repository, "set_access") as update:
        with pytest.raises(PlatformAdminServiceError) as error:
            service.set_staff_access(3, {"platform_role": "admin", "modules": mapping()["modules"], "reason": "Change"}, mapping("super_admin"))
    assert error.value.status_code == 403
    update.assert_not_called()


def test_recheck_scopes_company_reuses_idempotent_service_and_audits_first():
    row = {"id": 6, "company_id": 9, "order_reference": "sample-order", "payment_gateway": "hitpay", "status": "pending"}
    sequence = []
    with patch.object(repository, "get_stored_billing_order", return_value=row) as query, \
         patch.object(repository, "audit_read", side_effect=lambda *a, **k: sequence.append("audit")), \
         patch.object(service, "reconcile_subscription_order", side_effect=lambda *a, **k: sequence.append("recheck") or {"outcome": "hitpay_pending"}) as reconcile:
        result = service.recheck_billing_order(9, 6, mapping(billing=True))
    assert sequence == ["audit", "recheck", "audit"]
    assert query.call_args_list[0].args == (9, 6)
    reconcile.assert_called_once_with("sample-order", company_id=9, force=False)
    assert result["outcome"] == "hitpay_pending"
    assert "order_reference" not in result["order"]


def test_audit_failure_prevents_recheck_mutation():
    row = {"id": 6, "company_id": 9, "order_reference": "sample-order", "payment_gateway": "hitpay", "status": "pending"}
    with patch.object(repository, "get_stored_billing_order", return_value=row), \
         patch.object(repository, "audit_read", side_effect=RuntimeError("secret")), \
         patch.object(service, "reconcile_subscription_order") as reconcile:
        with pytest.raises(PlatformAdminServiceError) as error:
            service.recheck_billing_order(9, 6, mapping(billing=True))
    assert error.value.status_code == 503
    reconcile.assert_not_called()


@pytest.mark.parametrize("row,status", [(None, 404), ({"company_id": 11}, 404),
    ({"company_id": 9, "payment_gateway": "toyyibpay", "order_reference": "x", "status": "pending"}, 409)])
def test_recheck_does_not_trust_unknown_or_unverified_order(row, status):
    with patch.object(repository, "get_stored_billing_order", return_value=row), \
         patch.object(service, "reconcile_subscription_order") as reconcile:
        with pytest.raises(PlatformAdminServiceError) as error:
            service.recheck_billing_order(9, 6, mapping(billing=True))
    assert error.value.status_code == status
    reconcile.assert_not_called()


def test_repository_scopes_requester_in_both_list_and_detail():
    mock = MagicMock()
    query = mock.table.return_value
    for method in ("select", "eq", "order", "range", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = MagicMock(data=[], count=0)
    with patch.object(repository, "supabase", mock):
        repository.list_requests(requester_id=3, limit=10, offset=0)
        repository.get_request(8, requester_id=3)
    assert query.eq.call_args_list[0].args == ("requester_platform_admin_user_id", 3)
    assert query.eq.call_args_list[-1].args == ("requester_platform_admin_user_id", 3)


def test_migration_is_additive_service_only_and_has_atomic_guards():
    sql = (Path(__file__).resolve().parents[1] / "data/053_platform_staff_roles_approvals.sql").read_text()
    assert "SECURITY DEFINER" not in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "LOCK TABLE public.platform_admin_users IN SHARE ROW EXCLUSIVE MODE" in sql
    assert "WHERE id = p_request_id FOR UPDATE" in sql
    assert "At least one active Super Admin is required" in sql
    assert "Self-demotion is not allowed" in sql
    assert "Approval request is already decided" in sql
    assert "FROM PUBLIC,anon,authenticated,service_role" in sql
    assert "UPDATE public.company_subscriptions" not in sql
    assert "PERFORM public.require_platform_staff_access(p_actor_platform_admin_user_id, NULL, TRUE)" in sql
    assert "UPDATE public.platform_admin_users SET platform_role = 'super_admin'" not in sql


@pytest.mark.parametrize("rows", [[], [{"id": 3, "user_id": 7, "is_active": False}]])
def test_login_mapping_probe_preserves_unmapped_tenants_before_migration(rows):
    mock = MagicMock()
    query = mock.table.return_value
    for method in ("select", "eq", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = MagicMock(data=rows)
    with patch.object(platform_admin_repository, "supabase", mock):
        result = platform_admin_repository.get_platform_admin_by_user_id(7)
    assert result == (rows[0] if rows else None)
    query.select.assert_called_once_with("id,user_id,is_active")


def test_active_mapping_disappearing_during_login_does_not_fall_back_to_tenant():
    mock = MagicMock()
    query = mock.table.return_value
    for method in ("select", "eq", "limit"):
        getattr(query, method).return_value = query
    query.execute.side_effect = [MagicMock(data=[{"id": 3, "user_id": 7, "is_active": True}]), MagicMock(data=[])]
    with patch.object(platform_admin_repository, "supabase", mock), pytest.raises(RuntimeError):
        platform_admin_repository.get_platform_admin_by_user_id(7)


def test_support_assignments_exclude_deactivated_application_users():
    mock = MagicMock()
    query = mock.table.return_value
    for method in ("select", "in_", "eq"):
        getattr(query, method).return_value = query
    query.execute.return_value = MagicMock(data=[{"id": 7}])
    with patch.object(repository, "supabase", mock):
        result = repository._active_user_mappings([{"id": 3, "user_id": 7}, {"id": 4, "user_id": 8}])
    assert result == [{"id": 3, "user_id": 7}]
    query.eq.assert_called_once_with("status", "active")
