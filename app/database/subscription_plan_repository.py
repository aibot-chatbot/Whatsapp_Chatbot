from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "subscription_plans"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_active_plans():
    """Return all subscription plans that are currently active, ordered by price."""
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("is_active", True)
        .order("price")
        .execute()
    )
    return response.data or []


def get_plan_by_id(plan_id):
    """Fetch a single subscription plan by its id."""
    if not plan_id:
        return None

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("id", plan_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def get_plan_by_code(code):
    """Fetch a single subscription plan by its unique code."""
    if not code:
        return None

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("code", code)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None
