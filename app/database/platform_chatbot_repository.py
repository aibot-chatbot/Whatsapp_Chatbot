"""Explicit company-chatbot reads for authorized platform admins."""

from app.database.db import supabase


LIST_FIELDS = (
    "id,bot_name,is_active,status,language,tone,ai_provider,model_name,"
    "created_at,updated_at"
)
ALLOWED_STATES = {"current", "archived", "all"}
ALLOWED_SORT_FIELDS = {"created_at", "updated_at", "bot_name", "id"}
ALLOWED_SORT_ORDERS = {"asc", "desc"}
ARCHIVED_STATUS = "archived"


def _positive_company_id(company_id):
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        raise ValueError("company_id must be a positive integer")


def _validate_page(limit, offset):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")


def _escaped_ilike_pattern(search):
    escaped = (
        search.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace('"', '\\"')
        .replace(",", "\\,")
        .replace(".", "\\.")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    return f'"*{escaped}*"'


def list_company_chatbots_for_platform_admin(
    *,
    company_id,
    limit,
    offset,
    search=None,
    state="current",
    sort_by="created_at",
    sort_order="desc",
):
    _positive_company_id(company_id)
    _validate_page(limit, offset)
    if state not in ALLOWED_STATES:
        raise ValueError("Unsupported chatbot state")
    if sort_by not in ALLOWED_SORT_FIELDS or sort_order not in ALLOWED_SORT_ORDERS:
        raise ValueError("Unsupported chatbot ordering")

    query = (
        supabase.table("chatbots")
        .select(LIST_FIELDS, count="exact")
        .eq("company_id", company_id)
    )
    if search is not None:
        query = query.or_(f"bot_name.ilike.{_escaped_ilike_pattern(search)}")
    if state == "current":
        query = query.is_("deleted_at", "null").or_("status.is.null,status.neq.archived")
    elif state == "archived":
        query = query.eq("status", ARCHIVED_STATUS)

    descending = sort_order == "desc"
    query = query.order(sort_by, desc=descending)
    if sort_by != "id":
        query = query.order("id", desc=descending)
    response = query.range(offset, offset + limit - 1).execute()
    return response.data or [], int(response.count or 0)
