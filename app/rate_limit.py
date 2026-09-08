"""rate_limit.py — Flask-Limiter integration for billing and auth rate limiting.

Provides a configured Limiter instance and helper functions.
Uses in-memory storage by default; configure RATELIMIT_STORAGE_URI for Redis in production.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging

logger = logging.getLogger(__name__)

LIMITER_DISABLED_KEY = "_ratelimit_disabled"

def _get_company_or_ip():
    """Identify client by company_id if authenticated, else remote IP."""
    from flask import g, request
    try:
        if hasattr(g, "company_id") and g.company_id:
            return f"company:{g.company_id}"
    except RuntimeError:
        pass
    return get_remote_address()


def _on_rate_limit_breach(limit):
    """Log rate-limit breaches safely."""
    from flask import request
    logger.warning(
        "Rate limit breached: endpoint=%s method=%s limit=%s",
        request.endpoint,
        request.method,
        limit,
    )


# Stable unbound extension. Route decorators register against this instance at
# import time; create_app() binds it after loading each application's config.
limiter = Limiter(
    key_func=_get_company_or_ip,
    default_limits=None,
    on_breach=_on_rate_limit_breach,
)


def init_limiter(app):
    """Bind the shared limiter to an application using its loaded config."""
    limiter.init_app(app)
    logger.info(
        "Rate limiter initialized: enabled=%s",
        app.config.get("RATELIMIT_ENABLED", True),
    )
    return limiter
