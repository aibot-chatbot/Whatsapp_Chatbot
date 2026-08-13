import logging

from flask import Blueprint, g, jsonify, request

from app.decorators.auth_decorator import token_required
from app.services.flow_service import get_active_flow, save_flow
from app.utils.access_control import verify_chatbot_access


flow_blueprint = Blueprint("flows", __name__)


@flow_blueprint.route("/api/dashboard/flows", methods=["GET"])
@token_required
def get_bot_flow():
    company_id = getattr(g, "company_id", None)
    chatbot_id = request.args.get("chatbot_id", type=int)

    if not company_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not chatbot_id:
        return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

    try:
        verify_chatbot_access(chatbot_id)
        return jsonify({"status": "success", "data": get_active_flow(company_id, chatbot_id)}), 200
    except PermissionError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 403
    except Exception as exc:
        logging.exception("Failed to fetch flow for chatbot %s: %s", chatbot_id, exc)
        return jsonify({"status": "error", "message": "Failed to fetch flow"}), 500


@flow_blueprint.route("/api/dashboard/flows", methods=["POST"])
@token_required
def save_bot_flow():
    company_id = getattr(g, "company_id", None)
    data = request.get_json() or {}
    chatbot_id = data.get("chatbot_id")
    name = data.get("name", "Untitled Flow")
    flow_data = data.get("flow_data")
    action = request.args.get("action", data.get("action", "draft"))

    if not company_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not chatbot_id or not isinstance(flow_data, dict):
        return jsonify({"status": "error", "message": "Missing chatbot_id or flow_data"}), 400

    try:
        chatbot_id = int(chatbot_id)
        verify_chatbot_access(chatbot_id)
        saved_flow = save_flow(company_id, chatbot_id, name, flow_data, action)
        return jsonify({"status": "success", "data": saved_flow}), 200
    except PermissionError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 403
    except Exception as exc:
        logging.exception("Failed to save flow for chatbot %s: %s", chatbot_id, exc)
        return jsonify({"status": "error", "message": "Failed to save flow"}), 500
