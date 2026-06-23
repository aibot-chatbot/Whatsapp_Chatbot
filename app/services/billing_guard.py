"""
billing_guard.py — Central enforcement engine for subscription limits.

This module provides the building blocks for checking whether a company
has exceeded its subscription plan limits. It is deliberately kept
separate from existing billing logic so that enforcement can be added
incrementally without modifying the usage-tracking or subscription-
management code.
"""

from app.services.billing_service import (
    get_company_usage,
    get_current_subscription,
)


class BillingLimitError(Exception):
    """Raised when a company has exceeded a subscription plan limit.

    Attributes:
        message — human-readable explanation
        code     — optional short string for future UI handling
                   (e.g. "chatbot_limit", "ai_message_limit")
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


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
            "ai_messages": None,
            "knowledge_files": None,
            "storage_bytes": None,
            "channels": None,
        }

    return {
        "chatbots": plan.get("chatbot_limit"),
        "team_members": plan.get("team_member_limit"),
        "ai_messages": plan.get("monthly_ai_message_limit"),
        "knowledge_files": plan.get("knowledge_file_limit"),
        "storage_bytes": plan.get("knowledge_storage_limit_bytes"),
        "channels": plan.get("channel_limit"),
    }


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
    Raises BillingLimitError when the chatbot limit has been reached.
    """
    data = check_company_limit(company_id)

    if data is None:
        return True

    used = data["usage"].get("usage", {}).get("chatbots", {}).get("used")
    limit = data["limits"].get("chatbots")

    return _check_limit(used, limit, "Chatbot limit reached", "chatbot_limit")


def can_send_ai_message(company_id: int) -> bool:
    """Check whether the company can send an AI message this billing period.

    Returns True when allowed.
    Raises BillingLimitError when the AI message limit has been reached.
    """
    data = check_company_limit(company_id)

    if data is None:
        return True

    used = data["usage"].get("usage", {}).get("ai_messages", {}).get("used")
    limit = data["limits"].get("ai_messages")

    return _check_limit(used, limit, "AI message limit reached", "ai_message_limit")


def can_upload_knowledge_file(company_id: int) -> bool:
    """Check whether the company can upload a new knowledge file.

    Returns True when allowed.
    Raises BillingLimitError when the knowledge-file limit has been reached.
    """
    data = check_company_limit(company_id)

    if data is None:
        return True

    used = data["usage"].get("usage", {}).get("knowledge_files", {}).get("used")
    limit = data["limits"].get("knowledge_files")

    return _check_limit(used, limit, "Knowledge file limit reached", "file_limit")


def can_connect_channel(company_id: int) -> bool:
    """Check whether the company can connect a new channel.

    Returns True when allowed.
    Raises BillingLimitError when the channel limit has been reached.
    """
    data = check_company_limit(company_id)

    if data is None:
        return True

    used = data["usage"].get("usage", {}).get("channels", {}).get("used")
    limit = data["limits"].get("channels")

    return _check_limit(used, limit, "Channel limit reached", "channel_limit")
