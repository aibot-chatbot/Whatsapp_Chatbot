"""subscription_lifecycle_service.py \u2014 Safe subscription state transitions and scheduling.

This module is the single authority for changing subscription status and
scheduling plan changes or cancellations.  All subscription transitions
must go through this service so that the state machine is enforced
consistently.

Allowed transitions:
    trialing  -> active, expired
    active    -> past_due, expired, cancelled
    past_due  -> active, expired, cancelled
    expired   -> active
    cancelled -> active

Disallowed:
    Any transition TO trialing.
    expired/cancelled -> anything except active.
    Same-status transitions are idempotent (return without error).
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from app.database.company_subscription_repository import (
    get_company_subscription as _get_current_sub,
    get_latest_company_subscription as _get_latest_sub,
    update_subscription_status_if_current as _update_status_conditional,
    update_company_subscription as _update_sub,
)
from app.database.subscription_plan_repository import get_plan_by_id
from app.services.free_trial_status_service import (
    parse_iso_datetime,
    resolve_effective_subscription_status,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed transition table
# ---------------------------------------------------------------------------
# Key: current_status -> set of allowed target statuses

ALLOWED_TRANSITIONS = {
    "trialing": {"active", "expired"},
    "active": {"past_due", "expired", "cancelled"},
    "past_due": {"active", "expired", "cancelled"},
    "expired": {"active"},
    "cancelled": {"active"},
}

_VALID_STATUSES = frozenset(ALLOWED_TRANSITIONS.keys()) | {"active",
    "past_due", "expired", "cancelled", "trialing"}

_SOURCE_STATE_PROTECTING_ACTIVATION_STATUSES = frozenset({
    "claimed",
    "activated",
    "credit_pending",
    "conflict",
})


def _same_source_snapshot(order: dict, subscription: dict) -> bool:
    return (
        order.get("subscription_id") == subscription.get("id")
        and order.get("source_plan_id") == subscription.get("plan_id")
        and (order.get("source_status") or "").strip().lower()
        == (subscription.get("status") or "").strip().lower()
        and str(order.get("source_period_start") or "")
        == str(subscription.get("current_period_start") or "")
        and str(order.get("source_period_end") or "")
        == str(subscription.get("current_period_end") or "")
    )


def _has_source_state_dependent_subscription_order(
    subscription: dict,
    *,
    now: datetime,
) -> bool:
    """Return True when changing status could invalidate an in-flight checkout.

    A live payable pending order must keep its captured source subscription
    state valid until the checkout is resolved. Paid/partially activated orders
    also protect the source state because reconciliation may still need the
    same snapshot to finish safely.
    """
    company_id = subscription.get("company_id")
    if not company_id:
        return False

    try:
        from app.database.company_subscription_order_repository import (
            list_subscription_orders_for_company,
        )

        orders = list_subscription_orders_for_company(
            company_id=company_id,
            limit=100,
        )
    except Exception:
        logger.exception(
            "Could not inspect subscription orders before lifecycle transition "
            "for company %s; failing closed.",
            company_id,
        )
        return True

    for order in orders:
        if not _same_source_snapshot(order, subscription):
            continue

        status = (order.get("status") or "").strip().lower()
        activation_status = (order.get("activation_status") or "").strip().lower()

        if (
            status == "pending"
            and not order.get("paid_at")
            and not order.get("credited_at")
            and order.get("gateway_order_id")
            and order.get("checkout_url")
        ):
            expires_at = parse_iso_datetime(order.get("expires_at"))
            if expires_at is None or expires_at > now:
                return True

        if status == "paid" or order.get("reconciliation_required"):
            return True

        if activation_status in _SOURCE_STATE_PROTECTING_ACTIVATION_STATUSES:
            return True

    return False


def transition_subscription_status(
    company_id: int,
    target_status: str,
    expected_current_status: str | None = None,
    reason: str | None = None,
    effective_at: str | None = None,
) -> dict:
    """Transition a company subscription to a new status.

    Args:
        company_id: The company whose subscription to transition.
        target_status: The target status to transition to.
        expected_current_status: If provided, the subscription must have
            this status; raises ValueError on mismatch.
        reason: Optional human-readable reason for the transition (logged).
        effective_at: Optional ISO-8601 timestamp; when provided the
            transition is logged with this effective time (not yet used
            for scheduling \u2014 that is handled by schedule_* functions).

    Returns:
        The updated subscription record (dictionary).

    Raises:
        ValueError: If the transition is not allowed, the subscription
            does not exist, or the expected_current_status does not match.
    """
    target = target_status.strip().lower() if target_status else ""
    if not target:
        raise ValueError("target_status is required")
    if target not in _VALID_STATUSES:
        raise ValueError(f"Invalid target status: {target!r}")

    # Fetch the current subscription (active/trialing/past_due only)
    subscription = _get_current_sub(company_id)
    if not subscription:
        # The subscription may have an expired/cancelled status that
        # the current lookup does not return.  Try the latest lookup.
        subscription = _get_latest_sub(company_id)
        if not subscription:
            raise ValueError(
                f"No subscription found for company {company_id}"
            )

    current_status = (subscription.get("status") or "").strip().lower()

    if expected_current_status is not None:
        expected = expected_current_status.strip().lower()
        if current_status != expected:
            raise ValueError(
                f"Expected current status '{expected}' for company {company_id}, "
                f"but actual status is '{current_status}'"
            )

    # Idempotent: same status returns success without modification
    if current_status == target:
        logger.info(
            "Subscription for company %d already has status '%s'. "
            "Transition is idempotent.",
            company_id, target,
        )
        return subscription

    # Validate transition
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if target not in allowed:
        raise ValueError(
            f"Transition from '{current_status}' to '{target}' is not allowed "
            f"for company {company_id}. Allowed targets from '{current_status}': "
            f"{sorted(allowed)}"
        )

    # Build extra update fields
    extra = {}
    if target == "cancelled":
        extra["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    elif current_status == "cancelled" and target == "active":
        # Reactivating clears cancellation markers
        extra["cancelled_at"] = None
        extra["cancellation_scheduled_at"] = None
        extra["cancellation_effective_at"] = None

    if reason:
        extra["_transition_reason"] = reason  # logged but not stored

    subscription_id = subscription.get("id")

    try:
        updated = _update_status_conditional(
            subscription_id=subscription_id,
            company_id=company_id,
            expected_status=current_status,
            target_status=target,
            extra_updates=extra if extra else None,
        )
    except ValueError as exc:
        # Re-raise with clearer context
        logger.warning(
            "Status transition failed for company %d (%s -> %s): %s",
            company_id, current_status, target, exc,
        )
        raise

    logger.info(
        "Subscription for company %d transitioned from '%s' to '%s'%s",
        company_id, current_status, target,
        f" (reason: {reason})" if reason else "",
    )

    return updated


# ---------------------------------------------------------------------------
# Scheduling helpers (reserved for future phases \u2014 no action taken yet)
# ---------------------------------------------------------------------------


def _validate_scheduling_active(subscription):
    """Ensure the subscription is in an active paid status for scheduling.

    Raises ValueError if the subscription is not active/trialing/past_due.
    """
    status = (subscription.get("status") or "").strip().lower()
    if status not in ("active",):
        raise ValueError(
            f"Cannot schedule changes on subscription with status '{status}'. "
            "Only active subscriptions can schedule plan changes or cancellations."
        )


def schedule_plan_change(
    company_id: int,
    pending_plan_id: int,
    effective_at: str,
) -> dict:
    """Schedule a plan change (downgrade) for an active subscription.

    The change is NOT executed here \u2014 only the pending plan and effective
    date are stored on the subscription row.

    Args:
        company_id: The company whose subscription to update.
        pending_plan_id: The target plan ID.
        effective_at: ISO-8601 timestamp (must equal current_period_end).

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If validation fails.
    """
    if not pending_plan_id:
        raise ValueError("pending_plan_id is required")
    if not effective_at:
        raise ValueError("effective_at is required")

    subscription = _get_current_sub(company_id)
    if not subscription:
        raise ValueError(f"No active subscription for company {company_id}")

    _validate_scheduling_active(subscription)

    # effective_at must match current_period_end
    period_end = subscription.get("current_period_end")
    if period_end and effective_at != period_end:
        raise ValueError(
            f"effective_at ({effective_at}) must match "
            f"current_period_end ({period_end})"
        )

    subscription_id = subscription.get("id")

    updated = _update_sub(
        subscription_id=subscription_id,
        company_id=company_id,
        updates={
            "pending_plan_id": pending_plan_id,
            "plan_change_effective_at": effective_at,
        },
    )

    logger.info(
        "Plan change scheduled for company %d: new plan_id=%s effective at %s",
        company_id, pending_plan_id, effective_at,
    )

    return updated


def clear_scheduled_plan_change(company_id: int) -> dict:
    """Remove a pending plan change from an active subscription.

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If no active subscription is found.
    """
    subscription = _get_current_sub(company_id)
    if not subscription:
        raise ValueError(f"No active subscription for company {company_id}")

    subscription_id = subscription.get("id")

    updated = _update_sub(
        subscription_id=subscription_id,
        company_id=company_id,
        updates={
            "pending_plan_id": None,
            "plan_change_effective_at": None,
        },
    )

    logger.info(
        "Scheduled plan change cleared for company %d", company_id,
    )

    return updated


def schedule_cancellation(
    company_id: int,
    effective_at: str,
) -> dict:
    """Schedule a cancellation for an active subscription.

    The cancellation is NOT executed here \u2014 only the scheduling fields
    are stored on the subscription row.

    Args:
        company_id: The company whose subscription to cancel.
        effective_at: ISO-8601 timestamp (must equal current_period_end).

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If validation fails.
    """
    if not effective_at:
        raise ValueError("effective_at is required")

    subscription = _get_current_sub(company_id)
    if not subscription:
        raise ValueError(f"No active subscription for company {company_id}")

    _validate_scheduling_active(subscription)

    period_end = subscription.get("current_period_end")
    if period_end and effective_at != period_end:
        raise ValueError(
            f"effective_at ({effective_at}) must match "
            f"current_period_end ({period_end})"
        )

    subscription_id = subscription.get("id")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Cancelling clears any pending downgrade
    updated = _update_sub(
        subscription_id=subscription_id,
        company_id=company_id,
        updates={
            "cancellation_scheduled_at": now_iso,
            "cancellation_effective_at": effective_at,
            "pending_plan_id": None,
            "plan_change_effective_at": None,
        },
    )
    return updated


def clear_scheduled_cancellation(company_id: int) -> dict:
    """Remove a pending cancellation from an active subscription.

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If no active subscription is found.
    """
    subscription = _get_current_sub(company_id)
    if not subscription:
        raise ValueError(f"No active subscription for company {company_id}")

    subscription_id = subscription.get("id")

    updated = _update_sub(
        subscription_id=subscription_id,
        company_id=company_id,
        updates={
            "cancellation_scheduled_at": None,
            "cancellation_effective_at": None,
        },
    )

    logger.info(
        "Scheduled cancellation cleared for company %d", company_id,
    )

    return updated




def undo_subscription_cancellation(company_id: int) -> dict:
    """Undo a pending cancellation before it takes effect.

    Args:
        company_id: The company whose pending cancellation to undo.

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If no active subscription is found or subscription
            cannot be modified because cancellation has already taken effect.
    """
    subscription = _get_current_sub(company_id)
    if not subscription:
        raise ValueError(f"No active subscription for company {company_id}")

    subscription_id = subscription.get("id")

    # Check if cancellation has already taken effect
    status = (subscription.get("status") or "").strip().lower()
    if status in ("expired", "cancelled"):
        raise ValueError(
            f"Cannot undo cancellation for company {company_id}: "
            f"subscription is already '{status}'."
        )

    return clear_scheduled_cancellation(company_id)


def schedule_subscription_downgrade(
    company_id: int,
    target_plan_id: int,
    now: datetime | None = None,
) -> dict:
    """Schedule a downgrade for an active subscription.

    Validates that:
    - The subscription is active paid.
    - No cancellation is pending.
    - The target is a valid lower plan.
    - Current usage fits within target plan limits.

    Args:
        company_id: The company whose subscription to downgrade.
        target_plan_id: The target plan ID (must be lower than current).
        now: Optional UTC datetime for comparison.

    Returns:
        The updated subscription record.

    Raises:
        ValueError: If validation fails.
    """
    if not target_plan_id:
        raise ValueError("target_plan_id is required")

    subscription = _get_current_sub(company_id)
    if not subscription:
        raise ValueError(f"No active subscription for company {company_id}")

    _validate_scheduling_active(subscription)

    # Check conflict: cancellation pending blocks downgrade
    if subscription.get("cancellation_effective_at"):
        raise ValueError(
            f"Cannot schedule downgrade for company {company_id}: "
            "a cancellation is already scheduled. Undo cancellation first."
        )

    effective_at = subscription.get("current_period_end")
    if not effective_at:
        raise ValueError(
            f"Cannot schedule downgrade for company {company_id}: "
            "current_period_end is not set."
        )

    return schedule_plan_change(
        company_id=company_id,
        pending_plan_id=target_plan_id,
        effective_at=effective_at,
    )


def clear_scheduled_downgrade(company_id: int) -> dict:
    """Remove a pending downgrade from an active subscription.

    Args:
        company_id: The company whose pending downgrade to clear.

    Returns:
        The updated subscription record.
    """
    return clear_scheduled_plan_change(company_id)





# ---------------------------------------------------------------------------
# Expiry processing
# ---------------------------------------------------------------------------


def process_subscription_expiry(
    company_id: int,
    now: datetime | None = None,
) -> dict:
    """Process a single subscription expiry with grace period support.

    Determines the correct transition based on current status:
      - trialing + trial_ends_at <= now  -> trialing -> expired
      - active + current_period_end <= now -> active -> past_due (grace period)
      - past_due + current_period_end + grace <= now -> past_due -> expired
      - already expired/cancelled -> idempotent (no change)

    The grace period is configurable via BILLING_GRACE_PERIOD_DAYS env var
    (default 3 days). During grace, the subscription is in past_due state
    and the company retains limited access.

    Args:
        company_id: The company whose subscription to process.
        now: UTC datetime for expiry comparison. Defaults to current UTC time.

    Returns:
        Processing result dict with keys:
        - processed (bool)
        - company_id (int)
        - from_status (str or None)
        - to_status (str or None)
        - reason (str or None)
        - idempotent (bool)
        - grace_period_used (bool): Whether the grace period was applied.

    Raises:
        ValueError: If the subscription is missing or transition fails.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    now_iso = now.isoformat()

    # Fetch latest subscription to see any status
    subscription = _get_latest_sub(company_id)
    if not subscription:
        raise ValueError(f"No subscription found for company {company_id}")

    current_status = (subscription.get("status") or "").strip().lower()
    sub_id = subscription.get("id")
    plan = None
    try:
        plan = get_plan_by_id(subscription.get("plan_id"))
    except Exception:
        logger.exception(
            "Could not load subscription plan before expiry processing for company %d",
            company_id,
        )
    effective = resolve_effective_subscription_status(
        subscription,
        plan,
        now=now,
    )

    # Already expired or cancelled -> idempotent
    if current_status in ("expired", "cancelled"):
        logger.info(
            "Subscription for company %d already has status '%s'; expiry processing is idempotent.",
            company_id, current_status,
        )
        return {
            "processed": False,
            "company_id": company_id,
            "from_status": current_status,
            "to_status": current_status,
            "reason": f"Already {current_status}",
            "idempotent": True,
            "grace_period_used": False,
        }

    # Determine whether expiry condition is met
    reason = None
    target_status = "expired"
    grace_period_used = False

    if (
        effective["is_free_trial"]
        and effective["trial_expired"]
        and not effective["trial_missing"]
        and current_status in ("trialing", "active")
    ):
        if _has_source_state_dependent_subscription_order(subscription, now=now):
            logger.info(
                "Deferring physical Free trial expiry for company %d because "
                "an unresolved source-state subscription order exists.",
                company_id,
            )
            return {
                "processed": False,
                "company_id": company_id,
                "from_status": current_status,
                "to_status": current_status,
                "reason": "Free trial expired; source-state checkout pending",
                "idempotent": True,
                "grace_period_used": False,
                "protected_by_pending_checkout": True,
            }
        reason = "Trial period ended"
        target_status = "expired"

    elif current_status == "trialing":
        trial_end = subscription.get("trial_ends_at")
        if trial_end and trial_end <= now_iso:
            reason = "Trial period ended"
        else:
            reason = None

    elif current_status == "active":
        period_end = subscription.get("current_period_end")
        if period_end and period_end <= now_iso:
            # Transition to past_due first (grace period)
            target_status = "past_due"
            reason = "Billing period ended; grace period started"
            grace_period_used = True
        else:
            reason = None

    elif current_status == "past_due":
        period_end = subscription.get("current_period_end")
        if period_end and period_end <= now_iso:
            # Check if grace period has also passed
            grace_days = get_grace_period_days()
            try:
                end_dt = datetime.fromisoformat(period_end)
                grace_end = end_dt + timedelta(days=grace_days)
                if now >= grace_end:
                    reason = "Grace period ended"
                else:
                    # Still within grace period
                    reason = None
            except (ValueError, TypeError):
                reason = "Billing period ended"
        else:
            reason = None

    if not reason:
        # Not due for expiry yet
        return {
            "processed": False,
            "company_id": company_id,
            "from_status": current_status,
            "to_status": current_status,
            "reason": "Not due for expiry",
            "idempotent": True,
            "grace_period_used": False,
        }

    # Perform the transition via conditional update
    try:
        result = _update_status_conditional(
            subscription_id=sub_id,
            company_id=company_id,
            expected_status=current_status,
            target_status=target_status,
        )
    except ValueError as exc:
        # Status may have changed between check and update (race)
        logger.warning(
            "Expiry transition race for company %d (expected %s): %s",
            company_id, current_status, exc,
        )
        raise

    logger.info(
        "Subscription lifecycle: company=%d transition=%s->%s reason=%s grace=%s",
        company_id, current_status, target_status, reason, grace_period_used,
    )
    logger.info(
        "Subscription for company %d transitioned: %s -> %s (%s)%s",
        company_id, current_status, target_status, reason,
        " [grace period]" if grace_period_used else "",
    )

    # --- Generate notifications on state transitions ---
    try:
        from app.services.billing_notification_service import (
            notify_grace_period_started,
            notify_subscription_expired,
        )
        period_end = subscription.get("current_period_end", "")
        if target_status == "past_due" and grace_period_used and period_end:
            # Grace period started — compute grace period end
            grace_days = int(os.environ.get("BILLING_GRACE_PERIOD_DAYS", "3"))
            try:
                end_dt = datetime.fromisoformat(period_end)
                grace_end = end_dt + timedelta(days=grace_days)
                notify_grace_period_started(
                    company_id=company_id,
                    subscription_id=sub_id,
                    period_end=period_end,
                    grace_period_end=grace_end.isoformat(),
                )
            except (ValueError, TypeError):
                logger.warning("Could not parse period_end for grace notification: %s", period_end)
        if target_status == "expired" and reason and "grace" in reason.lower() or (
            current_status == "past_due" and target_status == "expired"
        ):
            notify_subscription_expired(
                company_id=company_id,
                subscription_id=sub_id,
                period_end=subscription.get("current_period_end", ""),
            )
    except Exception as notify_err:
        logger.warning(
            "Failed to generate expiry notification for company %d: %s",
            company_id, notify_err,
        )

    return {
        "processed": True,
        "company_id": company_id,
        "from_status": current_status,
        "to_status": target_status,
        "reason": reason,
        "idempotent": False,
        "grace_period_used": grace_period_used,
    }

