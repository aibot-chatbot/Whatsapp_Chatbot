"""billing_guard.py — Central enforcement engine for subscription limits.

This module provides the building blocks for checking whether a company
has exceeded its subscription plan limits. It is deliberately kept
separate from existing billing logic so that enforcement can be added
incrementally without modifying the usage-tracking or subscription-
management code.
"""

import logging

from app.services.billing_service import (
    get_company_usage,
    get_current_subscription,
    ensure_default_company_subscription,
)
from app.services.free_trial_status_service import (
    resolve_effective_subscription_status,
)
from app.database.invite_repository import count_valid_pending_invitations

logger = logging.getLogger(__name__)


def _strict_pending_invitation_count(company_id, reported_pending):
    """Replace nonzero aggregate usage with an expiry-validated reservation count."""
    if not reported_pending:
        return 0
    try:
        return count_valid_pending_invitations(company_id)
    except Exception as exc:
        logger.exception("Unable to validate pending invitation reservations")
        raise BillingLimitError(
            "Unable to verify usage limits. Please try again.",
            code="usage_unavailable",
        ) from exc


class BillingLimitError(Exception):
    """Raised when a company has exceeded a subscription plan limit.

    Attributes:
        message — human-readable explanation
        code     — optional short string for future UI handling
                   (e.g. "chatbot_limit", "knowledge_storage_limit")
        details  — optional dict with additional structured information
                   (e.g. current usage, limit, incoming size for storage)
    """

    def __init__(self, message: str, code: str | None = None, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _get_limits(subscription: dict | None) -> dict:
    """Extract subscription plan limits as a plain dictionary.

    Every value preserves None to mean "unlimited".
    The subscription may be None or may not carry a nested plan —
    both cases are handled safely.
    """
    plan = (subscription or {}).get("plan") or None

    if plan is None:
        return {
            "chatbots": None,
            "team_members": None,
            "knowledge_files": None,
            "storage_bytes": None,
            "channels": None,
        }

    return {
        "chatbots": plan.get("chatbot_limit"),
        "team_members": plan.get("team_member_limit"),
        "knowledge_files": plan.get("knowledge_file_limit"),
        "storage_bytes": plan.get("knowledge_storage_limit_bytes"),
        "channels": plan.get("channel_limit"),
    }


def _resolve_company_subscription(company_id: int) -> dict | None:
    """Resolve a valid subscription for a company, creating the Free plan if needed.

    Attempts to resolve the current subscription.  If no subscription exists,
    attempts to create the default Free subscription.  If that also fails,
    returns None — the caller should deny the action.

    This is the single place where the missing-subscription fallback is
    handled, so that all guards behave consistently.

    Unexpected exceptions from get_current_subscription are caught and
    converted to a logged None return so that repository or network
    failures do not escape the guard layer.

    Returns:
        A subscription dict (with nested plan) when a subscription is
        available, or None when no subscription can be resolved.
    """
    try:
        subscription = get_current_subscription(company_id)
    except BillingLimitError:
        # Already a controlled error — re-raise
        raise
    except Exception:
        logger.exception(
            "Failed to resolve current subscription for company %s; denying access.",
            company_id,
        )
        return None

    if subscription is not None:
        effective = resolve_effective_subscription_status(
            subscription,
            subscription.get("plan"),
        )
        if effective["is_free_trial"] and effective["trial_expired"]:
            logger.info(
                "Company %s: Free trial entitlement is expired or invalid; "
                "denying guard check.",
                company_id,
            )
            return None

        # Scheduler-safe guard: if the subscription is active but
        # current_period_end has passed, treat it as expired for
        # limit-enforcement purposes.  This protects the billing
        # guard from allowing new usage when the scheduled expiry
        # processor has not yet run.
        sub_status = (subscription.get("status") or "").lower().strip()
        if sub_status == "active":
            period_end_raw = subscription.get("current_period_end")
            if period_end_raw:
                from datetime import datetime, timezone
                try:
                    period_end = datetime.fromisoformat(str(period_end_raw))
                    if period_end.tzinfo is None:
                        period_end = period_end.replace(tzinfo=timezone.utc)
                    if period_end <= datetime.now(timezone.utc):
                        logger.info(
                            "Company %s: active subscription period ended at %s; "
                            "denying guard check (scheduler-safe guard).",
                            company_id, period_end_raw,
                        )
                        return None
                except (ValueError, TypeError):
                    logger.warning(
                        "Company %s: could not parse current_period_end=%r; "
                        "failing closed for safety.",
                        company_id, period_end_raw,
                    )
                    return None
        return subscription

    # No subscription — try to assign the Free plan
    try:
        subscription = ensure_default_company_subscription(company_id)
    except Exception:
        logger.exception(
            "Failed to create default Free subscription for company %s; denying access.",
            company_id,
        )
        return None

    if subscription is None:
        logger.warning(
            "ensure_default_company_subscription returned None for company %s; denying access.",
            company_id,
        )
        return None

    # Confirm we actually have a plan after recovery
    plan = subscription.get("plan")
    if not plan:
        logger.warning(
            "Company %s has a subscription row but no plan; denying access.",
            company_id,
        )
        return None

    return subscription
def check_company_limit(company_id: int) -> dict | None:
    """Return current usage, plan limits, and plan info for testing.

    This function is intended for development / debugging only.
    It calls the existing billing-service functions and merges
    them into a single dictionary.

    Returns:
        dict with keys: usage, limits, plan
        None when the company has no current subscription.
    """
    usage = get_company_usage(company_id)
    subscription = get_current_subscription(company_id)

    if usage is None or subscription is None:
        return None

    limits = _get_limits(subscription)

    return {
        "usage": usage,
        "limits": limits,
        "plan": subscription.get("plan"),
    }


# ---------------------------------------------------------------------------
# Enforcement helpers
# ---------------------------------------------------------------------------


def _check_limit(used: int | None, limit: int | None, msg: str, code: str) -> bool:
    """Shared enforcement check.

    Returns True when the action is allowed.
    Raises BillingLimitError when the limit has been reached or exceeded.

    Parameters
    ----------
    used  : current usage count (None is treated as 0)
    limit : plan limit (None means unlimited)
    msg   : human-readable message for the exception
    code  : machine-readable code for the exception
    """
    if limit is None:
        return True

    actual_used = used if used is not None else 0

    if actual_used >= limit:
        raise BillingLimitError(msg, code=code)

    return True


def can_create_chatbot(company_id: int) -> bool:
    """Check whether the company can create a new chatbot.

    Returns True when allowed.
    Raises BillingLimitError when no subscription exists or the
    chatbot limit has been reached.
    """
    subscription = _resolve_company_subscription(company_id)
    if subscription is None:
        raise BillingLimitError(
            "No active subscription plan. Please contact support.",
            code="no_subscription",
        )
    plan = subscription.get("plan") or {}
    limit = plan.get("chatbot_limit")
    if limit is None:
        return True
    usage = get_company_usage(company_id)
    if usage is None:
        raise BillingLimitError(
            "Unable to verify usage limits. Please try again.",
            code="usage_unavailable",
        )
    used = usage.get("usage", {}).get("chatbots", {}).get("used", 0) or 0
    return _check_limit(used, limit, "Chatbot limit reached", "chatbot_limit")


def can_upload_knowledge_file(company_id: int) -> bool:
    """Check whether the company can upload a new knowledge file.

    Returns True when allowed.
    Raises BillingLimitError when no subscription exists or the
    knowledge-file limit has been reached.
    """
    subscription = _resolve_company_subscription(company_id)
    if subscription is None:
        raise BillingLimitError(
            "No active subscription plan. Please contact support.",
            code="no_subscription",
        )
    plan = subscription.get("plan") or {}
    limit = plan.get("knowledge_file_limit")
    if limit is None:
        return True
    usage = get_company_usage(company_id)
    if usage is None:
        raise BillingLimitError(
            "Unable to verify usage limits. Please try again.",
            code="usage_unavailable",
        )
    used = usage.get("usage", {}).get("knowledge_files", {}).get("used", 0) or 0
    return _check_limit(used, limit, "Knowledge file limit reached", "file_limit")


def can_connect_channel(company_id: int) -> bool:
    """Check whether the company can connect a new channel.

    Returns True when allowed.
    Raises BillingLimitError when no subscription exists or the
    channel limit has been reached.
    """
    subscription = _resolve_company_subscription(company_id)
    if subscription is None:
        raise BillingLimitError(
            "No active subscription plan. Please contact support.",
            code="no_subscription",
        )
    plan = subscription.get("plan") or {}
    limit = plan.get("channel_limit")
    if limit is None:
        return True
    usage = get_company_usage(company_id)
    if usage is None:
        raise BillingLimitError(
            "Unable to verify usage limits. Please try again.",
            code="usage_unavailable",
        )
    used = usage.get("usage", {}).get("channels", {}).get("used", 0) or 0
    return _check_limit(used, limit, "Channel limit reached", "channel_limit")


def can_add_team_member(company_id: int) -> bool:
    """Check whether the company can add a new team member.

    Reads the team_member limit from the active subscription plan
    and compares it against the current count of active users.

    Returns True when allowed.
    Raises BillingLimitError when no subscription exists or the
    team-member limit has been reached.
    """
    subscription = _resolve_company_subscription(company_id)
    if subscription is None:
        raise BillingLimitError(
            "No active subscription plan. Please contact support.",
            code="no_subscription",
        )
    plan = subscription.get("plan") or {}
    limit = plan.get("team_member_limit")
    if limit is None:
        return True
    usage = get_company_usage(company_id)
    if usage is None:
        raise BillingLimitError(
            "Unable to verify usage limits. Please try again.",
            code="usage_unavailable",
        )
    used = usage.get("usage", {}).get("team_members", {}).get("used", 0) or 0
    reported_pending = usage.get("usage", {}).get("team_members", {}).get("pending_invitations", 0) or 0
    pending = _strict_pending_invitation_count(company_id, reported_pending)
    return _check_limit(used + pending, limit, "Team member limit reached for the current subscription plan.", "team_member_limit")


def can_accept_team_invitation(company_id: int) -> bool:
    """Allow a valid pending invitation to consume its already-reserved seat."""
    subscription = _resolve_company_subscription(company_id)
    if subscription is None:
        raise BillingLimitError(
            "No active subscription plan. Please contact support.",
            code="no_subscription",
        )
    plan = subscription.get("plan") or {}
    limit = plan.get("team_member_limit")
    if limit is None:
        return True
    usage = get_company_usage(company_id)
    if usage is None:
        raise BillingLimitError(
            "Unable to verify usage limits. Please try again.",
            code="usage_unavailable",
        )
    team_usage = usage.get("usage", {}).get("team_members", {})
    used = team_usage.get("used", 0) or 0
    reported_pending = team_usage.get("pending_invitations", 0) or 0
    pending = _strict_pending_invitation_count(company_id, reported_pending)
    if used + pending > limit:
        raise BillingLimitError(
            "Team member limit reached for the current subscription plan.",
            code="team_member_limit",
        )
    return True


# ---------------------------------------------------------------------------
# Plan feature flag guard
# ---------------------------------------------------------------------------

# Recognised feature keys for subscription plan feature_flags.
# Extend this set when adding new gated features.
# Model-access categories (Economy, Standard, Premium) are NOT boolean
# features and require separate design.
PLAN_FEATURES = frozenset({
    "batch_website_scraping",
    "single_website_scraping",
    "ai_generated_reports",
    "ai_assisted_menu_generation",
    "crm_lead_assignment",
})


def can_use_plan_feature(company_id, feature_key):
    """Check whether the company's current subscription plan allows a feature.

    Reads ``feature_flags`` from the active plan (a JSONB column on the
    ``subscription_plans`` table) and checks whether *feature_key* is
    explicitly enabled.

    Missing-subscription behavior:
        Attempts to resolve a subscription (creating the Free plan if
        absent).  If no subscription can be resolved, the feature is
        denied.

    Backward-compatibility rules (temporary - each plan must be configured
    explicitly before public launch):
        * Feature key missing from the plan ``feature_flags``   -> allowed
        * ``feature_flags`` column is NULL or empty dict        -> allowed
        * No active subscription exists                         -> denied
        * Feature explicitly set to ``true``                    -> allowed
        * Feature explicitly set to ``false``                   -> blocked
    """
    if not feature_key or not isinstance(feature_key, str):
        raise ValueError("feature_key must be a non-empty string")

    if feature_key not in PLAN_FEATURES:
        raise ValueError(
            "Unknown feature key: " + repr(feature_key) + ". "
            "Recognised keys: " + str(sorted(PLAN_FEATURES))
        )

    subscription = _resolve_company_subscription(company_id)
    if subscription is None:
        raise BillingLimitError(
            "No active subscription plan. Please contact support.",
            code="no_subscription",
        )

    plan = subscription.get("plan") or {}
    feature_flags = plan.get("feature_flags")

    # Backward compatibility: missing or null flags -> allow
    if feature_flags is None or not isinstance(feature_flags, dict):
        return True

    # Feature key not present in the flags map -> allow (temporary compat)
    if feature_key not in feature_flags:
        return True

    enabled = feature_flags.get(feature_key)

    if enabled is True:
        return True

    # Explicitly false (or any falsy non-None value) -> block
    raise BillingLimitError(
        "The feature \"" + feature_key + "\" is not available on your current subscription plan.",
        code="feature_not_available",
        details={"feature_key": feature_key},
    )


def can_upload_knowledge_storage(company_id: int, incoming_size_bytes: int) -> bool:
    """Check whether the company can upload a knowledge file of the given size.

    Projects the current storage usage plus the incoming file size against
    the plan's storage-byte limit.

    Args:
        company_id: The company to check.
        incoming_size_bytes: Size of the file being uploaded, in bytes.

    Returns True when allowed.
    Raises BillingLimitError when projected usage exceeds the plan limit
    or when no subscription can be resolved.
    Raises ValueError if incoming_size_bytes is negative.
    """
    if incoming_size_bytes < 0:
        raise ValueError(f"incoming_size_bytes must be non-negative, got {incoming_size_bytes}")

    subscription = _resolve_company_subscription(company_id)
    if subscription is None:
        raise BillingLimitError(
            "No active subscription plan. Please contact support.",
            code="no_subscription",
        )

    plan = subscription.get("plan") or {}
    limit = plan.get("knowledge_storage_limit_bytes")
    if limit is None:
        return True

    usage = get_company_usage(company_id)
    if usage is None:
        raise BillingLimitError(
            "Unable to verify usage limits. Please try again.",
            code="usage_unavailable",
        )

    current_usage = usage.get("usage", {}).get("knowledge_storage_bytes", {}).get("used", 0) or 0
    projected = current_usage + incoming_size_bytes
    if projected > limit:
        raise BillingLimitError(
            f"Knowledge storage limit reached: {projected} bytes projected exceeds {limit} bytes allowed",
            code="knowledge_storage_limit",
            details={
                "current_usage_bytes": current_usage,
                "incoming_size_bytes": incoming_size_bytes,
                "projected_usage_bytes": projected,
                "limit_bytes": limit,
            },
        )
    return True
