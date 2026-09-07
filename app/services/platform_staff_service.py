"""Explicit staff grants and durable approval decisions, without execution."""

from app.database import platform_staff_repository as repository
from app.decorators.platform_admin_decorator import platform_access_context, PLATFORM_MODULES
from app.services.platform_admin_service import PlatformAdminServiceError, _safe_rpc_mapping, _safe_billing_order_response_row
from app.services.subscription_reconciliation_service import reconcile_subscription_order, RECONCILIATION_OUTCOMES


REQUEST_MODULES = {
    "refund": "billing", "manual_payment": "billing", "plan_change": "billing",
    "account_change": "customers", "suspension": "customers", "support_escalation": "support",
}
STATUSES = {"pending", "approved", "rejected"}


def _error(status, code, message):
    raise PlatformAdminServiceError(status, code, message)


def _positive_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _error(400, "invalid_id", "A positive integer ID is required.")
    return value


def _actor(mapping, *, module=None, super_only=False):
    access = platform_access_context(mapping)
    if access is None:
        _error(403, "platform_admin_access_denied", "Active platform staff access is required.")
    actor_id = _positive_id(mapping.get("id"))
    if (super_only and access["platform_role"] != "super_admin") or (module and not access["modules"].get(module)):
        _error(403, "platform_module_access_denied", "Your staff role does not permit this operation.")
    return actor_id, access


def _body(payload, keys):
    if not isinstance(payload, dict) or set(payload) != set(keys):
        _error(400, "invalid_request", "The request body contains missing or unsupported fields.")


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _error(400, "invalid_" + name, f"{name} must contain 1 to {maximum} characters.")
    return value.strip()


def _page(value, default, minimum, maximum):
    if value is None:
        return default
    if isinstance(value, bool) or not str(value).isdecimal():
        _error(400, "invalid_pagination", "Pagination must use non-negative integers.")
    number = int(value)
    if not minimum <= number <= maximum:
        _error(400, "invalid_pagination", "Pagination is outside the allowed range.")
    return number


def _call(operation):
    try:
        return operation()
    except PlatformAdminServiceError:
        raise
    except Exception as exc:
        code = str(getattr(exc, "code", ""))
        # PostgREST errors include PostgreSQL SQLSTATE; never expose SQL details.
        if code == "P0002":
            _error(404, "platform_record_not_found", "The requested record was not found.")
        if code == "23505":
            _error(409, "approval_already_decided", "This request already has a decision. Refresh to view it.")
        if code == "42501":
            _error(403, "platform_change_denied", "This change is not permitted; retain an active Super Admin and your own access.")
        if code in {"22023", "23514"}:
            _error(400, "invalid_request", "The requested change is invalid.")
        _error(503, "platform_staff_data_unavailable", "Platform staff data is temporarily unavailable.")


def _request(row):
    # Approval is a recorded decision. It does not imply execution of any action.
    return {**{key: row.get(key) for key in repository.REQUEST_FIELDS.split(",")},
            "execution_status": "not_executed"}


def _audit(actor_id, action, resource_id=None, method="GET", endpoint="/api/platform-admin/approval-requests"):
    _call(lambda: repository.audit_read(
        actor_id, action=action, resource_type="platform_approval_requests",
        resource_id=resource_id, endpoint=endpoint, method=method,
    ))


def list_approval_requests(mapping, *, limit=None, offset=None, status=None):
    actor_id, access = _actor(mapping)
    limit = _page(limit, 25, 1, 100)
    offset = _page(offset, 0, 0, 1000000)
    if status is not None and status not in STATUSES:
        _error(400, "invalid_status", "Unsupported request status.")
    requester_id = actor_id if access["platform_role"] == "admin" else None
    rows, total = _call(lambda: repository.list_requests(requester_id=requester_id, limit=limit, offset=offset, status=status))
    _audit(actor_id, "platform_admin.approval.list")
    return {"requests": [_request(row) for row in rows], "pagination": {
        "limit": limit, "offset": offset, "returned": len(rows), "total": total,
        "has_more": offset + len(rows) < total,
    }}


def get_approval_request(approval_id, mapping):
    actor_id, access = _actor(mapping)
    _positive_id(approval_id)
    requester_id = actor_id if access["platform_role"] == "admin" else None
    row = _call(lambda: repository.get_request(approval_id, requester_id=requester_id))
    if not row:
        _error(404, "approval_not_found", "Approval request not found.")
    _audit(actor_id, "platform_admin.approval.read", approval_id,
           endpoint="/api/platform-admin/approval-requests/<approval_id>")
    return {"request": _request(row)}


