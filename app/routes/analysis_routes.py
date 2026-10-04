"""Selected-Bot Analysis. Authenticated merchant routes never accept tenant IDs."""
from functools import wraps
from io import BytesIO
import os
import secrets

from flask import Blueprint, g, jsonify, request, send_file

from app.database import analysis_repository as repo
from app.decorators.auth_decorator import token_required
from app.rate_limit import limiter
from app.services.analysis_request_service import (
    SCHEDULED_KEY_PREFIX, validate_request_spec, schedule_period, schedule_owner_durably_unentitled,
    validate_schedule_choice,
)
from app.services.analysis_storage_service import read_export, FORMATS
from app.services.billing_guard import BillingLimitError, can_use_plan_feature
from app.services.company_status_service import ensure_company_operational, CompanyOperationalStatusError
from app.services.industry_template_catalog import get_template
from app.utils.access_control import role_required, verify_chatbot_access

analysis_blueprint = Blueprint("analysis", __name__)

# Automatic working flows (schedules, recording) are Pro-only; manual reports
# stay on ai_generated_reports alone.
AUTOMATION_FEATURE = "automation_workflows"
# The owner's schedule slot: weekday (weekly) or day (monthly) plus time.
SLOT_FIELDS = ("run_weekday", "run_day", "run_time")
DUE_PAGE_SIZE = 100
# ponytail: 10 pages = 1,000 due rows a tick can step past; raise it (or add
# a plan-aware due query) if more stuck schedules than that ever accumulate.
MAX_DUE_PAGES = 10


def _enabled():
    return os.getenv("AGENT_ANALYSIS_ENABLED", "false").lower() in {"1", "true"}


def _errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not _enabled():
            return jsonify(message="Analysis is not enabled yet.", code="analysis_disabled"), 503
        try:
            return fn(*args, **kwargs)
        except (BillingLimitError, CompanyOperationalStatusError) as exc:
            return jsonify(message=str(exc), code=exc.code), getattr(exc, "status_code", 403)
        except (repo.AnalysisUnavailable, repo.AnalysisConflict, repo.AnalysisRateLimited) as exc:
            return jsonify(message=str(exc)), exc.status_code
        except PermissionError:
            return jsonify(message="This report or bot is unavailable."), 404
        except ValueError as exc:
            return jsonify(message=str(exc)), 400
        except Exception as exc:
            # Never include database/provider messages or customer content in logs.
            from flask import current_app
            current_app.logger.error("Analysis request failed (%s)", type(exc).__name__)
            return jsonify(message="Analysis is temporarily unavailable."), 503
    return wrapped


def _authorize(bot_id):
    bot = verify_chatbot_access(bot_id)
    ensure_company_operational(g.company_id)
    can_use_plan_feature(g.company_id, "ai_generated_reports")
    return bot


def _body(fields):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - set(fields):
        raise ValueError("Invalid request fields.")
    return body


def _public_report(row, *, detail=False):
    keys = ("id", "request_text", "status", "created_at", "updated_at", "error_code", "request_spec")
    result = {key: row.get(key) for key in keys}
    result["formats"] = [kind for kind in FORMATS if kind in (row.get("manifest") or {})]
    if detail:
        result["result"] = row.get("result")
        result["snapshot"] = row.get("snapshot")
    return result


