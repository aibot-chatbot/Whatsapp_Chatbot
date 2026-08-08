"""Tenant support request submission routes."""

from flask import Blueprint, g, jsonify, request
from flask_limiter.util import get_remote_address

from app.decorators.auth_decorator import token_required
from app.rate_limit import limiter
from app.services import tenant_support_service


support_bp = Blueprint("support", __name__, url_prefix="/api/support")


def _tenant_support_rate_key():
    user_id = getattr(g, "user_id", None)
    if isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0:
        return f"tenant-support-user:{user_id}"
    return get_remote_address()


@support_bp.post("/requests")
@token_required
@limiter.limit("5/hour", key_func=_tenant_support_rate_key)
def submit_support_request():
    try:
        result = tenant_support_service.submit_tenant_support_request(
            request.get_json(silent=True),
            company_id=g.company_id,
            requester_user_id=g.user_id,
        )
        return jsonify({"status": "success", "data": result}), 200
    except tenant_support_service.TenantSupportServiceError as exc:
        return jsonify({
            "status": "error",
            "code": exc.code,
            "message": exc.message,
        }), exc.status_code
