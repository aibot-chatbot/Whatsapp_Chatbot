from flask import Blueprint, g, jsonify, request

from app.decorators.auth_decorator import token_required
from app.services.company_status_service import company_operational_required
from app.services.automation_service import (
    apply_crm_stage_automation,
)
from app.database.automation_event_repository import (
    automation_events_table_available,
    list_automation_events,
)
from app.utils.access_control import role_required, verify_chatbot_access


automation_blueprint = Blueprint("automation", __name__)


@automation_blueprint.route("/api/automation/health", methods=["GET"])
def automation_health():
    available = automation_events_table_available()
    return jsonify({
        "status": "ok" if available else "degraded",
        "checks": {"automation_events": available},
    }), 200


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
