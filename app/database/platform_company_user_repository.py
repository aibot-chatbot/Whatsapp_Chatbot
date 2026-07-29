"""Explicit company-user reads for authorized platform admins."""

from app.database.db import supabase


LIST_FIELDS = "id,full_name,email,role,status,created_at,updated_at"
ALLOWED_SORT_FIELDS = {"created_at", "email", "full_name", "id"}
ALLOWED_SORT_ORDERS = {"asc", "desc"}


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


def list_company_users_for_platform_admin(
    *, company_id, limit, offset, search=None, sort_by="created_at", sort_order="desc"
):
    _positive_company_id(company_id)
    _validate_page(limit, offset)
    if sort_by not in ALLOWED_SORT_FIELDS or sort_order not in ALLOWED_SORT_ORDERS:
        raise ValueError("Unsupported user ordering")

    query = (
        supabase.table("users")
        .select(LIST_FIELDS, count="exact")
        .eq("company_id", company_id)
    )
    if search is not None:
        pattern = _escaped_ilike_pattern(search)
        query = query.or_(f"email.ilike.{pattern},full_name.ilike.{pattern}")

    descending = sort_order == "desc"
    query = query.order(sort_by, desc=descending)
    if sort_by != "id":
        query = query.order("id", desc=descending)
    response = query.range(offset, offset + limit - 1).execute()
    return response.data or [], int(response.count or 0)
