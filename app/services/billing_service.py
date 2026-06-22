import logging

from app.database.subscription_plan_repository import (
    get_active_plans as _get_active_plans,
    get_plan_by_id,
)
from app.database.company_subscription_repository import (
    get_company_subscription as _get_company_subscription,
)


def list_active_plans():
    """Return formatted list of active subscription plans."""
    plans = _get_active_plans()

    result = []
    for plan in plans:
        result.append({
            "id": plan.get("id"),
            "name": plan.get("name"),
            "code": plan.get("code"),
            "description": plan.get("description"),
            "price": str(plan.get("price", "0")),
            "currency": plan.get("currency"),
            "billing_interval": plan.get("billing_interval"),
            "chatbot_limit": plan.get("chatbot_limit"),
            "team_member_limit": plan.get("team_member_limit"),
            "monthly_ai_message_limit": plan.get("monthly_ai_message_limit"),
            "knowledge_file_limit": plan.get("knowledge_file_limit"),
            "knowledge_storage_limit_bytes": plan.get("knowledge_storage_limit_bytes"),
            "channel_limit": plan.get("channel_limit"),
        })

    return result


def get_current_subscription(company_id):
    """Return the current subscription for a company, including plan details.

    Returns None when the company has no active, trialing, or past-due subscription.
    The company_id must already be authenticated and scoped (e.g. from g.company_id).
    External payment fields are intentionally excluded from the response.
    Subscription information is never placed inside the JWT.
    """
    if not company_id:
        raise ValueError("Company ID is required")

    subscription = _get_company_subscription(company_id)

    if not subscription:
        return None

    plan = get_plan_by_id(subscription.get("plan_id"))

    result = {
        "id": subscription.get("id"),
        "company_id": subscription.get("company_id"),
        "plan_id": subscription.get("plan_id"),
        "status": subscription.get("status"),
        "starts_at": subscription.get("starts_at"),
        "current_period_start": subscription.get("current_period_start"),
        "current_period_end": subscription.get("current_period_end"),
        "trial_ends_at": subscription.get("trial_ends_at"),
        "cancelled_at": subscription.get("cancelled_at"),
        "ends_at": subscription.get("ends_at"),
        "payment_gateway": subscription.get("payment_gateway"),
        "created_at": subscription.get("created_at"),
        "updated_at": subscription.get("updated_at"),
    }

    if plan:
        result["plan"] = {
            "id": plan.get("id"),
            "name": plan.get("name"),
            "code": plan.get("code"),
            "description": plan.get("description"),
            "price": str(plan.get("price", "0")),
            "currency": plan.get("currency"),
            "billing_interval": plan.get("billing_interval"),
            "chatbot_limit": plan.get("chatbot_limit"),
            "team_member_limit": plan.get("team_member_limit"),
            "monthly_ai_message_limit": plan.get("monthly_ai_message_limit"),
            "knowledge_file_limit": plan.get("knowledge_file_limit"),
            "knowledge_storage_limit_bytes": plan.get("knowledge_storage_limit_bytes"),
            "channel_limit": plan.get("channel_limit"),
        }

    return result
