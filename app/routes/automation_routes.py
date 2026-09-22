from threading import Lock
from time import monotonic

from flask import Blueprint, current_app, g, jsonify, request

from app.decorators.auth_decorator import token_required
from app.decorators.security import worker_token_required
from app.rate_limit import limiter
from app.services.company_status_service import company_operational_required
from app.services.langflow_adapter import langflow_automation_health
from app.services.n8n_adapter import n8n_automation_health, n8n_worker_enabled, worker_lease_seconds
from app.services.automation_service import (
    apply_crm_stage_automation,
)
from app.database.automation_event_repository import (
    WORKER_TERMINAL_STATUSES,
    automation_events_table_available,
    claim_queued_automation_events,
    get_automation_event_by_id,
    list_automation_events,
    update_automation_event_status,
)
from app.utils.access_control import role_required, verify_chatbot_access


automation_blueprint = Blueprint("automation", __name__)


@automation_blueprint.route("/api/automation/health", methods=["GET"])
def automation_health():
    # ponytail: one probe per process; use shared readiness if workers scale out.
    state = current_app.extensions.setdefault(
        "automation_health", {"lock": Lock(), "expires": 0, "result": None}
    )
    if monotonic() < state["expires"]:
        return jsonify(state["result"]), 200
    if not state["lock"].acquire(blocking=False):
        return jsonify({
            "status": "degraded",
            "checks": {
                "automation_events": False,
                "langflow": {"status": "checking"},
                "n8n": {"status": "checking"},
            },
        }), 200
    try:
        if monotonic() >= state["expires"]:
            available = automation_events_table_available()
            langflow = langflow_automation_health()
            n8n = n8n_automation_health()
            healthy = (
                available
                and langflow["status"] in {"ok", "disabled"}
                and n8n["status"] in {"ok", "disabled"}
            )
            state["result"] = {
                "status": "ok" if healthy else "degraded",
                "checks": {
                    "automation_events": available,
                    "langflow": langflow,
                    "n8n": n8n,
                },
            }
            state["expires"] = monotonic() + 10
        return jsonify(state["result"]), 200
    finally:
        state["lock"].release()


@automation_blueprint.route("/api/automation/events", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_automation_events():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        status = request.args.get("status")
        limit = request.args.get("limit", 50, type=int)

        if chatbot_id:
            access = verify_chatbot_access(chatbot_id)
            company_id = access["company_id"]
        else:
            company_id = getattr(g, "company_id", None)
            if not company_id:
                return jsonify({"status": "error", "message": "Unauthorized"}), 401

        events = list_automation_events(
            company_id=company_id,
            chatbot_id=chatbot_id,
            status=status,
            limit=limit,
        )
        return jsonify({"status": "success", "data": {"events": events}}), 200
    except PermissionError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        return jsonify({"status": "error", "message": "Unable to load automation events."}), 500


@automation_blueprint.route("/api/automation/crm-stage", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def automate_crm_stage():
    data = request.get_json(silent=True) or {}
    chatbot_id = data.get("chatbot_id")
    lead_id = data.get("lead_id")
    target_status = data.get("target_status")

    if not chatbot_id or not lead_id or not target_status:
        return jsonify({
            "status": "error",
            "message": "chatbot_id, lead_id, and target_status are required",
        }), 400

    try:
        chatbot_id = int(chatbot_id)
        lead_id = int(lead_id)
        access = verify_chatbot_access(chatbot_id)
        result = apply_crm_stage_automation(
            company_id=access["company_id"],
            chatbot_id=chatbot_id,
            lead_id=lead_id,
            target_status=target_status,
            reason=data.get("reason", ""),
            idempotency_key=data.get("idempotency_key"),
        )
        return jsonify({"status": "success", "data": result}), 200
    except PermissionError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        return jsonify({"status": "error", "message": "Unable to automate CRM stage."}), 500


@automation_blueprint.route("/api/automation/worker/events", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("RATELIMIT_AUTOMATION_WORKER", "60/minute"))
@worker_token_required
def claim_automation_worker_events():
    """Hand queued outbox events to the n8n worker under a lease.

    POST rather than GET because claiming mutates status. The worker is a
    platform actor, so this deliberately spans tenants; nothing here accepts a
    caller-supplied company_id.
    """
    if not n8n_worker_enabled():
        return jsonify({"status": "error", "message": "Automation worker is disabled"}), 503

    data = request.get_json(silent=True) or {}
    requested = data.get("limit", 10)
    if isinstance(requested, bool) or not isinstance(requested, int):
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    lease = worker_lease_seconds()
    try:
        events = claim_queued_automation_events(limit=requested, lease_seconds=lease)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        return jsonify({"status": "error", "message": "Unable to claim automation events."}), 500

    return jsonify({
        "status": "success",
        "data": {"events": events, "lease_seconds": lease},
    }), 200


@automation_blueprint.route(
    "/api/automation/worker/events/<int:event_id>/status", methods=["POST"]
)
@limiter.limit(lambda: current_app.config.get("RATELIMIT_AUTOMATION_WORKER", "60/minute"))
@worker_token_required
def report_automation_worker_event(event_id):
    """Close out one leased event as completed or failed.

    company_id and chatbot_id come from the stored row, never from the request,
    so a worker cannot aim an update at a row it was not handed. A repeated
    callback on an already-finished event is a success with no write, because
    n8n retries are expected and must not reopen or rewrite settled work.
    """
    if not n8n_worker_enabled():
        return jsonify({"status": "error", "message": "Automation worker is disabled"}), 503

    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip().lower()
    if status not in WORKER_TERMINAL_STATUSES:
        return jsonify({
            "status": "error",
            "message": "status must be completed or failed",
        }), 400

    result = data.get("result")
    if result is not None and not isinstance(result, dict):
        return jsonify({"status": "error", "message": "result must be an object"}), 400

    try:
        event = get_automation_event_by_id(event_id)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        return jsonify({"status": "error", "message": "Unable to load automation event."}), 500

    if not event:
        return jsonify({"status": "error", "message": "Automation event not found"}), 404

    current = str(event.get("status") or "")
    if current in WORKER_TERMINAL_STATUSES:
        return jsonify({
            "status": "success",
            "data": {"event": event, "changed": False},
        }), 200
    if current != "running":
        return jsonify({
            "status": "error",
            "message": "Only a claimed event can be reported",
        }), 409

    try:
        updated = update_automation_event_status(
            company_id=event["company_id"],
            chatbot_id=event["chatbot_id"],
            event_id=event_id,
            status=status,
            result=result,
            error_message=data.get("error_message"),
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        return jsonify({"status": "error", "message": "Unable to update automation event."}), 500

    return jsonify({
        "status": "success",
        "data": {"event": updated or event, "changed": bool(updated)},
    }), 200
