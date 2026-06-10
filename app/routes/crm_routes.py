from flask import Blueprint, jsonify, request

from app.database.crm_lead_repository import (
    ALLOWED_CRM_LEAD_STATUSES,
    get_crm_leads_by_chatbot,
    update_crm_lead_status_notes,
)
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access


crm_blueprint = Blueprint("crm", __name__)


@crm_blueprint.route("/api/crm/leads", methods=["GET"])
@token_required
def get_crm_leads():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        status = request.args.get("status")
        limit = request.args.get("limit", 50, type=int)

        verify_chatbot_access(chatbot_id)
        leads = get_crm_leads_by_chatbot(chatbot_id, status=status, limit=limit)

        return jsonify({
            "status": "success",
            "data": {
                "leads": leads
            }
        }), 200

    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 401

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@crm_blueprint.route("/api/crm/leads/<int:lead_id>", methods=["PATCH"])
@token_required
def update_crm_lead(lead_id):
    try:
        data = request.get_json(silent=True) or {}
        chatbot_id = data.get("chatbot_id")

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        chatbot_id = int(chatbot_id)
        status = data.get("status")
        notes = data.get("notes")
        assigned_to = data.get("assigned_to")

        if status is not None and str(status).strip().lower() not in ALLOWED_CRM_LEAD_STATUSES:
            return jsonify({
                "status": "error",
                "message": "Invalid CRM lead status."
            }), 400

        verify_chatbot_access(chatbot_id)
        update_kwargs = {
            "chatbot_id": chatbot_id,
            "lead_id": lead_id,
            "status": status,
            "notes": notes,
            "assigned_to": assigned_to,
        }

        if "follow_up_date" in data:
            update_kwargs["follow_up_date"] = data.get("follow_up_date")

        lead = update_crm_lead_status_notes(**update_kwargs)

        if not lead:
            return jsonify({
                "status": "error",
                "message": "CRM lead not found"
            }), 404

        return jsonify({
            "status": "success",
            "data": {
                "lead": lead
            }
        }), 200

    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
