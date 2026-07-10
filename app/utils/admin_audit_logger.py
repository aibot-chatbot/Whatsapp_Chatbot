"""
admin_audit_logger.py

Structured audit logging for sensitive admin/support operations.

Logs contain:
- actor user id
- target company id
- order reference where applicable
- safe action name
- result
- safe error code
- timestamp

Never logged:
- access tokens
- API secrets
- webhook signatures
- full provider payloads
- customer passwords
"""

import logging

logger = logging.getLogger(__name__)


def log_admin_action(
    action: str,
    actor_user_id: int | None = None,
    target_company_id: int | None = None,
    order_reference: str | None = None,
    result: str | None = None,
    error_code: str | None = None,
    detail: str | None = None,
):
    """Log a structured admin action for audit purposes."""
    parts = [f"action={action}"]
    if actor_user_id is not None:
        parts.append(f"actor={actor_user_id}")
    if target_company_id is not None:
        parts.append(f"company={target_company_id}")
    if order_reference:
        parts.append(f"order={order_reference}")
    if result:
        parts.append(f"result={result}")
    if error_code:
        parts.append(f"error={error_code}")
    if detail:
        parts.append(f"detail={detail}")
    logger.info("ADMIN: %s", " | ".join(parts))