def process_due_subscriptions(
    now: datetime | None = None,
    batch_size: int = 100,
) -> dict:
    """Process all subscriptions whose current_period_end or trial_ends_at has passed.

    This function is the batch entry point for cron/scheduler usage.
    Processing order per subscription:
    1. Scheduled cancellation due
    2. Scheduled downgrade due
    3. Normal active/past_due period expiry
    4. Trial expiry

    Args:
        now: UTC datetime for expiry comparison. Defaults to current UTC time.
        batch_size: Maximum number of due subscriptions to process per call.

    Returns:
        Processing summary dict:
        - total_processed (int)
        - errors (list of dict)
        - outcomes (list of dict with company_id, result)
        - batch_size (int)
        - due_count (int)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    now_iso = now.isoformat()

    from app.database.company_subscription_repository import (
        get_due_subscriptions as _get_due,
    )

    due_subscriptions = _get_due(now_iso=now_iso, batch_size=batch_size)

    logger.info(
        "Found %d due subscription(s) for lifecycle processing",
        len(due_subscriptions),
    )

    total_processed = 0
    errors: list[dict] = []
    outcomes: list[dict] = []

    for sub in due_subscriptions:
        company_id = sub.get("company_id")
        current_status = sub.get("status", "")
        sub_id = sub.get("id")

        try:
            result = _process_single_subscription(sub, now=now)
            outcomes.append(result)
            if result.get("processed"):
                total_processed += 1
                status_to = result.get("to_status", result.get("result", "unknown"))
                reason = result.get("reason", "")
                logger.info(
                    "Processed subscription %d (company %d): %s -> %s (%s)",
                    sub_id, company_id, current_status, status_to, reason,
                )
        except Exception as exc:
            logger.exception(
                "Failed to process lifecycle for company %d (subscription %d): %s",
                company_id, sub_id, exc,
            )
            errors.append({
                "company_id": company_id,
                "subscription_id": sub_id,
                "status": current_status,
                "error": str(exc),
            })
            outcomes.append({
                "company_id": company_id,
                "subscription_id": sub_id,
                "result": "failed",
                "error": str(exc),
            })

    summary = {
        "total_processed": total_processed,
        "errors": errors,
        "outcomes": outcomes,
        "batch_size": batch_size,
        "due_count": len(due_subscriptions),
    }

    if errors:
        logger.warning(
            "Lifecycle processing completed with %d error(s): %s",
            len(errors), summary,
        )
    else:
        logger.info(
            "Lifecycle processing completed: %d processed, 0 errors",
            total_processed,
        )

    return summary


# ---------------------------------------------------------------------------
# Single-subscription lifecycle processing
# ---------------------------------------------------------------------------


def _process_single_subscription(sub: dict, now: datetime | None = None) -> dict:
    """Process a single due subscription through the lifecycle state machine.

    Evaluation order:
    1. Scheduled cancellation due
    2. Scheduled downgrade due
    3. Normal active/past_due period expiry
    4. Trial expiry

    Each subscription is processed at most once per call.

    Args:
        sub: The subscription record to process.
        now: UTC datetime for comparison. Defaults to current UTC time.

    Returns:
        Dict with company_id, result, and optionally from_status/to_status.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    now_iso = now.isoformat()
    company_id = sub.get("company_id")
    sub_id = sub.get("id")
    current_status = (sub.get("status") or "").strip().lower()
    plan = None
    try:
        plan = get_plan_by_id(sub.get("plan_id"))
    except Exception:
        logger.exception(
            "Could not load subscription plan for lifecycle candidate %s",
            sub_id,
        )

    # Already expired or cancelled
    if current_status in ("expired", "cancelled"):
        return {
            "company_id": company_id,
            "subscription_id": sub_id,
            "processed": False,
            "result": "unchanged",
            "reason": f"Already {current_status}",
        }

    # --- 1. Scheduled cancellation ---
    cancellation_effective = sub.get("cancellation_effective_at")
    if current_status == "active" and cancellation_effective and cancellation_effective <= now_iso:
        try:
            transition_subscription_status(
                company_id=company_id,
                target_status="cancelled",
                reason="Scheduled cancellation effective",
            )
            _clear_all_scheduling(sub_id, company_id)
            return {
                "company_id": company_id,
                "subscription_id": sub_id,
                "processed": True,
                "result": "cancellation_applied",
                "from_status": "active",
                "to_status": "cancelled",
                "reason": "Scheduled cancellation effective",
            }
        except ValueError as exc:
            logger.warning(
                "Cancellation execution failed for company %d: %s",
                company_id, exc,
            )
            return {
                "company_id": company_id,
                "subscription_id": sub_id,
                "processed": False,
                "result": "failed",
                "error": str(exc),
            }

    # --- 2. Scheduled downgrade ---
    pending_plan_id = sub.get("pending_plan_id")
    plan_change_effective = sub.get("plan_change_effective_at")
    if current_status == "active" and pending_plan_id and plan_change_effective and plan_change_effective <= now_iso:
        try:
            _apply_scheduled_downgrade(company_id, pending_plan_id, sub, now=now)
            return {
                "company_id": company_id,
                "subscription_id": sub_id,
                "processed": True,
                "result": "downgrade_applied",
                "reason": "Scheduled downgrade effective",
            }
        except ValueError as exc:
            logger.warning(
                "Downgrade execution blocked for company %d: %s",
                company_id, exc,
            )
            # Don't return - fall through to expiry check if period has ended
            downgrade_blocked_info = {
                "company_id": company_id,
                "subscription_id": sub_id,
                "result": "downgrade_blocked",
                "error": str(exc),
            }
            logger.warning("Downgrade blocked info: %s", downgrade_blocked_info)
    effective = resolve_effective_subscription_status(sub, plan, now=now)
    if (
        effective["is_free_trial"]
        and effective["trial_expired"]
        and not effective["trial_missing"]
        and current_status in ("trialing", "active")
    ):
        return process_subscription_expiry(company_id, now=now)

    # --- 3. Normal active/past_due period expiry ---
    if current_status in ("active", "past_due"):
        period_end = sub.get("current_period_end")
        if period_end and period_end <= now_iso:
            return process_subscription_expiry(company_id, now=now)

    # --- 4. Trial expiry ---
    if current_status == "trialing":
        trial_end = sub.get("trial_ends_at")
        if trial_end and trial_end <= now_iso:
            return process_subscription_expiry(company_id, now=now)

    return {
        "company_id": company_id,
        "subscription_id": sub_id,
        "processed": False,
        "result": "unchanged",
        "reason": "Not due for processing",
    }


