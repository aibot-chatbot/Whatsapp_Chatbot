import hashlib
import logging
import os
import secrets

from flask import Blueprint, request, jsonify

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import can_connect_channel, BillingLimitError
from app.services.company_status_service import company_operational_required
from app.database.bot_repository import get_bot_by_id
from app.database.wasender_channel_repository import (
    create_wasender_channel,
    get_wasender_channel_by_id,
    get_wasender_channels_by_chatbot,
    update_wasender_channel,
    disconnect_wasender_channel,
)
from app.services.wasender_service import process_wasender_webhook
from app.utils.api_errors import server_error


wasender_blueprint = Blueprint("wasender", __name__)


def clean_public_base_url(url: str):
    if not url:
        return ""

    return url.strip().rstrip("/")


def safe_wasender_channel(channel: dict):
    """
    Never send api_key back to frontend.
    """
    if not channel:
        return None

    return {
        "id": channel.get("id"),
        "company_id": channel.get("company_id"),
        "chatbot_id": channel.get("chatbot_id"),
        "session_id": channel.get("session_id"),
        "session_name": channel.get("session_name"),
        "phone_number": channel.get("phone_number"),
        "webhook_url": channel.get("webhook_url"),
        "connection_status": channel.get("connection_status"),
        "last_error": channel.get("last_error"),
        "is_active": channel.get("is_active"),
        "created_at": channel.get("created_at"),
        "updated_at": channel.get("updated_at"),
    }


@wasender_blueprint.route("/api/wasender/connect", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def connect_wasender():
    """
    Save WasenderAPI channel details for a chatbot.

    Frontend sends:
    {
        "api_key": "WASENDER_API_KEY",
        "phone_number": "+60123456789",
        "session_id": "optional",
        "session_name": "optional",
        "webhook_base_url": "optional public deployment URL"
    }
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        access = verify_chatbot_access(chatbot_id)

        data = request.get_json() or {}

        api_key = (data.get("api_key") or "").strip()
        phone_number = (data.get("phone_number") or "").strip()
        session_id = (data.get("session_id") or "").strip() or None
        session_name = (data.get("session_name") or "").strip() or None

        if not api_key:
            return jsonify({
                "status": "error",
                "message": "WasenderAPI key is required."
            }), 400

        if not phone_number:
            return jsonify({
                "status": "error",
                "message": "Phone number is required."
            }), 400

        bot = get_bot_by_id(chatbot_id, access["company_id"])

        if not bot:
            return jsonify({
                "status": "error",
                "message": "Chatbot not found."
            }), 404

        company_id = bot.get("company_id")

        public_base_url = clean_public_base_url(
            data.get("webhook_base_url")
            or os.getenv("PUBLIC_BASE_URL")
        )

        if not public_base_url:
            return jsonify({
                "status": "error",
                "message": "PUBLIC_BASE_URL is missing. Configure a deployed public HTTPS server URL."
            }), 400

        webhook_secret = secrets.token_urlsafe(32)
        webhook_url = f"{public_base_url}/wasender/webhook/{webhook_secret}"

        # Check subscription limit before creating channel
        can_connect_channel(company_id)

        channel = create_wasender_channel(
            company_id=company_id,
            chatbot_id=chatbot_id,
            api_key=api_key,
            phone_number=phone_number,
            session_id=session_id,
            session_name=session_name,
            webhook_secret=webhook_secret,
            webhook_url=webhook_url,
        )

        if not channel:
            return jsonify({
                "status": "error",
                "message": "Failed to save WasenderAPI channel."
            }), 500

        updated_channel = update_wasender_channel(channel["id"], {
            "connection_status": "connected",
            "last_error": None,
            "is_active": True,
        })

        return jsonify({
            "status": "success",
            "message": "WasenderAPI channel saved successfully. Copy the webhook URL into your WasenderAPI session settings.",
            "data": safe_wasender_channel(updated_channel or channel)
        }), 200

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Connect Wasender error: {e}")
        return server_error("connect_wasender", e)


@wasender_blueprint.route("/api/wasender/channels", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_wasender_channels():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        channels = get_wasender_channels_by_chatbot(chatbot_id)

        safe_channels = [safe_wasender_channel(channel) for channel in channels]

        return jsonify({
            "status": "success",
            "data": safe_channels
        }), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"List Wasender channels error: {e}")
        return server_error("list_wasender_channels", e)


@wasender_blueprint.route("/api/wasender/channels/<int:channel_id>/disconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def disconnect_wasender(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        channel = get_wasender_channel_by_id(channel_id)

        if not channel:
            return jsonify({
                "status": "error",
                "message": "WasenderAPI channel not found."
            }), 404

        if int(channel.get("chatbot_id")) != int(chatbot_id):
            return jsonify({
                "status": "error",
                "message": "This WasenderAPI channel does not belong to this chatbot."
            }), 403

        updated_channel = disconnect_wasender_channel(channel_id)

        if not updated_channel:
            return jsonify({
                "status": "error",
                "message": "Failed to disconnect WasenderAPI channel."
            }), 500

        return jsonify({
            "status": "success",
            "message": "WasenderAPI channel disconnected successfully.",
            "data": safe_wasender_channel(updated_channel)
        }), 200

    except Exception as e:
        logging.error(f"Disconnect Wasender error: {e}")
        return server_error("disconnect_wasender", e)


@wasender_blueprint.route("/wasender/webhook/<webhook_secret>", methods=["GET"])
def wasender_webhook_health(webhook_secret):
    return jsonify({
        "status": "ok",
        "message": "WasenderAPI webhook endpoint is active."
    }), 200


@wasender_blueprint.route("/wasender/webhook/<webhook_secret>", methods=["POST"])
def wasender_webhook_post(webhook_secret):
    try:
        payload = request.get_json(silent=True) or {}

        # Fingerprint, never the secret itself - for Wasender the path
        # secret is the ONLY authentication factor (no signature header).
        logging.info(
            "Wasender webhook received for channel %s",
            hashlib.sha256(webhook_secret.encode()).hexdigest()[:12],
        )
        # Keys only, never values: the payload carries the customer's message
        # text and phone number. The channel fingerprint above already
        # identifies which tenant this belongs to.
        logging.info("Wasender payload keys: %s", sorted(payload)[:10])

        process_wasender_webhook(payload, webhook_secret)

        return jsonify({
            "status": "ok"
        }), 200

    except Exception as e:
        logging.error(f"Wasender webhook error: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal Wasender webhook error."
        }), 500
