import logging
from flask import Blueprint, request, jsonify
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.database.whatsapp_channel_repository import get_whatsapp_channels_by_chatbot
from app.services.meta_template_service import get_meta_templates, create_meta_template, delete_meta_template

meta_template_blueprint = Blueprint("meta_templates", __name__)

def _get_active_meta_channel(chatbot_id):
    channels = get_whatsapp_channels_by_chatbot(chatbot_id)
    for channel in channels:
        if channel.get("is_active") and channel.get("whatsapp_business_account_id") and channel.get("access_token"):
            return channel
    return None

@meta_template_blueprint.route("/api/meta-templates", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_meta_templates():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        channel = _get_active_meta_channel(chatbot_id)
        if not channel:
            return jsonify({"status": "error", "message": "No active Meta WhatsApp integration found for this bot."}), 400
            
        waba_id = channel.get("whatsapp_business_account_id") or channel.get("waba_id")
        access_token = channel.get("access_token")
        
        templates = get_meta_templates(waba_id, access_token)
        
        return jsonify({
            "status": "success",
            "data": templates
        }), 200

    except Exception as e:
        logging.error(f"List meta templates error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@meta_template_blueprint.route("/api/meta-templates", methods=["POST"])
@token_required
@role_required("admin", "owner")
def add_meta_template():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        channel = _get_active_meta_channel(chatbot_id)
        if not channel:
            return jsonify({"status": "error", "message": "No active Meta WhatsApp integration found for this bot."}), 400
            
        waba_id = channel.get("whatsapp_business_account_id") or channel.get("waba_id")
        access_token = channel.get("access_token")
        
        data = request.get_json() or {}
        name = data.get("name")
        language = data.get("language", "en_US")
        category = data.get("category", "MARKETING")
        components = data.get("components", [])
        
        if not name:
            return jsonify({"status": "error", "message": "Template name is required"}), 400
            
        response_data = create_meta_template(waba_id, access_token, name, language, category, components)
        
        return jsonify({
            "status": "success",
            "message": "Template submitted to Meta successfully",
            "data": response_data
        }), 201

    except Exception as e:
        logging.error(f"Create meta template error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@meta_template_blueprint.route("/api/meta-templates/<template_name>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def remove_meta_template(template_name):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        channel = _get_active_meta_channel(chatbot_id)
        if not channel:
            return jsonify({"status": "error", "message": "No active Meta WhatsApp integration found for this bot."}), 400
            
        waba_id = channel.get("whatsapp_business_account_id") or channel.get("waba_id")
        access_token = channel.get("access_token")
        
        delete_meta_template(waba_id, access_token, template_name)
        
        return jsonify({
            "status": "success",
            "message": "Template deleted successfully from Meta"
        }), 200

    except Exception as e:
        logging.error(f"Delete meta template error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
