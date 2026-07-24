from flask import Blueprint, g, jsonify, request

from app.database.conversation_repository import get_conversation_by_id_and_chatbot
from app.database.crm_lead_repository import (
    ALLOWED_CRM_LEAD_PRIORITIES,
    ALLOWED_CRM_LEAD_STATUSES,
    get_crm_leads_by_chatbot,
    upsert_crm_lead_by_conversation,
    update_crm_lead_status_notes,
)
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access
from app.services.billing_guard import can_use_plan_feature, BillingLimitError


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
        conversation_id = request.args.get("conversation_id", type=int)
        limit = request.args.get("limit", 50, type=int)

        verify_chatbot_access(chatbot_id)
        leads = get_crm_leads_by_chatbot(
            chatbot_id,
            status=status,
            limit=limit,
            conversation_id=conversation_id,
        )

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

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
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

        # Check CRM lead assignment feature gate if assigning to a non-null member
        if assigned_to is not None and assigned_to != "":
            can_use_plan_feature(g.company_id, "crm_lead_assignment")

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

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
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


@crm_blueprint.route("/api/crm/leads/upsert", methods=["POST"])
@token_required
def upsert_crm_lead():
    try:
        data = request.get_json(silent=True) or {}
        chatbot_id = data.get("chatbot_id")
        conversation_id = data.get("conversation_id")

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        if not conversation_id:
            return jsonify({
                "status": "error",
                "message": "conversation_id is required"
            }), 400

        chatbot_id = int(chatbot_id)
        conversation_id = int(conversation_id)
        status = str(data.get("status") or "new").strip().lower()
        # Check CRM lead assignment feature gate if assigning to a non-null member
        assigned_to = data.get("assigned_to")
        if assigned_to is not None and assigned_to != "":
            can_use_plan_feature(g.company_id, "crm_lead_assignment")

        priority = str(data.get("priority") or "medium").strip().lower()

        if status not in ALLOWED_CRM_LEAD_STATUSES:
            return jsonify({
                "status": "error",
                "message": "Invalid CRM lead status."
            }), 400

        if priority not in ALLOWED_CRM_LEAD_PRIORITIES:
            return jsonify({
                "status": "error",
                "message": "Invalid CRM lead priority."
            }), 400

        access = verify_chatbot_access(chatbot_id)
        conversation = get_conversation_by_id_and_chatbot(conversation_id, chatbot_id)

        if not conversation:
            return jsonify({
                "status": "error",
                "message": "Conversation not found"
            }), 404

        lead = upsert_crm_lead_by_conversation(
            company_id=access.get("company_id"),
            chatbot_id=chatbot_id,
            conversation_id=conversation_id,
            customer_phone=conversation.get("customer_phone"),
            customer_name=conversation.get("customer_name"),
            source_channel=conversation.get("source_channel"),
            status=status,
            priority=priority,
            assigned_to=data.get("assigned_to"),
            follow_up_date=data.get("follow_up_date"),
            notes=data.get("notes"),
        )

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

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
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
