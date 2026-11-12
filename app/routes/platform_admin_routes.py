"""Privileged HTTP surface for separately authorized platform administrators."""

import logging

from flask import Blueprint, g, jsonify, request

from app.decorators.platform_admin_decorator import platform_admin_required
from app.services import platform_admin_help_article_service
from app.services import platform_admin_service
from app.services import platform_staff_service


logger = logging.getLogger(__name__)
platform_admin_bp = Blueprint(
    "platform_admin", __name__, url_prefix="/api/platform-admin"
)


@platform_admin_bp.before_request
@platform_admin_required
def require_platform_admin_for_blueprint():
    """Protect every route in this privileged blueprint by default."""
    if g.platform_access["platform_role"] == "super_admin":
        return None
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint in STAFF_COMMON_ENDPOINTS:
        return None
    module = STAFF_MODULE_ENDPOINTS.get(endpoint)
    if module and g.platform_access["modules"].get(module) is True:
        return None
    return jsonify({
        "status": "error", "code": "platform_module_access_denied",
        "message": "Your staff role does not permit this operation.",
    }), 403


# The allowlist is deliberate: new and legacy endpoints default to Super Admin.
STAFF_COMMON_ENDPOINTS = {
    "current_platform_admin", "approval_requests", "approval_request_detail",
    "create_approval_request",
}
STAFF_MODULE_ENDPOINTS = {
    **dict.fromkeys(("billing_overview", "billing_companies", "company_subscription",
                    "company_subscription_history", "company_ai_credit_usage",
                    "company_ai_credit_transactions", "company_billing_orders",
                    "recheck_billing_order"), "billing"),
    **dict.fromkeys(("companies", "company_detail"), "customers"),
    **dict.fromkeys(("support_cases", "support_case_assignees", "support_case_detail",
                    "support_case_replies", "create_support_case_reply",
                    "create_support_case_note", "assign_support_case",
                    "update_support_case_status"), "support"),
}


def _success(data):
    return jsonify({"status": "success", "data": data}), 200


def _execute(service_call):
    try:
        return _success(service_call())
    except platform_admin_service.PlatformAdminServiceError as exc:
        return jsonify({
            "status": "error", "code": exc.code, "message": exc.message,
        }), exc.status_code
    except Exception:
        logger.error("Unexpected platform-admin request failure")
        return jsonify({
            "status": "error",
            "code": "platform_admin_data_unavailable",
            "message": "Platform data is temporarily unavailable.",
        }), 503


def _actor_id():
    return g.platform_admin_user["id"]


def _actor_mapping():
    return g.platform_admin_user


@platform_admin_bp.get("/me")
def current_platform_admin():
    return _execute(lambda: platform_admin_service.get_current_platform_admin_identity(
        g.authenticated_user, g.platform_admin_user
    ))


@platform_admin_bp.get("/overview")
def operations_overview():
    return _execute(lambda: platform_admin_service.get_operations_overview(_actor_id()))


@platform_admin_bp.get("/billing/overview")
def billing_overview():
    return _execute(lambda: platform_admin_service.get_billing_overview(_actor_id()))


@platform_admin_bp.get("/billing/companies")
def billing_companies():
    return _execute(lambda: platform_admin_service.list_billing_companies(
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        subscription_status=request.args.get("subscription_status"),
        plan=request.args.get("plan"),
        attention=request.args.get("attention"),
    ))


@platform_admin_bp.get("/safety-flags")
def safety_flags():
    def read_flags():
        allowed = {"company_id", "category", "days", "limit"}
        if set(request.args) - allowed or any(len(request.args.getlist(key)) != 1 for key in request.args):
            raise platform_admin_service.PlatformAdminServiceError(
                400, "invalid_query", "Unsupported or repeated query parameter."
            )
        return platform_admin_service.list_safety_flags(_actor_id(), **request.args.to_dict())
    return _execute(read_flags)


@platform_admin_bp.get("/audit-events")
def audit_events():
    return _execute(lambda: platform_admin_service.list_audit_events(
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        action=request.args.get("action"),
        resource_type=request.args.get("resource_type"),
        actor_user_id=request.args.get("actor_user_id"),
        resource_id=request.args.get("resource_id"),
        created_after=request.args.get("created_after"),
        created_before=request.args.get("created_before"),
    ))


@platform_admin_bp.get("/platform-admin-users")
def platform_admin_users():
    return _execute(lambda: platform_admin_service.list_platform_admin_users(
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        is_active=request.args.get("is_active"),
    ))


