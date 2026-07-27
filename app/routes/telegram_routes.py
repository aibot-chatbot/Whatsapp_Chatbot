import logging
import os
import secrets
import requests

from flask import Blueprint, request, jsonify

from app.decorators.auth_decorator import token_required
from app.services.billing_guard import can_connect_channel, BillingLimitError
from app.utils.access_control import verify_chatbot_access, role_required
from app.database.bot_repository import get_bot_by_id
from app.database.telegram_channel_repository import (
    create_telegram_channel,
    update_telegram_channel,
    get_telegram_channel_by_id,
    get_telegram_channels_by_chatbot,
)
from app.utils.telegram_utils import process_telegram_update


telegram_blueprint = Blueprint("telegram", __name__)


def clean_public_base_url(url: str):
    if not url:
        return ""

    return url.strip().rstrip("/")


def validate_telegram_bot_token(bot_token: str):
    """
    Validate Telegram bot token by calling getMe.
    If valid, Telegram returns bot id and username.
    """
    url = f"https://api.telegram.org/bot{bot_token}/getMe"

    response = requests.get(url, timeout=10)

    if response.status_code != 200:
        return None, f"Telegram getMe failed with status {response.status_code}"

    data = response.json()

    if not data.get("ok"):
        return None, data.get("description", "Invalid Telegram bot token")

    return data.get("result"), None


def set_telegram_webhook(bot_token: str, webhook_url: str):
    """
    Register webhook URL with Telegram.
    Telegram will send future messages to this URL.
    """
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

    response = requests.post(
        url,
        json={
            "url": webhook_url,
            "drop_pending_updates": True,
        },
        timeout=10,
    )

    if response.status_code != 200:
        return False, f"Telegram setWebhook failed with status {response.status_code}: {response.text}"

    data = response.json()

    if not data.get("ok"):
        return False, data.get("description", "Failed to set Telegram webhook")

    return True, None


def delete_telegram_webhook(bot_token: str):
    """
    Remove Telegram webhook.
    This stops Telegram from sending future updates to our backend.
    """
    if not bot_token:
        return False, "Missing Telegram bot token"

    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"

    try:
        response = requests.post(
            url,
            json={"drop_pending_updates": True},
            timeout=10,
        )

        if response.status_code != 200:
            return False, f"Telegram deleteWebhook failed with status {response.status_code}: {response.text}"

        data = response.json()

        if not data.get("ok"):
            return False, data.get("description", "Failed to delete Telegram webhook")

        return True, None

    except Exception as e:
        return False, str(e)


