"""Authenticated, company-scoped GEO analysis routes."""
from functools import wraps
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.database import geo_repository
from app.database import geo_monitoring_repository
from app.decorators.auth_decorator import token_required
from app.rate_limit import limiter
from app.services.billing_guard import BillingLimitError, get_company_geo_entitlement
from app.services.company_status_service import CompanyOperationalStatusError, ensure_company_operational
from app.services.geo_analysis_service import MIN_RELIABLE_SAMPLES, ROLLING_ANALYSIS_LIMIT, run_analysis
from app.services.geo_comparison_service import GeoComparisonInProgress, run_metered_comparison
from app.services.geo_monitoring_service import save_schedule
from app.services.geo_provider_service import comparison_capability, platform_capabilities


geo_blueprint = Blueprint("geo", __name__, url_prefix="/api/geo")


def _errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BillingLimitError as exc:
            return jsonify(status="error", code=exc.code, message=str(exc)), 403
        except CompanyOperationalStatusError as exc:
            return jsonify(status="error", code=exc.code, message=str(exc)), exc.status_code
        except geo_repository.GeoMonthlyLimitExceeded:
            return jsonify(status="error", code="geo_monthly_limit",
                           message="Your monthly GEO provider-check allowance has been used. It resets next month."), 403
        except geo_repository.GeoIdempotencyConflict as exc:
            return jsonify(status="error", code="geo_idempotency_conflict", message=str(exc)), 409
        except GeoComparisonInProgress as exc:
            return jsonify(status="error", code="geo_comparison_in_progress", message=str(exc)), 409
        except geo_repository.GeoStorageUnavailable:
            return jsonify(status="error", code="geo_storage_unavailable",
                           message="GEO analysis is temporarily unavailable."), 503
        except RequestEntityTooLarge:
            return jsonify(status="error", code="geo_request_too_large",
                           message="GEO analysis request is too large."), 413
        except ValueError as exc:
            return jsonify(status="error", code="invalid_geo_request", message=str(exc)), 400
        except Exception as exc:
            from flask import current_app
            current_app.logger.error("GEO request failed (%s)", type(exc).__name__)
            return jsonify(status="error", code="geo_unavailable",
                           message="GEO analysis is temporarily unavailable."), 503
    return wrapped


def _authorize():
    ensure_company_operational(g.company_id)
    return get_company_geo_entitlement(g.company_id)


def _next_month_iso():
    now = datetime.now(timezone.utc)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc).isoformat()


@geo_blueprint.get("/capabilities")
@token_required
@_errors
def capabilities():
    entitlement = _authorize()
    providers = platform_capabilities()
    used = geo_repository.get_monthly_usage(g.company_id)
    limit = entitlement["monthly_executions"]
    return jsonify(status="success", data={
        "enabled": True,
        "comparison": comparison_capability(),
        "plan": {"code": entitlement["plan_code"], "label": entitlement["label"]},
        "platforms": {platform: {**metadata, "included": platform in entitlement["platforms"]}
                      for platform, metadata in providers.items()},
        "limits": {"keywords": entitlement.get("keywords_per_analysis", 10),
                   "prompts": entitlement["prompts_per_analysis"],
                   "samples_per_prompt": entitlement["samples_per_prompt"],
                   "minimum_reliable_samples": MIN_RELIABLE_SAMPLES,
                   "rolling_analysis_window": ROLLING_ANALYSIS_LIMIT,
                   "monitoring_frequencies": entitlement.get("monitoring_frequencies", []),
                   "platforms": len(entitlement["platforms"]),
                   "executions": min(20, entitlement.get("executions_per_analysis", 20)),
                   "monthly_executions": limit,
                   "history": entitlement["history_limit"]},
        "usage": {"used": used, "remaining": max(0, limit - used), "resets_at": _next_month_iso()},
    })


@geo_blueprint.get("/analyses")
@token_required
@_errors
def analyses():
    entitlement = _authorize()
    requested = request.args.get("limit", entitlement["history_limit"])
    try:
        limit = min(int(requested), entitlement["history_limit"])
    except (TypeError, ValueError):
        raise ValueError("History limit must be a number.") from None
    return jsonify(status="success", data=geo_repository.list_analyses(g.company_id, limit))


@geo_blueprint.get("/analyses/<uuid:analysis_id>")
@token_required
@_errors
def analysis_detail(analysis_id):
    _authorize()
    result = geo_repository.get_analysis(g.company_id, str(analysis_id))
    if not result:
        return jsonify(status="error", code="geo_analysis_not_found", message="GEO analysis not found."), 404
    return jsonify(status="success", data=result)


@geo_blueprint.route("/monitoring", methods=["GET", "PUT"])
@token_required
@limiter.limit("10/hour")
@_errors
def monitoring():
    entitlement = _authorize()
    if request.method == "GET":
        return jsonify(status="success", data=geo_monitoring_repository.get_schedule(g.company_id))
    request.max_content_length = min(request.max_content_length or 32768, 32768)
    if request.content_length is not None and request.content_length > 32768:
        return jsonify(status="error", code="geo_request_too_large",
                       message="GEO monitoring request is too large."), 413
    result = save_schedule(g.company_id, g.user_id, request.get_json(silent=True), entitlement)
    return jsonify(status="success", data=result)


@geo_blueprint.post("/analyses")
@token_required
@limiter.limit("5/hour")
@limiter.limit("20/day")
@_errors
def create_analysis():
    entitlement = _authorize()
    # Werkzeug enforces this while reading the stream, including chunked
    # requests that intentionally omit Content-Length.
    request.max_content_length = min(request.max_content_length or 32768, 32768)
    if request.content_length is not None and request.content_length > 32768:
        return jsonify(status="error", code="geo_request_too_large",
                       message="GEO analysis request is too large."), 413
    result = run_analysis(g.company_id, g.user_id, request.get_json(silent=True), entitlement)
    return jsonify(status="success", data=result), 201


@geo_blueprint.post("/provider-comparison")
@token_required
@limiter.limit("3/hour")
@limiter.limit("10/day")
@_errors
def provider_comparison():
    entitlement = _authorize()
    request.max_content_length = min(request.max_content_length or 4096, 4096)
    if request.content_length is not None and request.content_length > 4096:
        return jsonify(status="error", code="geo_request_too_large",
                       message="Comparison request is too large."), 413
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {"prompt", "country", "language"}:
        raise ValueError("A valid comparison request is required.")
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise ValueError("A UUID Idempotency-Key header is required.")
    result = run_metered_comparison(
        g.company_id, g.user_id, entitlement, idempotency_key,
        prompt=body.get("prompt"), country=body.get("country"), language=body.get("language"),
    )
    return jsonify(status="success", data=result)
