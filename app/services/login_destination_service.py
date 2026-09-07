"""Choose a login destination from the authoritative platform-staff mapping."""


class LoginDestinationError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def get_login_destination(user_id):
    from app.database.platform_admin_repository import get_platform_admin_by_user_id
    from app.decorators.platform_admin_decorator import platform_access_context

    try:
        mapping = get_platform_admin_by_user_id(user_id)
    except Exception as exc:
        raise LoginDestinationError(
            503, "platform_admin_authorization_unavailable",
            "Account access is temporarily unavailable. Please try again.",
        ) from exc
    if mapping is None:
        return "bots.html"
    if isinstance(mapping, dict) and mapping.get("is_active") is False:
        raise LoginDestinationError(
            403, "platform_admin_access_denied",
            "Your platform staff access has been revoked. Contact Super Admin.",
        )
    access = platform_access_context(mapping)
    if access is None:
        raise LoginDestinationError(
            503, "platform_admin_authorization_unavailable",
            "Your platform role is not configured. Contact Super Admin.",
        )
    return access["landing_page"]
