"""Company-scoped persistence for GEO analyses and prompt executions."""
from datetime import datetime, timezone
import json
from uuid import UUID

from app.database.db import supabase


class GeoStorageUnavailable(RuntimeError):
    pass


class GeoMonthlyLimitExceeded(RuntimeError):
    pass


class GeoIdempotencyConflict(RuntimeError):
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


def _bounded_metadata(value, max_bytes):
    """Keep provider evidence JSON within the database contract.

    Some search providers include fetched page bodies inside citation metadata.
    The URL/title/position remain in their dedicated columns; oversized opaque
    metadata is replaced with a small, explicit truncation marker.
    """
    if not isinstance(value, dict):
        return {}
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return {"metadata_truncated": True, "reason": "not_json_serializable"}
    if len(encoded.encode("utf-8")) <= max_bytes:
        return value
    source_type = value.get("type") or value.get("kind")
    return {
        "metadata_truncated": True,
        "source_type": str(source_type)[:80] if source_type else None,
        "available_fields": sorted(str(key)[:80] for key in value)[:40],
    }


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
    company = _positive(company_id, "company_id")
    analyses = _rows(supabase.table("geo_analyses").select("execution_count")
                     .eq("company_id", company).gte("created_at", period_start.isoformat()))
    comparisons = _rows(supabase.table("geo_provider_comparisons").select("execution_count")
                        .eq("company_id", company).gte("created_at", period_start.isoformat()))
    return sum(row.get("execution_count") or 0 for row in [*analyses, *comparisons])


def reserve_comparison(company_id, actor_user_id, entitlement, idempotency_key,
                       *, reservation_token, prompt, country, language):
    params = {
        "p_company_id": _positive(company_id, "company_id"),
        "p_actor_user_id": _positive(actor_user_id, "actor_user_id"),
        "p_plan_code": entitlement["plan_code"],
        "p_monthly_limit": _positive(entitlement["monthly_executions"], "monthly_limit"),
        "p_idempotency_key": _uuid(idempotency_key),
        "p_reservation_token": _uuid(reservation_token),
        "p_prompt": prompt,
        "p_country": country,
        "p_language": language,
    }
    try:
        rows = supabase.rpc("reserve_geo_provider_comparison", params).execute().data
    except Exception as exc:
        message = str(exc)
        if "geo_monthly_limit" in message:
            raise GeoMonthlyLimitExceeded("Monthly GEO provider-check allowance reached") from None
        if "geo_idempotency_conflict" in message:
            raise GeoIdempotencyConflict("This comparison request identifier was already used for different input") from None
        recovered = get_comparison_by_key(company_id, actor_user_id, idempotency_key)
        if recovered and recovered.get("reservation_token") == params["p_reservation_token"]:
            return {**recovered, "comparison_id": recovered.get("id"), "reserved_new": True}
        raise GeoStorageUnavailable("GEO comparison storage is unavailable") from None
    if not isinstance(rows, list) or len(rows) != 1:
        raise GeoStorageUnavailable("GEO comparison reservation was not confirmed")
    return rows[0]


def get_comparison_by_key(company_id, actor_user_id, idempotency_key):
    rows = _rows(supabase.table("geo_provider_comparisons").select("*")
                 .eq("company_id", _positive(company_id, "company_id"))
                 .eq("actor_user_id", _positive(actor_user_id, "actor_user_id"))
                 .eq("idempotency_key", _uuid(idempotency_key)).limit(1))
    return rows[0] if rows else None


def start_comparison(company_id, actor_user_id, comparison_id, reservation_token):
    params = {
        "p_company_id": _positive(company_id, "company_id"),
        "p_actor_user_id": _positive(actor_user_id, "actor_user_id"),
        "p_comparison_id": _uuid(comparison_id),
        "p_reservation_token": _uuid(reservation_token),
    }
    try:
        rows = supabase.rpc("start_geo_provider_comparison", params).execute().data
    except Exception:
        recovered = _rows(supabase.table("geo_provider_comparisons").select("*")
                          .eq("company_id", params["p_company_id"])
                          .eq("actor_user_id", params["p_actor_user_id"])
                          .eq("id", params["p_comparison_id"])
                          .eq("reservation_token", params["p_reservation_token"]).limit(1))
        if recovered and recovered[0].get("status") == "running":
            return recovered[0]
        raise GeoStorageUnavailable("GEO comparison start was not confirmed") from None
    if not isinstance(rows, list) or len(rows) != 1:
        raise GeoStorageUnavailable("GEO comparison reservation expired before execution")
    return rows[0]


def finish_comparison(company_id, comparison_id, *, status, result, error_code=None):
    if status not in {"complete", "partial", "failed"}:
        raise ValueError("Invalid GEO comparison status")
    if not isinstance(result, dict):
        raise ValueError("GEO comparison result must be an object")
    rows = _rows(supabase.table("geo_provider_comparisons").update({
        "status": status,
        "result": result,
        "error_code": error_code,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("company_id", _positive(company_id, "company_id"))
      .eq("id", _uuid(comparison_id)).eq("status", "running"))
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO comparison completion was not confirmed")
    return rows[0]


def add_execution(company_id, analysis_id, execution):
    scope = {
        "company_id": _positive(company_id, "company_id"),
        "analysis_id": _uuid(analysis_id),
    }
    citations = execution.pop("citations", [])
    execution = {**execution,
                 "provider_metadata": _bounded_metadata(execution.get("provider_metadata"), 60000)}
    rows = _rows(supabase.table("geo_prompt_executions").insert({**scope, **execution}))
    if len(rows) != 1:
        raise GeoStorageUnavailable("GEO storage did not confirm the prompt execution")
    stored = rows[0]
    if citations:
        citation_rows = []
        for citation in citations:
            url = citation.get("url") if isinstance(citation, dict) else None
            if not isinstance(url, str) or not 1 <= len(url) <= 4096:
                continue
            domain = citation.get("domain")
            title = citation.get("title")
            position = citation.get("position")
            citation_rows.append({
                "company_id": scope["company_id"],
                "execution_id": stored["id"],
                "url": url,
                "domain": str(domain)[:253] if domain else None,
                "title": str(title)[:1000] if title else None,
                "citation_position": position if isinstance(position, int) and position > 0 else None,
                "provider_metadata": _bounded_metadata(citation.get("metadata"), 30000),
            })
        stored["citations"] = (_rows(supabase.table("geo_execution_citations").insert(citation_rows))
                               if citation_rows else [])
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