def _apply_scheduled_downgrade(
    company_id: int,
    target_plan_id: int,
    sub: dict,
    now: datetime | None = None,
) -> dict:
    """Execute a scheduled downgrade after rechecking usage.

    Policy: downgrade takes effect at period end. The subscription
    becomes expired after applying the target plan. The customer
    must complete a manual renewal checkout for the lower plan
    before paid access resumes.

    No included AI credit is granted during downgrade without payment.

    Args:
        company_id: The company to downgrade.
        target_plan_id: The target plan ID.
        sub: The current subscription record.
        now: UTC datetime.

    Returns:
        Dict with processing result.

    Raises:
        ValueError: If usage exceeds target plan limits.
    """
    from app.services.billing_service import get_company_usage
    from app.database.subscription_plan_repository import get_plan_by_id

    target_plan = get_plan_by_id(target_plan_id)
    if not target_plan:
        raise ValueError(f"Target plan {target_plan_id} not found")

    # Recheck usage
    usage = get_company_usage(company_id)
    u = usage.get("usage", {}) if usage else {}

    target_limits = {
        "chatbots": target_plan.get("chatbot_limit"),
        "team_members": target_plan.get("team_member_limit"),
        "knowledge_files": target_plan.get("knowledge_file_limit"),
        "knowledge_storage_bytes": target_plan.get("knowledge_storage_limit_bytes"),
        "channels": target_plan.get("channel_limit"),
    }

    blocking_items = []

    def _check(label, used_key, limit_key, inner_key=None):
        u_data = u.get(used_key) or {}
        used = u_data.get(inner_key or "used", 0) or 0
        limit = target_limits.get(limit_key)
        if limit is not None and used > limit:
            blocking_items.append(f"{label}={used} > limit={limit}")

    _check("chatbots", "chatbots", "chatbots")
    _check("team_members", "team_members", "team_members")
    _check("knowledge_files", "knowledge_files", "knowledge_files")
    _check("knowledge_storage_bytes", "knowledge_storage_bytes", "knowledge_storage_bytes")
    _check("channels", "channels", "channels")

    if blocking_items:
        raise ValueError(
            f"Downgrade blocked for company {company_id}: "
            f"{'; '.join(blocking_items)}. "
            "Reduce usage before downgrading."
        )

    # Apply the downgrade: transition to expired, then set plan_id to target
    subscription_id = sub.get("id")

    transition_subscription_status(
        company_id=company_id,
        target_status="expired",
        expected_current_status="active",
        reason="Scheduled downgrade effective",
    )

    # Update plan_id to the target (lower) plan
    _update_sub(
        subscription_id=subscription_id,
        company_id=company_id,
        updates={
            "plan_id": target_plan_id,
            "pending_plan_id": None,
            "plan_change_effective_at": None,
        },
    )

    return {
        "company_id": company_id,
        "subscription_id": subscription_id,
        "processed": True,
        "result": "downgrade_applied",
        "from_plan_id": sub.get("plan_id"),
        "to_plan_id": target_plan_id,
    }