def _industry_with_name(published):
    industry = dict(published or {})
    try:
        industry["name"] = get_template(industry.get("template_id"))["name"]
    except ValueError:
        pass
    return industry


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis", methods=["GET"])
@token_required
@role_required("owner", "admin")
@_errors
def overview(bot_id):
    bot = _authorize(bot_id)
    context = repo.get_bot_context(g.company_id, bot_id)
    return jsonify(data={"bot": bot, "industry": _industry_with_name(context["bot"].get("industry_template_published")),
                         "role": context.get("settings", {}), "timezone": "Asia/Kuala_Lumpur"})


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis/records", methods=["GET"])
@token_required
@role_required("owner", "admin")
@_errors
def records(bot_id):
    _authorize(bot_id)
    after_id = request.args.get("after_id", "0")
    if not after_id.isdecimal():
        raise ValueError("Invalid record cursor.")
    rows = repo.list_business_events(g.company_id, bot_id, after_id=int(after_id), limit=100)
    return jsonify(data=rows, next_cursor=rows[-1]["id"] if len(rows) == 100 else None)


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis/messages", methods=["GET", "POST"])
@token_required
@role_required("owner", "admin")
@limiter.limit("6/minute", methods=["POST"])
@_errors
def messages(bot_id):
    _authorize(bot_id)
    if request.method == "GET":
        rows = repo.list_reports(g.company_id, bot_id, limit=50, before_id=request.args.get("before_id"))
        return jsonify(data=[_public_report(row) for row in rows], next_cursor=rows[-1]["id"] if len(rows) == 50 else None)
    body = _body({"text", "client_message_id", "request_spec"})
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("Enter a report request of up to 2,000 characters.")
    key = body.get("client_message_id")
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise ValueError("A request identifier is required.")
    if key.startswith(SCHEDULED_KEY_PREFIX):
        raise ValueError("That request identifier is reserved.")
    spec = validate_request_spec(body.get("request_spec", {}))
    row = repo.create_report_request(g.company_id, bot_id, g.user_id, key, text.strip(), request_spec=spec)
    return jsonify(data=_public_report(row)), 202


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis/reports/hide", methods=["POST"])
@token_required
@role_required("owner", "admin")
@limiter.limit("20/minute")
@_errors
def hide_reports(bot_id):
    """Remove one or more reports from the list, or clear every finished one. Nothing is deleted."""
    _authorize(bot_id)
    body = _body({"report_ids", "all_finished"})
    if body == {"all_finished": True}:
        report_ids = None
    elif set(body) == {"report_ids"} and isinstance(body["report_ids"], list) and body["report_ids"]:
        report_ids = body["report_ids"]
    else:
        raise ValueError("Choose the reports to remove, or clear all finished reports.")
    return jsonify(data={"hidden": repo.hide_reports(g.company_id, bot_id, g.user_id, report_ids)})


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis/reports/<uuid:report_id>", methods=["GET"])
@token_required
@role_required("owner", "admin")
@_errors
def report(bot_id, report_id):
    _authorize(bot_id)
    row = repo.get_report(g.company_id, bot_id, str(report_id))
    if not row:
        raise PermissionError()
    return jsonify(data=_public_report(row, detail=True))


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis/reports/<uuid:report_id>/download", methods=["GET"])
@token_required
@role_required("owner", "admin")
@_errors
def download(bot_id, report_id):
    _authorize(bot_id)
    row = repo.get_report(g.company_id, bot_id, str(report_id))
    if not row:
        raise PermissionError()
    kind = request.args.get("format", "pdf")
    if row.get("status") not in {"complete", "partial"}:
        return jsonify(message="Report files are not ready."), 409
    content = read_export(company_id=g.company_id, chatbot_id=bot_id, report_id=str(report_id),
                          manifest=(row.get("manifest") or {}).get(kind), format=kind)
    response = send_file(BytesIO(content), mimetype=FORMATS[kind], as_attachment=True,
                         download_name=f"report-{report_id}.{kind}", max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis/schedules", methods=["GET", "POST"])
@token_required
@role_required("owner", "admin")
@_errors
def schedules(bot_id):
    _authorize(bot_id)
    if request.method == "GET":
        return jsonify(data=repo.list_schedules(g.company_id, bot_id))
    body = _body({"frequency", "enabled", *SLOT_FIELDS})
    if type(body.get("enabled")) is not bool:
        raise ValueError("Choose whether the schedule is enabled.")
    slot = validate_schedule_choice(body.get("frequency"), **{field: body.get(field) for field in SLOT_FIELDS})
    next_due_at = None
    if body["enabled"]:
        # Turning automation off never needs the entitlement.
        can_use_plan_feature(g.company_id, AUTOMATION_FEATURE)
        # Enabling always carries the whole slot, so a new day/time takes
        # effect at once; disabling sends none and the stored choice stays.
        next_due_at = schedule_period(body["frequency"], **slot)["next_due_at"]
    row = repo.upsert_schedule(g.company_id, bot_id, g.user_id, frequency=body["frequency"],
                               enabled=body["enabled"], next_due_at=next_due_at, **slot)
    return jsonify(data=row)


@analysis_blueprint.route("/api/chatbots/<int:bot_id>/analysis/recording", methods=["GET", "POST"])
@token_required
@role_required("owner", "admin")
@_errors
def recording(bot_id):
    _authorize(bot_id)
    from app.database.business_observation_repository import get_recording_enabled, set_recording_enabled
    if request.method == "GET":
        return jsonify(data={"enabled": get_recording_enabled(g.company_id, bot_id)})
    body = _body({"enabled"})
    if type(body.get("enabled")) is not bool:
        raise ValueError("Choose whether to record customer requests.")
    if body["enabled"]:
        can_use_plan_feature(g.company_id, AUTOMATION_FEATURE)
    enabled = set_recording_enabled(g.company_id, bot_id, body["enabled"])
    return jsonify(data={"enabled": enabled})


def _internal(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = os.getenv("AGENT_INTERNAL_TOKEN", "")
        received = request.headers.get("Authorization", "")
        # Compare bytes: compare_digest raises TypeError on non-ASCII str input.
        if len(expected) < 32 or not secrets.compare_digest(
            received.encode("utf-8"), ("Bearer " + expected).encode("utf-8"),
        ):
            return jsonify(message="Unauthorized."), 401
        return fn(*args, **kwargs)
    return wrapped


@analysis_blueprint.route("/internal/analysis/schedules/tick", methods=["POST"])
@_internal
@_errors
def schedule_tick():
    _body(set())
    counts = {"enqueued": 0, "skipped": 0, "still_due": 0}
    for _ in range(MAX_DUE_PAGES):
        # Rows that stay due are stepped past, never re-read at the head: one
        # tenant's stuck schedule must not starve every tenant behind it.
        page = repo.list_due_schedules(limit=DUE_PAGE_SIZE, offset=counts["still_due"])
        for schedule in page:
            counts[_tick_schedule(schedule)] += 1
        if len(page) < DUE_PAGE_SIZE:
            break
    return jsonify(data={"enqueued": counts["enqueued"], "skipped": counts["skipped"]})


def _owner_period(schedule):
    # A row without a slot raises ValueError, which leaves it still_due.
    return schedule_period(schedule["frequency"], **{field: schedule.get(field) for field in SLOT_FIELDS})


def _tick_schedule(schedule):
    """Enqueue one due schedule; return enqueued, skipped or still_due."""
    company_id = schedule["company_id"]
    try:
        ensure_company_operational(company_id)
        # A scheduled report is both a report and an automatic working flow.
        can_use_plan_feature(company_id, "ai_generated_reports")
        can_use_plan_feature(company_id, AUTOMATION_FEATURE)
    except CompanyOperationalStatusError:
        return "still_due"
    except BillingLimitError as exc:
        # Skip the period only when billing was read: a plan without the flag,
        # or a churned (cancelled/expired) subscription. A failed billing
        # lookup keeps the period intact.
        if exc.code != "feature_not_available" and not schedule_owner_durably_unentitled(company_id):
            return "still_due"
        try:
            repo.skip_schedule_period(schedule, next_due_at=_owner_period(schedule)["next_due_at"])
        except (PermissionError, ValueError):
            return "still_due"
        return "skipped"
    try:
        # RPC rechecks current actor role/company/Bot; the worker rechecks plan.
        period = _owner_period(schedule)
        result = repo.enqueue_schedule_report(company_id, schedule["chatbot_id"], schedule["id"], **period)
    except (PermissionError, ValueError):
        # Actor removed, pending-report limit, conflicting request: this
        # schedule waits; the tick carries on for everyone else.
        return "still_due"
    if result.get("enqueued"):
        return "enqueued"
    if schedule.get("last_period_key") == period["period_key"]:
        # This period already ran (the owner moved today's slot later after
        # it fired). The RPC declines it without moving next_due_at, so step
        # to the next slot instead of staying due for a whole period.
        try:
            repo.skip_schedule_period(schedule, next_due_at=period["next_due_at"])
        except (PermissionError, ValueError):
            return "still_due"
        return "skipped"
    return "still_due"


@analysis_blueprint.route("/internal/agent-model-steps", methods=["POST"])
@_internal
@_errors
def agent_model_step():
    body = _body({"run_id", "step_id"})
    from uuid import UUID
    run_id = str(UUID(str(body.get("run_id"))))
    if body.get("step_id") not in {"plan", "analyze"}:
        raise ValueError("Invalid model step.")
    from app.services.analysis_worker_service import execute_model_step
    return jsonify(data=execute_model_step(run_id=run_id, step_id=body["step_id"]))


@analysis_blueprint.route("/internal/tuition-reminders/send", methods=["POST"])
@_internal
@_errors
def send_trial_reminder():
    body = _body({"event_id", "lease_token"})
    from uuid import UUID
    if type(body.get("event_id")) is not int or body["event_id"] <= 0:
        raise ValueError("Invalid reminder event.")
    token = str(UUID(str(body.get("lease_token"))))
    from app.services.tuition_reminder_service import execute_tuition_reminder
    return jsonify(data=execute_tuition_reminder(event_id=body["event_id"], lease_token=token))


@analysis_blueprint.route("/internal/tuition-reminders/tick", methods=["POST"])
@_internal
@_errors
def trial_reminder_tick():
    _body(set())
    from app.services.tuition_reminder_service import enqueue_due_reminders
    return jsonify(data=enqueue_due_reminders(limit=100))
