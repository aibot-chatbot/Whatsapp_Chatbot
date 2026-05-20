import logging
from flask import Blueprint, request, jsonify

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access
from app.database.whatsapp_channel_repository import (
    get_whatsapp_channels_by_chatbot,
    get_whatsapp_channel_by_id,
    update_whatsapp_channel,
)

whatsapp_blueprint = Blueprint("whatsapp", __name__)


@whatsapp_blueprint.route("/api/whatsapp/channels", methods=["GET"])
@token_required
def list_whatsapp_channels():
    try:
        chatbot_id = request.args.get("chatbot_id", 1, type=int)
        verify_chatbot_access(chatbot_id)

        channels = get_whatsapp_channels_by_chatbot(chatbot_id)

        safe_channels = []

        for channel in channels:
            safe_channels.append({
                "id": channel.get("id"),
                "company_id": channel.get("company_id"),
                "chatbot_id": channel.get("chatbot_id"),
                "phone_number_id": channel.get("phone_number_id"),
                "display_phone_number": channel.get("display_phone_number"),
                "whatsapp_business_account_id": channel.get("whatsapp_business_account_id"),
                "connection_status": channel.get("connection_status"),
                "last_error": channel.get("last_error"),
                "is_active": channel.get("is_active"),
                "created_at": channel.get("created_at"),
                "updated_at": channel.get("updated_at"),
            })

        return jsonify({
            "status": "success",
            "data": safe_channels
        }), 200

    except Exception as e:
        logging.error(f"List WhatsApp channels error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@whatsapp_blueprint.route("/api/whatsapp/channels/<int:channel_id>/disconnect", methods=["PUT"])
@token_required
def disconnect_whatsapp_channel(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", 1, type=int)
        verify_chatbot_access(chatbot_id)

        channel = get_whatsapp_channel_by_id(channel_id)

        if not channel:
            return jsonify({
                "status": "error",
                "message": "WhatsApp channel not found"
            }), 404

        if int(channel.get("chatbot_id")) != int(chatbot_id):
            return jsonify({
                "status": "error",
                "message": "This WhatsApp channel does not belong to this chatbot"
            }), 403

        updated_channel = update_whatsapp_channel(channel_id, {
            "is_active": False,
            "connection_status": "disconnected",
            "last_error": None,
        })

        if not updated_channel:
            return jsonify({
                "status": "error",
                "message": "Failed to update WhatsApp channel"
            }), 500

        return jsonify({
            "status": "success",
            "message": "WhatsApp channel disconnected successfully",
            "data": {
                "id": updated_channel.get("id"),
                "chatbot_id": updated_channel.get("chatbot_id"),
                "phone_number_id": updated_channel.get("phone_number_id"),
                "display_phone_number": updated_channel.get("display_phone_number"),
                "whatsapp_business_account_id": updated_channel.get("whatsapp_business_account_id"),
                "connection_status": updated_channel.get("connection_status"),
                "is_active": updated_channel.get("is_active"),
                "last_error": updated_channel.get("last_error"),
            }
        }), 200

    except Exception as e:
        logging.error(f"Disconnect WhatsApp channel error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500