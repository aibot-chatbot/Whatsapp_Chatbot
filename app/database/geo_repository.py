"""Company-scoped persistence for GEO analyses and prompt executions."""
from datetime import datetime, timezone
from uuid import UUID

from app.database.db import supabase


class GeoStorageUnavailable(RuntimeError):
    pass


class GeoMonthlyLimitExceeded(RuntimeError):
    pass


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid analysis ID is required") from None


def _rows(query):
    try:
        rows = query.execute().data
    except Exception:
        raise GeoStorageUnavailable("GEO storage is unavailable") from None
    if not isinstance(rows, list):
        raise GeoStorageUnavailable("GEO storage returned an invalid response")
    return rows


def create_analysis(company_id, actor_user_id, spec, entitlement):
    execution_count = len(spec["prompts"]) * len(spec["platforms"]) * spec["samples_per_prompt"]
    params = {
        "p_company_id": _positive(company_id, "company_id"),
        "p_actor_user_id": _positive(actor_user_id, "actor_user_id"),
        "p_plan_code": entitlement["plan_code"],
        "p_monthly_limit": _positive(entitlement["monthly_executions"], "monthly_limit"),
        "p_execution_count": _positive(execution_count, "execution_count"),
        "p_brand_name": spec["brand_name"],
        "p_aliases": spec["aliases"],
        "p_competitors": spec["competitors"],
        "p_owned_domains": spec["owned_domains"],
        "p_country": spec["country"],
        "p_language": spec["language"],
        "p_platforms": spec["platforms"],
        "p_prompts": spec["prompts"],
        "p_samples_per_prompt": spec["samples_per_prompt"],
    }
    try:
        rows = supabase.rpc("reserve_geo_analysis", params).execute().data
    except Exception as exc:
        if "geo_monthly_limit" in str(exc):
            raise GeoMonthlyLimitExceeded("Monthly GEO provider-check allowance reached") from None
        raise GeoStorageUnavailable("GEO storage is unavailable") from None
    if not isinstance(rows, list):
        raise GeoStorageUnavailable("GEO storage returned an invalid response")
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO storage did not confirm the analysis")
    return rows[0]


def get_monthly_usage(company_id):
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = _rows(supabase.table("geo_analyses").select("execution_count")
                 .eq("company_id", _positive(company_id, "company_id"))
                 .gte("created_at", period_start.isoformat()))
    return sum(row.get("execution_count") or 0 for row in rows)


def add_execution(company_id, analysis_id, execution):
    scope = {
        "company_id": _positive(company_id, "company_id"),
        "analysis_id": _uuid(analysis_id),
    }
    citations = execution.pop("citations", [])
    rows = _rows(supabase.table("geo_prompt_executions").insert({**scope, **execution}))
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO storage did not confirm the prompt execution")
    stored = rows[0]
    if citations:
        citation_rows = [{
            "company_id": scope["company_id"],
            "execution_id": stored["id"],
            "url": citation["url"],
            "domain": citation.get("domain"),
            "title": citation.get("title"),
            "citation_position": citation.get("position"),
            "provider_metadata": citation.get("metadata") or {},
        } for citation in citations]
        stored["citations"] = _rows(supabase.table("geo_execution_citations").insert(citation_rows))
    else:
        stored["citations"] = []
    return stored


def finish_analysis(company_id, analysis_id, *, status, metrics, methodology, error_code=None):
    if status not in {"complete", "partial", "failed"}:
        raise ValueError("Invalid GEO analysis status")
    rows = _rows(supabase.table("geo_analyses").update({
        "status": status,
        "metrics": metrics,
        "methodology": methodology,
        "error_code": error_code,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("company_id", _positive(company_id, "company_id")).eq("id", _uuid(analysis_id)))
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO storage did not confirm completion")
    return rows[0]


def list_analyses(company_id, limit=20):
    size = max(1, min(int(limit), 50))
    return _rows(supabase.table("geo_analyses").select("*")
                 .eq("company_id", _positive(company_id, "company_id"))
                 .order("created_at", desc=True).limit(size))


def get_analysis(company_id, analysis_id):
    company = _positive(company_id, "company_id")
    identifier = _uuid(analysis_id)
    rows = _rows(supabase.table("geo_analyses").select("*")
                 .eq("company_id", company).eq("id", identifier).limit(1))
    if not rows:
        return None
    executions = _rows(supabase.table("geo_prompt_executions").select("*")
                       .eq("company_id", company).eq("analysis_id", identifier)
                       .order("prompt_index").order("platform").order("sample_index"))
    execution_ids = [row["id"] for row in executions]
    citations = (_rows(supabase.table("geo_execution_citations").select("*")
                       .eq("company_id", company).in_("execution_id", execution_ids)
                       .order("citation_position")) if execution_ids else [])
    citations_by_execution = {}
    for citation in citations:
        citations_by_execution.setdefault(citation["execution_id"], []).append(citation)
    for execution in executions:
        execution["citations"] = citations_by_execution.get(execution["id"], [])
    return {**rows[0], "executions": executions}