@telegram_blueprint.route("/api/telegram/connect", methods=["POST"])
@token_required
@role_required("admin", "owner")
def connect_telegram():
    """
    Connect a Telegram bot to a chatbot.

    Frontend sends:
    {
        "bot_token": "TOKEN_FROM_BOTFATHER"
    }

    Optional:
    {
        "webhook_base_url": "https://api.example.com"
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
        bot_token = (data.get("bot_token") or "").strip()

        if not bot_token:
            return jsonify({
                "status": "error",
                "message": "Telegram bot token is required"
            }), 400

        bot = get_bot_by_id(chatbot_id, access["company_id"])

        if not bot:
            return jsonify({
                "status": "error",
                "message": "Chatbot not found"
            }), 404

        company_id = bot.get("company_id")

        # Validate token with Telegram
        bot_info, token_error = validate_telegram_bot_token(bot_token)

        if token_error:
            return jsonify({
                "status": "error",
                "message": token_error
            }), 400

        telegram_bot_id = str(bot_info.get("id"))
        bot_username = bot_info.get("username")

        # Use the request value first, then the configured public deployment URL.
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
        webhook_url = f"{public_base_url}/telegram/webhook/{webhook_secret}"

        # Check subscription limit before creating channel
        can_connect_channel(company_id)

        # Save channel first as pending
        channel = create_telegram_channel(
            company_id=company_id,
            chatbot_id=chatbot_id,
            bot_token=bot_token,
            bot_username=bot_username,
            telegram_bot_id=telegram_bot_id,
            webhook_secret=webhook_secret,
            webhook_url=webhook_url,
        )

        if not channel:
            return jsonify({
                "status": "error",
                "message": "Failed to save Telegram channel"
            }), 500

        # Register webhook with Telegram
        webhook_ok, webhook_error = set_telegram_webhook(bot_token, webhook_url)

        if not webhook_ok:
            update_telegram_channel(channel["id"], {
                "connection_status": "failed",
                "last_error": webhook_error,
            })

            return jsonify({
                "status": "error",
                "message": webhook_error
            }), 400

        updated_channel = update_telegram_channel(channel["id"], {
            "connection_status": "connected",
            "last_error": None,
        })

        return jsonify({
            "status": "success",
            "message": "Telegram bot connected successfully",
            "data": {
                "id": updated_channel["id"],
                "chatbot_id": updated_channel["chatbot_id"],
                "bot_username": updated_channel.get("bot_username"),
                "telegram_bot_id": updated_channel.get("telegram_bot_id"),
                "webhook_url": updated_channel.get("webhook_url"),
                "connection_status": updated_channel.get("connection_status"),
                "is_active": updated_channel.get("is_active"),
            }
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
        logging.error(f"Connect Telegram error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@telegram_blueprint.route("/api/telegram/channels", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_telegram_channels():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        channels = get_telegram_channels_by_chatbot(chatbot_id)

        # Never send bot_token back to frontend
        safe_channels = []

        for channel in channels:
            safe_channels.append({
                "id": channel.get("id"),
                "company_id": channel.get("company_id"),
                "chatbot_id": channel.get("chatbot_id"),
                "bot_username": channel.get("bot_username"),
                "telegram_bot_id": channel.get("telegram_bot_id"),
                "webhook_url": channel.get("webhook_url"),
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

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"List Telegram channels error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@telegram_blueprint.route("/api/telegram/channels/<int:channel_id>/disconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def disconnect_telegram_channel(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        channel = get_telegram_channel_by_id(channel_id)

        if not channel:
            return jsonify({
                "status": "error",
                "message": "Telegram channel not found"
            }), 404

        if int(channel.get("chatbot_id")) != int(chatbot_id):
            return jsonify({
                "status": "error",
                "message": "This Telegram channel does not belong to this chatbot"
            }), 403

        webhook_ok, webhook_error = delete_telegram_webhook(channel.get("bot_token"))

        update_data = {
            "is_active": False,
            "connection_status": "disconnected",
            "last_error": None if webhook_ok else webhook_error,
        }

        updated_channel = update_telegram_channel(channel_id, update_data)

        if not updated_channel:
            return jsonify({
                "status": "error",
                "message": "Failed to update Telegram channel"
            }), 500

        return jsonify({
            "status": "success",
            "message": "Telegram channel disconnected successfully",
            "data": {
                "id": updated_channel.get("id"),
                "chatbot_id": updated_channel.get("chatbot_id"),
                "bot_username": updated_channel.get("bot_username"),
                "telegram_bot_id": updated_channel.get("telegram_bot_id"),
                "connection_status": updated_channel.get("connection_status"),
                "is_active": updated_channel.get("is_active"),
                "last_error": updated_channel.get("last_error"),
            }
        }), 200

    except Exception as e:
        logging.error(f"Disconnect Telegram channel error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@telegram_blueprint.route("/api/telegram/channels/<int:channel_id>/reconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def reconnect_telegram_channel(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        channel = get_telegram_channel_by_id(channel_id)

        if not channel:
            return jsonify({
                "status": "error",
                "message": "Telegram channel not found"
            }), 404

        if int(channel.get("chatbot_id")) != int(chatbot_id):
            return jsonify({
                "status": "error",
                "message": "This Telegram channel does not belong to this chatbot"
            }), 403

        bot_token = channel.get("bot_token")

        if not bot_token:
            return jsonify({
                "status": "error",
                "message": "Saved Telegram bot token is missing. Please replace token and connect again."
            }), 400

        bot_info, token_error = validate_telegram_bot_token(bot_token)

        if token_error:
            update_telegram_channel(channel_id, {
                "connection_status": "failed",
                "last_error": token_error,
                "is_active": False,
            })

            return jsonify({
                "status": "error",
                "message": token_error
            }), 400

        public_base_url = clean_public_base_url(
            os.getenv("PUBLIC_BASE_URL")
        )

        if not public_base_url:
            return jsonify({
                "status": "error",
                "message": "PUBLIC_BASE_URL is missing. Configure a deployed public HTTPS server URL."
            }), 400

        webhook_secret = secrets.token_urlsafe(32)
        webhook_url = f"{public_base_url}/telegram/webhook/{webhook_secret}"

        webhook_ok, webhook_error = set_telegram_webhook(bot_token, webhook_url)

        if not webhook_ok:
            update_telegram_channel(channel_id, {
                "connection_status": "failed",
                "last_error": webhook_error,
                "is_active": False,
            })

            return jsonify({
                "status": "error",
                "message": webhook_error
            }), 400

        updated_channel = update_telegram_channel(channel_id, {
            "telegram_bot_id": str(bot_info.get("id")),
            "bot_username": bot_info.get("username"),
            "webhook_secret": webhook_secret,
            "webhook_url": webhook_url,
            "connection_status": "connected",
            "last_error": None,
            "is_active": True,
        })

        if not updated_channel:
            return jsonify({
                "status": "error",
                "message": "Failed to update Telegram channel"
            }), 500

        return jsonify({
            "status": "success",
            "message": "Telegram channel reconnected successfully",
            "data": {
                "id": updated_channel.get("id"),
                "chatbot_id": updated_channel.get("chatbot_id"),
                "bot_username": updated_channel.get("bot_username"),
                "telegram_bot_id": updated_channel.get("telegram_bot_id"),
                "webhook_url": updated_channel.get("webhook_url"),
                "connection_status": updated_channel.get("connection_status"),
                "is_active": updated_channel.get("is_active"),
                "last_error": updated_channel.get("last_error"),
            }
        }), 200

    except Exception as e:
        logging.error(f"Reconnect Telegram channel error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@telegram_blueprint.route("/telegram/webhook/<webhook_secret>", methods=["GET"])
def telegram_webhook_health(webhook_secret):
    return jsonify({
        "status": "ok",
        "message": "Telegram webhook endpoint is active"
    }), 200


@telegram_blueprint.route("/telegram/webhook/<webhook_secret>", methods=["POST"])
def telegram_webhook_post(webhook_secret):
    try:
        update = request.get_json(silent=True) or {}
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}

        logging.info(f"Telegram webhook received for secret: {webhook_secret}")
        logging.info(
            "Telegram update summary: update_id=%s message_id=%s chat_id=%s "
            "from_user_id=%s has_contact=%s has_text=%s",
            update.get("update_id"),
            message.get("message_id"),
            chat.get("id"),
            from_user.get("id"),
            bool(message.get("contact")),
            bool(message.get("text")),
        )

        process_telegram_update(update, webhook_secret)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logging.error(f"Telegram webhook error: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal Telegram webhook error"
        }), 500
