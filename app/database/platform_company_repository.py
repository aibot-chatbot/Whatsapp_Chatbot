"""Explicit cross-tenant company reads for authorized platform admins."""

from app.database.db import supabase


LIST_FIELDS = "id,company_name,business_type,status,contact_email,created_at,updated_at"
DETAIL_FIELDS = LIST_FIELDS + ",contact_phone"
ALLOWED_STATUSES = {"active", "inactive"}
ALLOWED_SORT_FIELDS = {"created_at", "company_name", "status", "id"}
ALLOWED_SORT_ORDERS = {"asc", "desc"}


def _positive_company_id(company_id):
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        raise ValueError("company_id must be a positive integer")


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


def list_companies_for_platform_admin(
    *, limit, offset, search=None, status=None, sort_by="created_at", sort_order="desc"
):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if status is not None and status not in ALLOWED_STATUSES:
        raise ValueError("Unsupported company status")
    if sort_by not in ALLOWED_SORT_FIELDS or sort_order not in ALLOWED_SORT_ORDERS:
        raise ValueError("Unsupported company ordering")

    query = supabase.table("companies").select(LIST_FIELDS, count="exact")
    if search is not None:
        pattern = _escaped_ilike_pattern(search)
        query = query.or_(
            f"company_name.ilike.{pattern},contact_email.ilike.{pattern}"
        )
    if status is not None:
        query = query.eq("status", status)

    descending = sort_order == "desc"
    query = query.order(sort_by, desc=descending)
    if sort_by != "id":
        query = query.order("id", desc=descending)
    response = query.range(offset, offset + limit - 1).execute()
    return response.data or [], int(response.count or 0)


def get_company_for_platform_admin(company_id):
    _positive_company_id(company_id)
    response = (
        supabase.table("companies")
        .select(DETAIL_FIELDS)
        .eq("id", company_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None
