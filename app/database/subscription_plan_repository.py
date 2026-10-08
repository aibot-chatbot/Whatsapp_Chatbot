from datetime import datetime, timezone

from app.database.db import supabase
from app.services.turn_cache import cached


TABLE_NAME = "subscription_plans"
PRO_CHANNEL_LIMIT = 4


def _apply_current_product_contract(plan):
    """Keep the runtime contract correct while older plan rows are migrated.

    Migration 074 updates persisted Pro rows to four channels.  Some deployed
    environments can still return the previous value until that migration is
    applied, so every server-side plan consumer receives the current contract
    immediately.  Values above the contract and unlimited plans are preserved.
    """
    if not isinstance(plan, dict):
        return plan
    result = dict(plan)
    code = str(result.get("code") or "").strip().casefold()
    channel_limit = result.get("channel_limit")
    if code == "pro" and isinstance(channel_limit, int) and not isinstance(channel_limit, bool):
        result["channel_limit"] = max(channel_limit, PRO_CHANNEL_LIMIT)
    if code == "pro" and isinstance(result.get("description"), str):
        result["description"] = result["description"].replace("2 channels", "4 channels")
    return result


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
    return [_apply_current_product_contract(plan) for plan in (response.data or [])]


def get_plan_by_id(plan_id):
    """Fetch a single subscription plan by its id."""
    if not plan_id:
        return None

    # Resolved three times per reply, through resolve_ai_access. The catalogue
    # is read-only to this role, so it cannot change inside a turn.
    return cached(("plan", plan_id), lambda: _select_plan(plan_id))


def _select_plan(plan_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("id", plan_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return _apply_current_product_contract(rows[0]) if rows else None


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
    return _apply_current_product_contract(rows[0]) if rows else None