def _clear_all_scheduling(subscription_id: int, company_id: int) -> dict:
    """Clear all scheduling fields on a subscription.

    Used after cancellation is executed or renewal/upgrade occurs.

    Args:
        subscription_id: The subscription to update.
        company_id: The company owning the subscription.

    Returns:
        The updated subscription record.
    """
    return _update_sub(
        subscription_id=subscription_id,
        company_id=company_id,
        updates={
            "pending_plan_id": None,
            "plan_change_effective_at": None,
            "cancellation_scheduled_at": None,
            "cancellation_effective_at": None,
        },
    )

# ===== Phase 4I: Renewal status & grace period =====

GRACE_PERIOD_DAYS_DEFAULT = 3


def get_grace_period_days() -> int:
    """Return the configured grace period in days."""
    try:
        val = int(os.environ.get("BILLING_GRACE_PERIOD_DAYS", str(GRACE_PERIOD_DAYS_DEFAULT)))
        return max(val, 1)
    except (ValueError, TypeError):
        return GRACE_PERIOD_DAYS_DEFAULT


def get_subscription_renewal_status(company_id: int) -> dict:
    """Return safe renewal status for a company subscription."""
    subscription = _get_latest_sub(company_id)
    if not subscription:
        raise ValueError(f"No subscription found for company {company_id}")
    status = (subscription.get("status") or "").strip().lower()
    now = datetime.now(timezone.utc)
    period_end_str = subscription.get("current_period_end")
    period_end = None
    if period_end_str:
        try:
            period_end = datetime.fromisoformat(period_end_str)
        except (ValueError, TypeError):
            pass
    period_start_str = subscription.get("current_period_start")
    pending_plan_id = subscription.get("pending_plan_id")
    cancellation_effective_at = subscription.get("cancellation_effective_at")
    days_until_expiry = None
    expiry_date = None
    if period_end:
        days_until_expiry = max(0, (period_end - now).days)
        expiry_date = period_end_str
    grace_days = get_grace_period_days()
    grace_period_active = False
    grace_period_end = None
    if status == "past_due" and period_end:
        grace_end = period_end + timedelta(days=grace_days)
        if now <= grace_end:
            grace_period_active = True
            grace_period_end = grace_end.isoformat()
    renewal_allowed = status in ("expired", "past_due", "cancelled")
    renewal_required = status in ("expired", "past_due")
    pending_renewal_order = None
    if renewal_allowed or renewal_required:
        from app.database.company_subscription_order_repository import list_subscription_orders_for_company
        pending_orders = list_subscription_orders_for_company(company_id=company_id, limit=5, status="pending")
        for po in pending_orders:
            if po.get("activation_type") == "renewal":
                pending_renewal_order = {
                    "order_reference": po.get("order_reference"),
                    "created_at": po.get("created_at"),
                    "expires_at": po.get("expires_at"),
                }
                break
    next_plan = None
    if pending_plan_id:
        from app.database.subscription_plan_repository import get_plan_by_id
        plan = get_plan_by_id(pending_plan_id)
        if plan:
            next_plan = {
                "id": plan.get("id"),
                "code": plan.get("code"),
                "name": plan.get("name"),
            }
    logger.info(
        "Renewal status for company %d: status=%s, days_until_expiry=%s, grace=%s, pending_order=%s",
        company_id, status, days_until_expiry, grace_period_active,
        "yes" if pending_renewal_order else "no",
    )
    message = _build_renewal_message(status, days_until_expiry, grace_period_active, grace_period_end, pending_renewal_order, cancellation_effective_at)
    return {
        "subscription_status": status,
        "period_start": period_start_str,
        "period_end": expiry_date,
        "days_until_expiry": days_until_expiry,
        "renewal_allowed": renewal_allowed,
        "renewal_required": renewal_required,
        "grace_period_active": grace_period_active,
        "grace_period_end": grace_period_end,
        "pending_renewal_order": pending_renewal_order,
        "scheduled_next_plan": next_plan,
        "message": message,
    }


def _build_renewal_message(status, days_until_expiry, grace_period_active, grace_period_end, pending_renewal_order, cancellation_effective_at):
    """Build a safe customer-facing renewal message."""
    if pending_renewal_order:
        return "Renewal payment is pending. Once confirmed, your subscription will be reactivated."
    if status == "active" and days_until_expiry is not None and days_until_expiry <= 0:
        return "Your subscription period has ended. Please renew to continue."
    if status == "active" and days_until_expiry is not None and days_until_expiry <= 7:
        return "Your subscription expires in {} day(s). Renew now to avoid interruption.".format(days_until_expiry)
    if status == "past_due" and grace_period_active:
        return "Your subscription is past due. Grace period ends {}. Renew to restore full access.".format(grace_period_end)
    if status == "expired":
        return "Your subscription has expired. Renew to restore access."
    if status == "cancelled":
        return "Your subscription has been cancelled. Renew to reactivate."
    return ""
