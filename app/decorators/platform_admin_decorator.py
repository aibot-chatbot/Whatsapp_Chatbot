"""Fail-closed authorization for the separate platform-admin surface."""

import logging
from functools import wraps

from flask import g, jsonify

from app.decorators.auth_decorator import token_required
from app.database.platform_admin_repository import (
    get_active_platform_admin_by_user_id,
)


logger = logging.getLogger(__name__)


def platform_admin_required(view_function):
    """Require an active application user and active platform-admin mapping."""

    @token_required
    @wraps(view_function)
    def decorated(*args, **kwargs):
        authenticated_user = getattr(g, "authenticated_user", None)
        user_id = authenticated_user.get("id") if isinstance(authenticated_user, dict) else None
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            logger.error("Platform-admin guard missing authenticated user context")
            return jsonify({
                "status": "error",
                "code": "platform_admin_guard_misconfigured",
                "message": "Platform authorization is unavailable.",
            }), 500

        try:
            mapping = get_active_platform_admin_by_user_id(user_id)
        except Exception:
            logger.error("Platform-admin authorization backend unavailable")
            return jsonify({
                "status": "error",
                "code": "platform_admin_authorization_unavailable",
                "message": "Platform authorization is temporarily unavailable.",
            }), 503

        if not isinstance(mapping, dict) or mapping.get("is_active") is not True:
            return jsonify({
                "status": "error",
                "code": "platform_admin_access_denied",
                "message": "Platform administrator access is required.",
            }), 403

        g.platform_admin_user = mapping
        return view_function(*args, **kwargs)

    return decorated
