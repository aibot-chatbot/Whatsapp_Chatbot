"""Explicit cross-tenant company reads for authorized platform admins."""

from app.database.db import supabase


LIST_FIELDS = "id,company_name,business_type,status,contact_email,created_at,updated_at"
DETAIL_FIELDS = LIST_FIELDS + ",contact_phone"
COUNT_FIELDS = "id"
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


def get_company_counts_for_platform_admin():
    """Return exact company counts by public company status."""

    def _count(status=None):
        query = supabase.table("companies").select(COUNT_FIELDS, count="exact")
        if status is not None:
            query = query.eq("status", status)
        response = query.limit(1).execute()
        return int(response.count or 0)

    return {
        "total": _count(),
        "active": _count("active"),
        "inactive": _count("inactive"),
    }


def get_companies_by_ids_for_platform_admin(company_ids):
    """Return safe company fields for a set of positive company IDs."""
    valid_ids = sorted({
        company_id for company_id in company_ids
        if isinstance(company_id, int) and not isinstance(company_id, bool) and company_id > 0
    })
    if not valid_ids:
        return {}
    response = (
        supabase.table("companies")
        .select("id,company_name,status")
        .in_("id", valid_ids)
        .execute()
    )
    return {
        row["id"]: row for row in (response.data or [])
        if isinstance(row.get("id"), int)
    }


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_company_lifecycle_result(result, *, company_id, old_status, new_status, action):
    if not isinstance(result, dict):
        raise RuntimeError("Malformed company lifecycle RPC result")
    company = result.get("company")
    audit = result.get("audit_event")
    if not isinstance(company, dict) or not isinstance(audit, dict):
        raise RuntimeError("Malformed company lifecycle RPC result")
    if company.get("id") != company_id:
        raise RuntimeError("Company lifecycle RPC company mismatch")
    if company.get("old_status") != old_status or company.get("new_status") != new_status:
        raise RuntimeError("Company lifecycle RPC status mismatch")
    if not isinstance(company.get("updated_at"), str) or not company.get("updated_at").strip():
        raise RuntimeError("Company lifecycle RPC updated_at missing")
    if not _is_positive_int(audit.get("id")):
        raise RuntimeError("Malformed company lifecycle audit result")
    if audit.get("action") != action:
        raise RuntimeError("Company lifecycle audit action mismatch")
    if audit.get("resource_type") != "company":
        raise RuntimeError("Company lifecycle audit resource mismatch")
    if audit.get("resource_id") != str(company_id):
        raise RuntimeError("Company lifecycle audit resource mismatch")
    return {"company": company, "audit_event": audit}


def suspend_platform_company_for_platform_admin(actor_mapping_id, company_id):
    _positive_company_id(actor_mapping_id)
    _positive_company_id(company_id)
    response = supabase.rpc(
        "suspend_platform_company",
        {
            "p_actor_platform_admin_user_id": actor_mapping_id,
            "p_company_id": company_id,
        },
    ).execute()
    return _validate_company_lifecycle_result(
        response.data,
        company_id=company_id,
        old_status="active",
        new_status="inactive",
        action="platform_admin.company.suspend",
    )


def restore_platform_company_for_platform_admin(actor_mapping_id, company_id):
    _positive_company_id(actor_mapping_id)
    _positive_company_id(company_id)
    response = supabase.rpc(
        "restore_platform_company",
        {
            "p_actor_platform_admin_user_id": actor_mapping_id,
            "p_company_id": company_id,
        },
    ).execute()
    return _validate_company_lifecycle_result(
        response.data,
        company_id=company_id,
        old_status="inactive",
        new_status="active",
        action="platform_admin.company.restore",
    )
