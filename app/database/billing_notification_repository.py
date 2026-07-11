"""billing_notification_repository.py - Company-scoped billing notification persistence.

Provides CRUD operations for the billing_notifications table, enforcing
company-level tenant isolation on all queries.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.database.db import supabase

logger = logging.getLogger(__name__)

TABLE_NAME = "billing_notifications"

# Severity levels allowed for notification creation.
ALLOWED_SEVERITIES = frozenset({"info", "warning", "critical"})

# Max length constraints to prevent excessively large text.
MAX_TITLE_LENGTH = 200
MAX_MESSAGE_LENGTH = 1000
MAX_EVENT_KEY_LENGTH = 200
MAX_REFERENCE_VALUE_LENGTH = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_company_id(company_id):
    """Validate that company_id is a positive integer or numeric string.

    Follows the pattern used by other billing repositories — accepts
    both int and string values from JWT payloads.
    """
    if not company_id:
        raise ValueError(f"Invalid company_id: {company_id}")
    try:
        val = int(company_id)
        if val < 1:
            raise ValueError(f"Invalid company_id: {company_id}")
    except (ValueError, TypeError):
        raise ValueError(f"Invalid company_id: {company_id}")


def _validate_severity(severity: str):
    if severity not in ALLOWED_SEVERITIES:
        raise ValueError(
            f"Invalid severity '{severity}'. Allowed: {', '.join(sorted(ALLOWED_SEVERITIES))}"
        )


def _truncate(value: str | None, max_len: int) -> str | None:
    if value is not None and len(value) > max_len:
        return value[:max_len]
    return value


def _single_row(response: Any, label: str) -> dict | None:
    """Return the first row or None."""
    data = response.data if hasattr(response, "data") else response
    if data and len(data) > 0:
        return data[0]
    return None


def create_billing_notification(
    company_id: int,
    notification_type: str,
    severity: str,
    title: str,
    message: str,
    event_key: str,
    reference_type: str | None = None,
    reference_value: str | None = None,
    expires_at: str | None = None,
    metadata: dict | None = None,
) -> dict | None:
    """Create a billing notification with idempotent event-key deduplication.

    If a notification with the same event_key already exists for the company,
    the existing record is returned and no duplicate is created.

    Args:
        company_id: The owning company.
        notification_type: Category (subscription_expiry_reminder, etc.).
        severity: info, warning, or critical.
        title: Short notification title.
        message: Notification body text.
        event_key: Unique deduplication key scoped to the company.
        reference_type: Optional resource type (order_reference, subscription_id).
        reference_value: Optional resource value.
        expires_at: Optional ISO-8601 expiry timestamp for the notification.
        metadata: Optional safe JSON metadata.

    Returns:
        The notification dict or None if creation failed silently (duplicate).
    """
    _validate_company_id(company_id)
    _validate_severity(severity)

    # Check for existing notification with this event_key
    existing = get_notification_by_event_key(company_id, event_key)
    if existing:
        logger.info(
            "Billing notification already exists for company %d event_key=%s (id=%d)",
            company_id, event_key, existing["id"],
        )
        return None

    now = _now_iso()
    safe_metadata = metadata if metadata else {}
    record = {
        "company_id": company_id,
        "notification_type": _truncate(notification_type, 100),
        "severity": severity,
        "title": _truncate(title, MAX_TITLE_LENGTH),
        "message": _truncate(message, MAX_MESSAGE_LENGTH),
        "event_key": _truncate(event_key, MAX_EVENT_KEY_LENGTH),
        "reference_type": _truncate(reference_type, 100),
        "reference_value": _truncate(reference_value, MAX_REFERENCE_VALUE_LENGTH),
        "expires_at": expires_at,
        "metadata": safe_metadata,
        "created_at": now,
        "is_read": False,
    }

    try:
        response = (
            supabase.table(TABLE_NAME)
            .insert(record)
            .execute()
        )
        row = _single_row(response, "create_billing_notification")
        if row:
            logger.info(
                "Created billing notification for company %d type=%s event_key=%s (id=%d)",
                company_id, notification_type, event_key, row["id"],
            )
            return row
        logger.warning(
            "No row returned creating billing notification for company %d event_key=%s",
            company_id, event_key,
        )
        return None
    except Exception as exc:
        # If a concurrent insert created the same event_key, the DB constraint
        # will raise IntegrityError, which is safe to log and return None.
        logger.warning(
            "Failed to create billing notification for company %d event_key=%s: %s",
            company_id, event_key, exc,
        )
        return None


def get_notification_by_event_key(
    company_id: int, event_key: str
) -> dict | None:
    """Fetch a notification by company_id and event_key.

    Returns the notification dict or None.
    """
    _validate_company_id(company_id)
    try:
        response = (
            supabase.table(TABLE_NAME)
            .select("*")
            .eq("company_id", company_id)
            .eq("event_key", event_key)
            .limit(1)
            .execute()
        )
        return _single_row(response, "get_notification_by_event_key")
    except Exception as exc:
        logger.error(
            "Error fetching notification by event_key for company %d: %s",
            company_id, exc,
        )
        return None


def list_billing_notifications(
    company_id: int,
    limit: int = 20,
    offset: int = 0,
    unread_only: bool = False,
) -> list[dict]:
    """List billing notifications for a company, newest first.

    Args:
        company_id: The owning company.
        limit: Maximum rows to return (default 20, max 100).
        offset: Pagination offset.
        unread_only: If True, filter to unread notifications only.

    Returns:
        List of notification dicts.
    """
    _validate_company_id(company_id)
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)

    try:
        query = (
            supabase.table(TABLE_NAME)
            .select("*")
            .eq("company_id", company_id)
            .order("created_at", desc=True)
            .limit(safe_limit)
            .offset(safe_offset)
        )
        if unread_only:
            query = query.eq("is_read", False)

        response = query.execute()
        data = response.data if hasattr(response, "data") else []
        return data if data else []
    except Exception as exc:
        logger.error(
            "Error listing billing notifications for company %d: %s",
            company_id, exc,
        )
        return []


def count_unread_billing_notifications(company_id: int) -> int:
    """Count unread billing notifications for a company.

    Args:
        company_id: The owning company.

    Returns:
        Unread notification count.
    """
    _validate_company_id(company_id)
    try:
        response = (
            supabase.table(TABLE_NAME)
            .select("id", count="exact")
            .eq("company_id", company_id)
            .eq("is_read", False)
            .execute()
        )
        return response.count if hasattr(response, "count") and response.count is not None else 0
    except Exception as exc:
        logger.error(
            "Error counting unread notifications for company %d: %s",
            company_id, exc,
        )
        return 0


def mark_billing_notification_read(company_id: int, notification_id: int) -> bool:
    """Mark a single notification as read, scoped to the company.

    Args:
        company_id: The owning company (tenant isolation).
        notification_id: The notification ID to mark.

    Returns:
        True if a row was updated, False if not found or already read.
    """
    _validate_company_id(company_id)
    try:
        now = _now_iso()
        response = (
            supabase.table(TABLE_NAME)
            .update({
                "is_read": True,
                "read_at": now,
            })
            .eq("id", notification_id)
            .eq("company_id", company_id)
            .eq("is_read", False)
            .execute()
        )
        data = response.data if hasattr(response, "data") else []
        return len(data) > 0
    except Exception as exc:
        logger.error(
            "Error marking notification %d read for company %d: %s",
            notification_id, company_id, exc,
        )
        return False


def mark_all_billing_notifications_read(company_id: int) -> int:
    """Mark all unread notifications as read for the company.

    Args:
        company_id: The owning company.

    Returns:
        Number of notifications marked read.
    """
    _validate_company_id(company_id)
    try:
        now = _now_iso()
        response = (
            supabase.table(TABLE_NAME)
            .update({
                "is_read": True,
                "read_at": now,
            })
            .eq("company_id", company_id)
            .eq("is_read", False)
            .execute()
        )
        data = response.data if hasattr(response, "data") else []
        updated_count = len(data) if data else 0
        logger.info(
            "Marked %d notifications read for company %d",
            updated_count, company_id,
        )
        return updated_count
    except Exception as exc:
        logger.error(
            "Error marking all notifications read for company %d: %s",
            company_id, exc,
        )
        return 0
