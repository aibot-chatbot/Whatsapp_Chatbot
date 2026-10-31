"""Durably metered, idempotent provider-route comparisons."""
from uuid import uuid4

from app.database import geo_repository
from app.services.geo_provider_service import (
    compare_openai_routes,
    comparison_capability,
    validate_comparison_input,
)


class GeoComparisonInProgress(RuntimeError):
    pass


def _public_result(row, *, replayed):
    result = row.get("result")
    required = {"prompt", "country", "language", "direct", "openrouter", "comparison", "methodology"}
    if not isinstance(result, dict) or not required.issubset(result):
        raise geo_repository.GeoStorageUnavailable("Stored GEO comparison result is unavailable")
    return {**result, "metering": {
        "comparison_id": row.get("comparison_id") or row.get("id"),
        "provider_checks": 2,
        "replayed": bool(replayed),
    }}


def _result_status(result):
    complete = sum(
        1 for key in ("direct", "openrouter")
        if isinstance(result.get(key), dict) and result[key].get("request_status") == "complete"
    )
    return "complete" if complete == 2 else "partial" if complete else "failed"


def run_metered_comparison(company_id, actor_user_id, entitlement, idempotency_key,
                           *, prompt, country, language):
    prompt, country, language = validate_comparison_input(prompt, country, language)
    existing = geo_repository.get_comparison_by_key(company_id, actor_user_id, idempotency_key)
    if existing:
        if (existing.get("prompt"), existing.get("country"), existing.get("language")) != (
                prompt, country, language):
            raise geo_repository.GeoIdempotencyConflict(
                "This comparison request identifier was already used for different input")
        if existing.get("status") in {"complete", "partial", "failed"}:
            return _public_result(existing, replayed=True)
        if existing.get("status") == "running":
            raise GeoComparisonInProgress(
                "This comparison is already running. Wait for it to finish before retrying.")
    if not comparison_capability().get("enabled"):
        raise ValueError("Configure both OPENAI_API_KEY and OPENROUTER_API_KEY before running a comparison.")
    reservation_token = str(uuid4())
    reservation = geo_repository.reserve_comparison(
        company_id, actor_user_id, entitlement, idempotency_key,
        reservation_token=reservation_token, prompt=prompt, country=country, language=language,
    )
    if not reservation.get("reserved_new"):
        if reservation.get("status") in {"complete", "partial", "failed"}:
            return _public_result(reservation, replayed=True)
        raise GeoComparisonInProgress(
            "This comparison is already running. Wait for it to finish before retrying."
        )

    comparison_id = reservation.get("comparison_id")
    geo_repository.start_comparison(company_id, actor_user_id, comparison_id, reservation_token)
    try:
        result = compare_openai_routes(prompt, country, language)
    except Exception:
        try:
            geo_repository.finish_comparison(
                company_id, comparison_id, status="failed", result={"unexpected_failure": True},
                error_code="comparison_interrupted",
            )
        except Exception:
            pass
        raise

    status = _result_status(result)
    stored = geo_repository.finish_comparison(
        company_id, comparison_id, status=status, result=result,
        error_code="all_providers_failed" if status == "failed" else None,
    )
    return _public_result(stored, replayed=False)
