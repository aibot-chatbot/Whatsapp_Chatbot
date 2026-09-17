"""billing_notification_service.py - Generation of billing notification events.

This service is the single source of notification generation for billing
events including subscription expiry reminders, grace-period alerts, payment
confirmations, activation outcomes, and AI-credit threshold alerts.

All notification creation is idempotent via event-key deduplication. Failure
to create a notification does not break the caller's core operation.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from app.database.billing_notification_repository import create_billing_notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# Notification types that also email the account owner.
#
# The test is whether the customer must DO something and would miss an in-app
# notice: credit running out stops their bots replying, and a lapsing
# subscription ends the service. Everything else stays in-app only.
#
# reconciliation_completed and activation_completed are deliberately absent.
# The first is internal housekeeping the customer never asked about; the second
# duplicates payment_confirmed for the same event, and emailing both would send
# two messages for one payment.
_EMAIL_NOTIFICATION_TYPES = frozenset({
    "ai_credit_low",
    "ai_credit_critical",
    "ai_credit_depleted",
    "subscription_expiry_reminder",
    "subscription_expired",
    "grace_period",
    "payment_confirmed",
    "activation_failed",
})


def _email_billing_contact(
    company_id: int, notification_type: str, severity: str, title: str, message: str
) -> None:
    """Email the account owner, when this notification type warrants one.

    The owner is the earliest active admin - the person who registered the
    company - rather than every admin, so a five-seat team gets one email and
    not five.

    Deliberately swallows every failure. The notification row is already written
    by the time this runs and the dashboard reads that row, so a bounced email,
    a company with no active owner, or an SMTP outage must never propagate back
    into a billing operation and roll it back. Delivery is best effort; the
    in-app notice is the system of record.
    """
    if notification_type not in _EMAIL_NOTIFICATION_TYPES:
        return
    try:
        from app.database.user_repository import get_company_billing_contact
        from app.services.email_service import send_billing_notification_email

        contact = get_company_billing_contact(company_id)
        if not contact:
            logger.info(
                "No active account owner for company %d; billing email skipped (type=%s)",
                company_id, notification_type,
            )
            return

        base = (os.getenv("FRONTEND_URL") or "").rstrip("/")
        send_billing_notification_email(
            contact["email"],
            title=title,
            message=message,
            severity=severity,
            recipient_name=contact["full_name"],
            action_label="Open billing" if base else None,
            action_url=(base + "/billing.html") if base else None,
        )
    except Exception as exc:
        logger.warning(
            "Billing email failed (type=%s, company=%d): %s",
            notification_type, company_id, exc,
        )


def _safe_notify(
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
) -> None:
    """Safely create a billing notification, isolating failures from callers."""
    try:
        create_billing_notification(
            company_id=company_id,
            notification_type=notification_type,
            severity=severity,
            title=title,
            message=message,
            event_key=event_key,
            reference_type=reference_type,
            reference_value=reference_value,
            expires_at=expires_at,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(
            "Failed to create billing notification (type=%s, company=%d): %s",
            notification_type, company_id, exc,
        )
        # The row is the system of record. If it did not land, do not email
        # about an event that is recorded nowhere.
        return

    _email_billing_contact(company_id, notification_type, severity, title, message)


# ---------------------------------------------------------------------------
# Subscription renewal reminders
# ---------------------------------------------------------------------------

def notify_subscription_expiry_reminder(
    company_id: int,
    subscription_id: int,
    period_end: str,
    days_remaining: int,
) -> None:
    """Generate a renewal reminder notification.

    Args:
        company_id: Company to notify.
        subscription_id: Subscription ID for reference.
        period_end: ISO-8601 period end date.
        days_remaining: Days until expiry (7, 3, 1, 0).
    """
    event_key = f"subscription:{subscription_id}:renewal_reminder:{days_remaining}d:{period_end}"

    if days_remaining > 0:
        title = f"Subscription expires in {days_remaining} day{'s' if days_remaining != 1 else ''}"
        message = (
            f"Your subscription period ends in {days_remaining} day{'s' if days_remaining != 1 else ''}. "
            "Renew now to avoid interruption."
        )
    else:
        title = "Subscription expires today"
        message = "Your subscription period ends today. Renew now to continue uninterrupted service."

    _safe_notify(
        company_id=company_id,
        notification_type="subscription_expiry_reminder",
        severity="warning",
        title=title,
        message=message,
        event_key=event_key,
        reference_type="subscription_id",
        reference_value=str(subscription_id),
    )


def notify_grace_period_started(
    company_id: int,
    subscription_id: int,
    period_end: str,
    grace_period_end: str,
) -> None:
    """Notify that the subscription has entered the grace period.

    Args:
        company_id: Company to notify.
        subscription_id: Subscription ID for reference.
        period_end: ISO-8601 period end date.
        grace_period_end: ISO-8601 grace period end date.
    """
    event_key = f"subscription:{subscription_id}:grace_started:{period_end}"

    _safe_notify(
        company_id=company_id,
        notification_type="grace_period",
        severity="warning",
        title="Subscription now in grace period",
        message=(
            f"Your subscription has entered the grace period, which ends on {grace_period_end}. "
            "Renew to restore full access and prevent service interruption."
        ),
        event_key=event_key,
        reference_type="subscription_id",
        reference_value=str(subscription_id),
        expires_at=grace_period_end,
    )


def notify_grace_period_ending(
    company_id: int,
    subscription_id: int,
    period_end: str,
    grace_period_end: str,
) -> None:
    """Notify that the grace period is ending soon.

    Args:
        company_id: Company to notify.
        subscription_id: Subscription ID for reference.
        period_end: ISO-8601 period end date.
        grace_period_end: ISO-8601 grace period end date.
    """
    event_key = f"subscription:{subscription_id}:grace_ending:{grace_period_end}"

    _safe_notify(
        company_id=company_id,
        notification_type="grace_period",
        severity="critical",
        title="Grace period ending tomorrow",
        message=(
            f"Your grace period ends on {grace_period_end}. "
            "Renew now to avoid subscription expiry and service interruption."
        ),
        event_key=event_key,
        reference_type="subscription_id",
        reference_value=str(subscription_id),
        expires_at=grace_period_end,
    )


def notify_subscription_expired(
    company_id: int,
    subscription_id: int,
    period_end: str,
) -> None:
    """Notify that the subscription has expired after the grace period.

    Args:
        company_id: Company to notify.
        subscription_id: Subscription ID for reference.
        period_end: ISO-8601 period end date.
    """
    event_key = f"subscription:{subscription_id}:expired:{period_end}"

    _safe_notify(
        company_id=company_id,
        notification_type="subscription_expired",
        severity="critical",
        title="Subscription has expired",
        message=(
            "Your subscription has expired. Renew now to restore access "
            "and continue using your chatbots and AI services."
        ),
        event_key=event_key,
        reference_type="subscription_id",
        reference_value=str(subscription_id),
    )


# ---------------------------------------------------------------------------
# Payment and activation notifications
# ---------------------------------------------------------------------------

def notify_payment_confirmed(
    company_id: int,
    order_reference: str,
) -> None:
    """Notify that a subscription payment has been confirmed.

    Args:
        company_id: Company to notify.
        order_reference: The subscription order reference.
    """
    event_key = f"payment:{order_reference}:confirmed"

    _safe_notify(
        company_id=company_id,
        notification_type="payment_confirmed",
        severity="info",
        title="Payment confirmed",
        message=(
            f"Your payment for order {order_reference} has been confirmed. "
            "We are now activating your subscription."
        ),
        event_key=event_key,
        reference_type="order_reference",
        reference_value=order_reference,
    )


def notify_activation_completed(
    company_id: int,
    order_reference: str,
) -> None:
    """Notify that subscription activation has completed successfully.

    Args:
        company_id: Company to notify.
        order_reference: The subscription order reference.
    """
    event_key = f"activation:{order_reference}:completed"

    _safe_notify(
        company_id=company_id,
        notification_type="activation_completed",
        severity="info",
        title="Subscription activated",
        message=(
            f"Your subscription for order {order_reference} has been activated. "
            "You now have access to your plan features and included AI credit."
        ),
        event_key=event_key,
        reference_type="order_reference",
        reference_value=order_reference,
    )


def notify_activation_failed(
    company_id: int,
    order_reference: str,
) -> None:
    """Notify that subscription activation failed and needs attention.

    Args:
        company_id: Company to notify.
        order_reference: The subscription order reference.
    """
    event_key = f"activation:{order_reference}:failed"

    _safe_notify(
        company_id=company_id,
        notification_type="activation_failed",
        severity="warning",
        title="Subscription activation needs attention",
        message=(
            f"Your payment for order {order_reference} was confirmed but "
            "activation could not complete automatically. "
            "Please contact support to resolve this."
        ),
        event_key=event_key,
        reference_type="order_reference",
        reference_value=order_reference,
    )


# ---------------------------------------------------------------------------
# AI-credit message helpers
# ---------------------------------------------------------------------------

def _ai_credit_low_message(balance_myr: float, is_trial: bool) -> str:
    """Build the low-credit notification message."""
    if is_trial:
        return (
            f"Your trial AI credit is running low (RM{balance_myr:.2f}). "
            "Upgrade to a paid plan for more AI credit and full model access."
        )
    return (
        f"Your company AI credit is low (RM{balance_myr:.2f}). "
        "Top up to avoid service interruption."
    )


def _ai_credit_critical_message(balance_myr: float, is_trial: bool) -> str:
    """Build the critical-credit notification message."""
    if is_trial:
        return (
            f"Your trial AI credit is critically low (RM{balance_myr:.2f}). "
            "Upgrade to a paid plan now to continue using AI features."
        )
    return (
        f"Your company AI credit is critically low (RM{balance_myr:.2f}). "
        "Top up immediately to prevent service interruption."
    )


def _ai_credit_depleted_message(is_trial: bool) -> str:
    """Build the depleted-credit notification message."""
    if is_trial:
        return (
            "Your trial AI credit has been fully used. "
            "Upgrade to a paid plan to continue using AI-powered features."
        )
    return (
        "Your company AI credit has been fully used. "
        "AI-powered features will not work until you top up."
    )


# ---------------------------------------------------------------------------
# AI-credit threshold alerts
# ---------------------------------------------------------------------------

def notify_ai_credit_low(
    company_id: int,
    total_balance_micro_myr: int,
    threshold_micro_myr: int,
    period_key: str,
    is_trial: bool = False,
) -> None:
    """Notify that AI credit is running low.

    Args:
        company_id: Company to notify.
        total_balance_micro_myr: Current total balance in micro-MYR.
        threshold_micro_myr: The threshold that was crossed.
        period_key: Current billing period key for deduplication.
        is_trial: True when the company is on the Free trial plan.
    """
    event_key = f"ai-credit:{company_id}:{period_key}:low"
    balance_myr = total_balance_micro_myr / 1_000_000

    _safe_notify(
        company_id=company_id,
        notification_type="ai_credit_low",
        severity="warning",
        title="AI credit running low",
        message=_ai_credit_low_message(balance_myr, is_trial),
        event_key=event_key,
        reference_type="company_id",
        reference_value=str(company_id),
    )


def notify_ai_credit_critical(
    company_id: int,
    total_balance_micro_myr: int,
    threshold_micro_myr: int,
    period_key: str,
    is_trial: bool = False,
) -> None:
    """Notify that AI credit is critically low.

    Args:
        company_id: Company to notify.
        total_balance_micro_myr: Current total balance in micro-MYR.
        threshold_micro_myr: The threshold that was crossed.
        period_key: Current billing period key for deduplication.
        is_trial: True when the company is on the Free trial plan.
    """
    event_key = f"ai-credit:{company_id}:{period_key}:critical"
    balance_myr = total_balance_micro_myr / 1_000_000

    _safe_notify(
        company_id=company_id,
        notification_type="ai_credit_critical",
        severity="critical",
        title="AI credit critically low",
        message=_ai_credit_critical_message(balance_myr, is_trial),
        event_key=event_key,
        reference_type="company_id",
        reference_value=str(company_id),
    )


def notify_ai_credit_depleted(
    company_id: int,
    period_key: str,
    is_trial: bool = False,
) -> None:
    """Notify that AI credit is fully depleted.

    Args:
        company_id: Company to notify.
        period_key: Current billing period key for deduplication.
        is_trial: True when the company is on the Free trial plan.
    """
    event_key = f"ai-credit:{company_id}:{period_key}:depleted"

    _safe_notify(
        company_id=company_id,
        notification_type="ai_credit_depleted",
        severity="critical",
        title="AI credit depleted",
        message=_ai_credit_depleted_message(is_trial),
        event_key=event_key,
        reference_type="company_id",
        reference_value=str(company_id),
    )


# ---------------------------------------------------------------------------
# Reconciliation notifications
# ---------------------------------------------------------------------------

def notify_reconciliation_completed(
    company_id: int,
    order_reference: str,
) -> None:
    """Notify that reconciliation completed for an order.

    Args:
        company_id: Company to notify.
        order_reference: The subscription order reference.
    """
    event_key = f"reconciliation:{order_reference}:completed"

    _safe_notify(
        company_id=company_id,
        notification_type="reconciliation_completed",
        severity="info",
        title="Subscription recovered",
        message=(
            f"Your subscription for order {order_reference} has been recovered "
            "and is now fully active."
        ),
        event_key=event_key,
        reference_type="order_reference",
        reference_value=order_reference,
    )
