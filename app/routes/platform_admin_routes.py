"""Read-only HTTP surface for separately authorized platform administrators."""

import logging

from flask import Blueprint, g, jsonify, request

from app.decorators.platform_admin_decorator import platform_admin_required
from app.services import platform_admin_service


logger = logging.getLogger(__name__)
platform_admin_bp = Blueprint(
    "platform_admin", __name__, url_prefix="/api/platform-admin"
)


@platform_admin_bp.before_request
@platform_admin_required
def require_platform_admin_for_blueprint():
    """Protect every route in this privileged blueprint by default."""


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


@platform_admin_bp.get("/me")
def current_platform_admin():
    return _execute(lambda: platform_admin_service.get_current_platform_admin_identity(
        g.authenticated_user, g.platform_admin_user
    ))


@platform_admin_bp.get("/overview")
def operations_overview():
    return _execute(lambda: platform_admin_service.get_operations_overview(_actor_id()))


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