def create_approval_request(payload, mapping):
    _body(payload, {"type", "company_id", "summary", "reason"})
    request_type = payload.get("type")
    if not isinstance(request_type, str) or request_type not in REQUEST_MODULES:
        _error(400, "invalid_type", "Unsupported approval request type.")
    actor_id, _ = _actor(mapping, module=REQUEST_MODULES[request_type])
    company_id = _positive_id(payload["company_id"])
    summary = _text(payload["summary"], "summary", 240)
    reason = _text(payload["reason"], "reason", 2000)
    row = _call(lambda: repository.create_request(actor_id, request_type=request_type,
                                               company_id=company_id, summary=summary, reason=reason))
    return {"request": _request(row)}


def decide_approval_request(approval_id, payload, mapping):
    actor_id, _ = _actor(mapping, super_only=True)
    _positive_id(approval_id)
    _body(payload, {"status", "reason"})
    if payload["status"] not in ("approved", "rejected"):
        _error(400, "invalid_status", "Choose approved or rejected.")
    reason = _text(payload["reason"], "reason", 2000)
    row = _call(lambda: repository.decide_request(actor_id, approval_id, status=payload["status"], reason=reason))
    return {"request": _request(row)}


def set_staff_access(mapping_id, payload, mapping):
    actor_id, _ = _actor(mapping, super_only=True)
    _positive_id(mapping_id)
    _body(payload, {"platform_role", "modules", "reason"})
    if payload["platform_role"] not in ("super_admin", "admin"):
        _error(400, "invalid_platform_role", "Choose a valid platform role.")
    modules = payload["modules"]
    if not isinstance(modules, dict) or set(modules) != set(PLATFORM_MODULES) or any(type(v) is not bool for v in modules.values()):
        _error(400, "invalid_modules", "All three module grants must be booleans.")
    reason = _text(payload["reason"], "reason", 2000)
    if mapping_id == actor_id and payload["platform_role"] != "super_admin":
        _error(403, "self_demotion_denied", "You cannot remove your own Super Admin access.")
    row = _call(lambda: repository.set_access(actor_id, mapping_id,
                  platform_role=payload["platform_role"], modules=modules, reason=reason))
    return {"platform_admin_user": _safe_rpc_mapping(row)}


def recheck_billing_order(company_id, order_id, mapping):
    actor_id, _ = _actor(mapping, module="billing")
    _positive_id(company_id)
    _positive_id(order_id)
    row = _call(lambda: repository.get_stored_billing_order(company_id, order_id))
    if not row:
        _error(404, "billing_order_not_found", "Billing order not found for this company.")
    if row.get("company_id") != company_id:
        _error(404, "billing_order_not_found", "Billing order not found for this company.")
    gateway = row.get("payment_gateway")
    if gateway not in ("hitpay", "toyyibpay") or not row.get("order_reference"):
        _error(409, "gateway_recheck_unavailable", "This order requires manual gateway review.")
    if gateway == "toyyibpay" and row.get("status") not in ("paid", "credited"):
        _error(409, "gateway_recheck_unavailable", "ToyyibPay requires its verified callback before fulfillment can be retried.")
    # Persist intent before the existing idempotent recovery path can mutate.
    # No new charge, checkout, refund, force flag or unverified payment is created.
    _call(lambda: repository.audit_read(actor_id, action="platform_admin.billing.status_recheck",
          resource_type="company_billing_orders", resource_id=order_id, method="POST", outcome="attempted",
          endpoint="/api/platform-admin/companies/<company_id>/billing-orders/<order_id>/recheck"))
    result = _call(lambda: reconcile_subscription_order(row["order_reference"], company_id=company_id, force=False))
    outcome = result.get("outcome") if isinstance(result, dict) else None
    if outcome not in RECONCILIATION_OUTCOMES:
        _error(503, "gateway_recheck_unavailable", "The gateway recheck result is unavailable. Refresh the order before retrying.")
    _call(lambda: repository.audit_read(actor_id, action="platform_admin.billing.status_recheck",
          resource_type="company_billing_orders", resource_id=order_id, method="POST",
          endpoint="/api/platform-admin/companies/<company_id>/billing-orders/<order_id>/recheck"))
    refreshed = _call(lambda: repository.get_stored_billing_order(company_id, order_id))
    if not refreshed or refreshed.get("company_id") != company_id:
        _error(503, "gateway_recheck_unavailable", "The recheck completed but order refresh failed. Refresh the order before retrying.")
    return {"order": _safe_billing_order_response_row(refreshed), "source": "existing_reconciliation",
            "outcome": outcome, "message": "Payment recheck completed. Review the returned payment and activation status."}
