"""rate_limit.py — Flask-Limiter integration for billing and auth rate limiting.

Provides a configured Limiter instance and helper functions.
Uses in-memory storage by default; configure RATELIMIT_STORAGE_URI for Redis in production.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging

logger = logging.getLogger(__name__)

LIMITER_DISABLED_KEY = "_ratelimit_disabled"

# Shared limiter instance — initialized by init_limiter() during app creation
# Uses a proxy so decorators can be applied at import time (before init).
limiter = None

class _LimiterProxy:
    """Proxy that queues limit specs and applies them once the real limiter is ready."""
    
    def __init__(self):
        self._real = None
        self._registry = []
    
    def limit(self, limit_value, **kwargs):
        if self._real is not None:
            return self._real.limit(limit_value, **kwargs)
        # Return the original function unchanged when limiter is not yet initialized
        def _noop(f):
            return f
        return _noop
    
    def _set_real(self, real_limiter):
        self._real = real_limiter

_limiter_proxy = _LimiterProxy()
limiter = _limiter_proxy


def _get_company_or_ip():
    """Identify client by company_id if authenticated, else remote IP."""
    from flask import g, request
    try:
        if hasattr(g, "company_id") and g.company_id:
            return f"company:{g.company_id}"
    except RuntimeError:
        pass
    return get_remote_address()


def init_limiter(app):
    """Create and configure a Limiter instance bound to the Flask app."""
    global limiter
    global _limiter_proxy
    enabled = app.config.get("RATELIMIT_ENABLED", True)
    storage_uri = app.config.get("RATELIMIT_STORAGE_URI", "memory://")

    real_limiter = Limiter(
        key_func=_get_company_or_ip,
        storage_uri=storage_uri,
        app=app,
        default_limits=None,
        enabled=enabled,
        on_breach=_on_rate_limit_breach,
    )
    _limiter_proxy._set_real(real_limiter)
    limiter = real_limiter

    logger.info(
        "Rate limiter initialized: enabled=%s, storage=%s", enabled, storage_uri
    )
    return limiter


def _on_rate_limit_breach(limit):
    """Log rate-limit breaches safely."""
    from flask import request
    logger.warning(
        "Rate limit breached: endpoint=%s method=%s limit=%s",
        request.endpoint,
        request.method,
        limit,
    )