@platform_admin_bp.get("/platform-admin-users/<int:mapping_id>")
def platform_admin_user_detail(mapping_id):
    return _execute(lambda: platform_admin_service.get_platform_admin_user(
        mapping_id, _actor_id()
    ))


@platform_admin_bp.post("/platform-admin-users")
def create_platform_admin_user():
    return _execute(lambda: platform_admin_service.create_platform_admin_user(
        request.get_json(silent=True), _actor_mapping()
    ))


@platform_admin_bp.patch("/platform-admin-users/<int:mapping_id>/active")
def set_platform_admin_user_active(mapping_id):
    return _execute(lambda: platform_admin_service.set_platform_admin_user_active(
        mapping_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.patch("/platform-admin-users/<int:mapping_id>/access")
def set_platform_staff_access(mapping_id):
    return _execute(lambda: platform_staff_service.set_staff_access(
        mapping_id, request.get_json(silent=True), _actor_mapping()
    ))


@platform_admin_bp.get("/approval-requests")
def approval_requests():
    return _execute(lambda: platform_staff_service.list_approval_requests(
        _actor_mapping(), limit=request.args.get("limit"), offset=request.args.get("offset"),
        status=request.args.get("status"),
    ))


@platform_admin_bp.get("/approval-requests/<int:approval_id>")
def approval_request_detail(approval_id):
    return _execute(lambda: platform_staff_service.get_approval_request(approval_id, _actor_mapping()))


@platform_admin_bp.post("/approval-requests")
def create_approval_request():
    return _execute(lambda: platform_staff_service.create_approval_request(
        request.get_json(silent=True), _actor_mapping()
    ))


@platform_admin_bp.post("/approval-requests/<int:approval_id>/decision")
def decide_approval_request(approval_id):
    return _execute(lambda: platform_staff_service.decide_approval_request(
        approval_id, request.get_json(silent=True), _actor_mapping()
    ))


@platform_admin_bp.get("/companies")
def companies():
    return _execute(lambda: platform_admin_service.list_companies(
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        search=request.args.get("search"),
        status=request.args.get("status"),
        sort_by=request.args.get("sort_by"),
        sort_order=request.args.get("sort_order"),
    ))


@platform_admin_bp.get("/companies/<int:company_id>")
def company_detail(company_id):
    return _execute(lambda: platform_admin_service.get_company_detail(company_id, _actor_id()))


@platform_admin_bp.post("/companies/<int:company_id>/suspend")
def suspend_company(company_id):
    return _execute(lambda: platform_admin_service.suspend_company(
        company_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.post("/companies/<int:company_id>/restore")
def restore_company(company_id):
    return _execute(lambda: platform_admin_service.restore_company(
        company_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.get("/companies/<int:company_id>/subscription")
def company_subscription(company_id):
    return _execute(lambda: platform_admin_service.get_company_subscription(company_id, _actor_id()))


@platform_admin_bp.get("/companies/<int:company_id>/subscription-history")
def company_subscription_history(company_id):
    return _execute(lambda: platform_admin_service.get_company_subscription_history(
        company_id,
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        status=request.args.get("status"),
    ))


@platform_admin_bp.get("/companies/<int:company_id>/ai-credit-usage")
def company_ai_credit_usage(company_id):
    return _execute(lambda: platform_admin_service.get_company_ai_credit_usage(company_id, _actor_id()))


@platform_admin_bp.get("/companies/<int:company_id>/ai-credit-transactions")
def company_ai_credit_transactions(company_id):
    return _execute(lambda: platform_admin_service.get_company_ai_credit_transactions(
        company_id,
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        transaction_type=request.args.get("transaction_type"),
    ))


@platform_admin_bp.get("/companies/<int:company_id>/billing-orders")
def company_billing_orders(company_id):
    return _execute(lambda: platform_admin_service.get_company_billing_orders(
        company_id,
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        status=request.args.get("status"),
        created_after=request.args.get("created_after"),
        created_before=request.args.get("created_before"),
    ))


@platform_admin_bp.post("/companies/<int:company_id>/billing-orders/<int:order_id>/recheck")
def recheck_billing_order(company_id, order_id):
    return _execute(lambda: platform_staff_service.recheck_billing_order(company_id, order_id, _actor_mapping()))


@platform_admin_bp.get("/companies/<int:company_id>/users")
def company_users(company_id):
    return _execute(lambda: platform_admin_service.get_company_users(
        company_id,
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        search=request.args.get("search"),
        sort_by=request.args.get("sort_by"),
        sort_order=request.args.get("sort_order"),
    ))


@platform_admin_bp.get("/companies/<int:company_id>/chatbots")
def company_chatbots(company_id):
    return _execute(lambda: platform_admin_service.get_company_chatbots(
        company_id,
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        search=request.args.get("search"),
        state=request.args.get("state"),
        sort_by=request.args.get("sort_by"),
        sort_order=request.args.get("sort_order"),
    ))


@platform_admin_bp.get("/support-cases")
def support_cases():
    return _execute(lambda: platform_admin_service.list_support_cases(
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        company_id=request.args.get("company_id"),
        status=request.args.get("status"),
        priority=request.args.get("priority"),
    ))


@platform_admin_bp.get("/support-case-assignees")
def support_case_assignees():
    return _execute(lambda: platform_admin_service.list_support_case_assignees(_actor_id()))


@platform_admin_bp.post("/support-cases")
def create_support_case():
    return _execute(lambda: platform_admin_service.create_support_case(
        request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.get("/support-cases/<int:case_id>")
def support_case_detail(case_id):
    return _execute(lambda: platform_admin_service.get_support_case(
        case_id,
        _actor_id(),
        event_limit=request.args.get("event_limit"),
        event_offset=request.args.get("event_offset"),
    ))


@platform_admin_bp.get("/support-cases/<int:case_id>/replies")
def support_case_replies(case_id):
    return _execute(lambda: platform_admin_service.list_support_case_replies(
        case_id,
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
    ))


@platform_admin_bp.post("/support-cases/<int:case_id>/replies")
def create_support_case_reply(case_id):
    return _execute(lambda: platform_admin_service.create_support_case_reply(
        case_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.post("/support-cases/<int:case_id>/notes")
def create_support_case_note(case_id):
    return _execute(lambda: platform_admin_service.add_support_case_note(
        case_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.patch("/support-cases/<int:case_id>/assignment")
def assign_support_case(case_id):
    return _execute(lambda: platform_admin_service.assign_support_case(
        case_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.patch("/support-cases/<int:case_id>/status")
def update_support_case_status(case_id):
    return _execute(lambda: platform_admin_service.update_support_case_status(
        case_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.patch("/support-cases/<int:case_id>/priority")
def update_support_case_priority(case_id):
    return _execute(lambda: platform_admin_service.update_support_case_priority(
        case_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.get("/tenant-support-requests")
def tenant_support_requests():
    return _execute(lambda: platform_admin_service.list_tenant_support_requests(
        _actor_id(),
        limit=request.args.get("limit"),
        offset=request.args.get("offset"),
        company_id=request.args.get("company_id"),
        category=request.args.get("category"),
        status=request.args.get("status"),
    ))


@platform_admin_bp.get("/tenant-support-requests/<int:request_id>")
def tenant_support_request_detail(request_id):
    return _execute(lambda: platform_admin_service.get_tenant_support_request(
        request_id, _actor_id()
    ))


@platform_admin_bp.patch("/tenant-support-requests/<int:request_id>")
def update_tenant_support_request(request_id):
    return _execute(lambda: platform_admin_service.update_tenant_support_request(
        request_id, request.get_json(silent=True), _actor_id()
    ))


@platform_admin_bp.post("/tenant-support-requests/<int:request_id>/convert")
def convert_tenant_support_request(request_id):
    raw_body = request.get_data(cache=True)
    payload = request.get_json(silent=True) if raw_body.strip() else {}
    if raw_body.strip() and payload is None:
        payload = {"_invalid_body": True}
    return _execute(lambda: platform_admin_service.convert_tenant_support_request(
        request_id, payload, _actor_id()
    ))


# Help article CRUD (FR-6). These share the blueprint's before_request guard,
# _execute's envelope and PlatformAdminServiceError's codes with every route
# above; the only thing new is the service module they delegate to.
@platform_admin_bp.get("/help/articles")
def help_articles():
    return _execute(platform_admin_help_article_service.list_help_articles)


@platform_admin_bp.post("/help/articles")
def create_help_article():
    return _execute(lambda: platform_admin_help_article_service.create_help_article(
        request.get_json(silent=True)
    ))


@platform_admin_bp.patch("/help/articles/<int:article_id>")
def update_help_article(article_id):
    return _execute(lambda: platform_admin_help_article_service.update_help_article(
        article_id, request.get_json(silent=True)
    ))


@platform_admin_bp.delete("/help/articles/<int:article_id>")
def delete_help_article(article_id):
    return _execute(lambda: platform_admin_help_article_service.delete_help_article(
        article_id
    ))
