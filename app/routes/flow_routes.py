import logging
from flask import Blueprint, jsonify, request, g
from app.decorators.auth_decorator import token_required
from app.services.flow_service import save_flow, get_active_flow

flow_blueprint = Blueprint("flows", __name__)

@flow_blueprint.route("/api/dashboard/flows", methods=["GET"])
@token_required
def get_bot_flow():
    company_id = getattr(g, "company_id", None)
    if not company_id:
        return jsonify({"error": "Unauthorized"}), 401

    chatbot_id = request.args.get("chatbot_id")
    if not chatbot_id:
        return jsonify({"error": "chatbot_id is required"}), 400

    try:
        flow = get_active_flow(company_id, int(chatbot_id))
        if flow:
            return jsonify({"status": "success", "data": flow}), 200
        return jsonify({"status": "success", "data": None}), 200
    except Exception as e:
        logging.error(f"Error fetching flow: {e}")
        return jsonify({"error": "Failed to fetch flow"}), 500


@flow_blueprint.route("/api/dashboard/flows", methods=["POST"])
@token_required
def save_bot_flow():
    company_id = getattr(g, "company_id", None)
    if not company_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    chatbot_id = data.get("chatbot_id")
    name = data.get("name", "Untitled Flow")
    flow_data = data.get("flow_data")
    action = request.args.get("action", "draft")

    if not chatbot_id or not flow_data:
        return jsonify({"status": "error", "message": "Missing chatbot_id or flow_data"}), 400

    try:
        saved_flow = save_flow(company_id, int(chatbot_id), name, flow_data, action)
        return jsonify({"status": "success", "data": saved_flow}), 200
    except Exception as e:
        logging.error(f"Error saving flow: {e}")
        return jsonify({"error": "Failed to save flow"}), 500
