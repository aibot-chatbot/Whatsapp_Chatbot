import hmac
import hashlib
import logging
import os
import re
import secrets
import time
import requests

from flask import Blueprint, request, jsonify

from app.decorators.auth_decorator import token_required
from app.services.billing_guard import can_connect_channel, BillingLimitError
from app.services.company_status_service import company_operational_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.database.bot_repository import get_bot_by_id
from app.database.telegram_channel_repository import (
    create_telegram_channel,
    update_telegram_channel,
    get_telegram_channel_by_id,
    get_telegram_channels_by_chatbot,
)
from app.utils.telegram_utils import process_telegram_update
from app.utils.api_errors import server_error


telegram_blueprint = Blueprint("telegram", __name__)


def clean_public_base_url(url: str):
    if not url:
        return ""

    return url.strip().rstrip("/")


def _counts_towards_channel_limit(channel):
    """Mirror of count_company_channels' filter, for one row."""
    return (
        bool(channel.get("is_active"))
        and str(channel.get("connection_status") or "").lower() == "connected"
    )


def _safe_telegram_error_description(description, fallback):
    # Preserve known diagnostics; unknown provider text can contain credentials.
    if description == "Unauthorized":
        return "Unauthorized"
    return fallback


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
        return None, _safe_telegram_error_description(
            data.get("description"), "Invalid Telegram bot token"
        )

    return data.get("result"), None


def set_telegram_webhook(bot_token: str, webhook_url: str, secret_token: str = None):
    """
    Register webhook URL with Telegram.
    Telegram will send future messages to this URL.

    `secret_token` is echoed back by Telegram in the
    X-Telegram-Bot-Api-Secret-Token header on every delivery, so the receiving
    route can tell a real Telegram call from anyone who learned the URL.
    """
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

    payload = {
        "url": webhook_url,
        "drop_pending_updates": True,
    }

    if secret_token:
        payload["secret_token"] = secret_token

    response = requests.post(
        url,
        json=payload,
        timeout=10,
    )

    if response.status_code != 200:
        return False, f"Telegram setWebhook failed with status {response.status_code}"

    data = response.json()

    if not data.get("ok"):
        return False, _safe_telegram_error_description(
            data.get("description"), "Failed to set Telegram webhook"
        )

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
            return False, f"Telegram deleteWebhook failed with status {response.status_code}"

        data = response.json()

        if not data.get("ok"):
            return False, _safe_telegram_error_description(
                data.get("description"), "Failed to delete Telegram webhook"
            )

        return True, None

    except Exception:
        # requests puts the full request URL into its exception text and that URL
        # carries the bot token, so the exception itself must never be returned:
        # this string is stored in last_error and shown to the user.
        logging.warning("Telegram deleteWebhook call failed", exc_info=False)
        return False, "Could not reach Telegram to remove the webhook"


# Telegram's own last_error_message can contain credential-bearing URLs.
# Logs and customer responses use these static descriptions instead.
DELIVERY_UNREACHABLE_MESSAGE = (
    "Telegram cannot reach your server right now. Your bot will answer as soon "
    "as the server is reachable again."
)
DELIVERY_CERTIFICATE_MESSAGE = (
    "Your server's security certificate is not valid, so Telegram will not send "
    "messages to it."
)
DELIVERY_GENERIC_MESSAGE = "Telegram could not deliver messages to your server."
DELIVERY_WRONG_SERVER_MESSAGE = (
    "This Telegram bot delivers messages to a different server, so it cannot "
    "answer here. Disconnect it there, then connect it again."
)
DELIVERY_OK_MESSAGE = "Telegram is delivering messages to your server."
DELIVERY_UNKNOWN_MESSAGE = (
    "We could not check with Telegram just now. Try again in a moment."
)

DELIVERY_STATUS_OK = "connected"
DELIVERY_STATUS_FAILED = "failed"
DELIVERY_STATUS_UNKNOWN = "unknown"

_CERTIFICATE_ERROR_MARKERS = ("ssl", "certificate", "tls")
_UNREACHABLE_ERROR_MARKERS = (
    "404",
    "502",
    "503",
    "unreachable",
    "connection refused",
    "connection reset",
    "timeout",
    "timed out",
    "getaddrinfo",
    "failed to resolve",
    "name or service not known",
)


def describe_telegram_delivery_error(raw_error: str) -> str:
    """Translate Telegram's raw delivery error into wording a customer can act on."""
    text = raw_error.lower() if isinstance(raw_error, str) else ""

    if any(marker in text for marker in _CERTIFICATE_ERROR_MARKERS):
        return DELIVERY_CERTIFICATE_MESSAGE

    if any(marker in text for marker in _UNREACHABLE_ERROR_MARKERS):
        return DELIVERY_UNREACHABLE_MESSAGE

    return DELIVERY_GENERIC_MESSAGE


def _safe_stored_telegram_error(error):
    """Project historical errors without exposing provider bodies or changing rows."""
    if not error:
        return None
    if isinstance(error, str):
        if error in {
            "Unauthorized",
            "Invalid Telegram bot token",
            "Missing Telegram bot token",
            "Failed to set Telegram webhook",
            "Failed to delete Telegram webhook",
            "Failed to read Telegram webhook info",
            "Could not reach Telegram to remove the webhook",
            "Could not reach Telegram to read the webhook status",
            "Telegram getWebhookInfo returned an unreadable response",
            DELIVERY_UNREACHABLE_MESSAGE,
            DELIVERY_CERTIFICATE_MESSAGE,
            DELIVERY_GENERIC_MESSAGE,
            DELIVERY_WRONG_SERVER_MESSAGE,
            DELIVERY_OK_MESSAGE,
            DELIVERY_UNKNOWN_MESSAGE,
        } or re.fullmatch(
            r"Telegram (?:getMe|setWebhook|deleteWebhook|getWebhookInfo) failed with status [1-5][0-9]{2}",
            error,
        ):
            return error
    return describe_telegram_delivery_error(error)


def get_telegram_webhook_info(bot_token: str) -> tuple[dict | None, str | None]:
    """Read Telegram's own report about the webhook registered for this bot.

    setWebhook only records a URL string, Telegram never contacts it, so its
    "ok" proves nothing about delivery. getWebhookInfo carries url,
    pending_update_count, last_error_date and last_error_message, which is the
    only evidence available that deliveries actually arrive.
    """
    if not bot_token:
        return None, "Missing Telegram bot token"

    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"

    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException:
        # The exception text embeds the request URL, which carries the token.
        return None, "Could not reach Telegram to read the webhook status"

    if response.status_code != 200:
        return None, f"Telegram getWebhookInfo failed with status {response.status_code}"

    try:
        data = response.json()
    except ValueError:
        return None, "Telegram getWebhookInfo returned an unreadable response"

    if not data.get("ok"):
        return None, _safe_telegram_error_description(
            data.get("description"), "Failed to read Telegram webhook info"
        )

    return data.get("result") or {}, None


def check_telegram_webhook_delivery(
    bot_token: str,
    expected_url: str,
    registered_since: int | None = None,
) -> tuple[str, str | None, dict]:
    """Decide whether Telegram can actually deliver to the webhook we registered.

    Returns (delivery_status, customer_facing_reason, raw_info). `registered_since`
    is the unix time our registration was sent: an older error belongs to a URL we
    have already replaced and must not condemn the new one.
    """
    info, read_error = get_telegram_webhook_info(bot_token)

    if read_error:
        # Failing to read the report is our blind spot, not proof that delivery
        # is broken, so a working channel is never flipped to failed for it.
        logging.warning("Telegram getWebhookInfo unavailable: %s", _safe_stored_telegram_error(read_error))
        return DELIVERY_STATUS_UNKNOWN, None, {}

    if expected_url and (info.get("url") or "") != expected_url:
        # The bot is pointed somewhere else, so nothing will ever reach us.
        # The URL itself is never logged: it carries the webhook secret.
        logging.warning("Telegram webhook for this bot is registered to another URL")
        return DELIVERY_STATUS_FAILED, DELIVERY_WRONG_SERVER_MESSAGE, info

    last_error_message = info.get("last_error_message")

    try:
        last_error_date = int(info.get("last_error_date") or 0)
    except (TypeError, ValueError):
        last_error_date = 0

    if last_error_message and (
        registered_since is None or last_error_date >= registered_since
    ):
        safe_reason = describe_telegram_delivery_error(last_error_message)
        logging.warning(
            "Telegram reports a webhook delivery failure: %s", safe_reason
        )
        return (
            DELIVERY_STATUS_FAILED,
            safe_reason,
            info,
        )

    return DELIVERY_STATUS_OK, None, info


@telegram_blueprint.route("/api/telegram/connect", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
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
        registered_at = int(time.time())

        webhook_ok, webhook_error = set_telegram_webhook(
            bot_token, webhook_url, secret_token=webhook_secret
        )

        if not webhook_ok:
            update_telegram_channel(channel["id"], {
                "connection_status": "failed",
                "last_error": webhook_error,
            })

            return jsonify({
                "status": "error",
                "message": webhook_error
            }), 400

        # setWebhook stores a URL string and nothing else, so it stays "ok" for a
        # server Telegram can never reach. Ask Telegram what it sees before
        # telling the user the bot is live.
        delivery_status, delivery_reason, _ = check_telegram_webhook_delivery(
            bot_token, webhook_url, registered_since=registered_at
        )

        if delivery_status == DELIVERY_STATUS_FAILED:
            # The row and the saved token stay exactly as they are: the server
            # can come back, and the user must be able to retry without pasting
            # the token from BotFather again.
            update_telegram_channel(channel["id"], {
                "connection_status": "failed",
                "last_error": delivery_reason,
            })

            return jsonify({
                "status": "error",
                "code": "webhook_not_delivering",
                "message": delivery_reason
            }), 502

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
        return server_error("connect_telegram", e)


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
                "last_error": _safe_stored_telegram_error(channel.get("last_error")),
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
        return server_error("list_telegram_channels", e)


@telegram_blueprint.route("/api/telegram/channels/<int:channel_id>/disconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
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
                "last_error": _safe_stored_telegram_error(updated_channel.get("last_error")),
            }
        }), 200

    except Exception as e:
        logging.error(f"Disconnect Telegram channel error: {e}")
        return server_error("disconnect_telegram_channel", e)


@telegram_blueprint.route("/api/telegram/channels/<int:channel_id>/reconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
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

        # Reconnect flips is_active and connection_status back on, and those are
        # the two columns count_company_channels counts. A channel that is not
        # currently counted is therefore about to consume a slot, so it has to
        # pass the same limit check that connect does. A channel that is already
        # live is not re-checked, otherwise a company at its limit could never
        # repair a channel it already owns.
        if not _counts_towards_channel_limit(channel):
            can_connect_channel(channel.get("company_id"))

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

        registered_at = int(time.time())

        webhook_ok, webhook_error = set_telegram_webhook(
            bot_token, webhook_url, secret_token=webhook_secret
        )

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

        delivery_status, delivery_reason, _ = check_telegram_webhook_delivery(
            bot_token, webhook_url, registered_since=registered_at
        )

        if delivery_status == DELIVERY_STATUS_FAILED:
            # Telegram now holds this secret, so the row has to hold it too. If
            # the row kept the previous one, a delivery that succeeds after the
            # server recovers would arrive with a secret nothing resolves and the
            # bot would be silently dead again. is_active stays True for the same
            # reason: get_telegram_channel_by_secret filters on it. A failed
            # channel still does not count towards the plan channel limit.
            update_telegram_channel(channel_id, {
                "telegram_bot_id": str(bot_info.get("id")),
                "bot_username": bot_info.get("username"),
                "webhook_secret": webhook_secret,
                "webhook_url": webhook_url,
                "connection_status": "failed",
                "last_error": delivery_reason,
                "is_active": True,
            })

            return jsonify({
                "status": "error",
                "code": "webhook_not_delivering",
                "message": delivery_reason
            }), 502

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
                "last_error": _safe_stored_telegram_error(updated_channel.get("last_error")),
            }
        }), 200

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except Exception as e:
        return server_error("reconnect_telegram_channel", e)


@telegram_blueprint.route("/api/telegram/channels/<int:channel_id>/delivery", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_telegram_channel_delivery(channel_id):
    """Live delivery state for one channel.

    connection_status is only as fresh as the last write, so a bot that died
    after it was connected still reads "connected" there. This asks Telegram
    instead, so the publish screen can show what is really happening.
    """
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

        delivery_status, delivery_reason, info = check_telegram_webhook_delivery(
            channel.get("bot_token"),
            channel.get("webhook_url"),
        )

        if delivery_status == DELIVERY_STATUS_OK:
            message = DELIVERY_OK_MESSAGE
        elif delivery_status == DELIVERY_STATUS_UNKNOWN:
            message = DELIVERY_UNKNOWN_MESSAGE
        else:
            message = delivery_reason

        pending_count = info.get("pending_update_count")
        if type(pending_count) is not int or pending_count < 0:
            pending_count = None

        # Never echo bot_token, webhook_secret, or webhook_url: the URL carries
        # the webhook secret in its path. Only validated counts leave info.
        return jsonify({
            "status": "success",
            "data": {
                "id": channel.get("id"),
                "chatbot_id": channel.get("chatbot_id"),
                "bot_username": channel.get("bot_username"),
                "connection_status": channel.get("connection_status"),
                "is_active": channel.get("is_active"),
                "delivery_status": delivery_status,
                "is_delivering": delivery_status == DELIVERY_STATUS_OK,
                "message": message,
                "pending_update_count": pending_count,
                "webhook_url_matches": bool(
                    info.get("url")
                    and info.get("url") == channel.get("webhook_url")
                ),
            }
        }), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Telegram channel delivery check error: {e}")
        return server_error("get_telegram_channel_delivery", e)


@telegram_blueprint.route("/telegram/webhook/<webhook_secret>", methods=["GET"])
def telegram_webhook_health(webhook_secret):
    return jsonify({
        "status": "ok",
        "message": "Telegram webhook endpoint is active"
    }), 200


@telegram_blueprint.route("/telegram/webhook/<webhook_secret>", methods=["POST"])
def telegram_webhook_post(webhook_secret):
    try:
        # Telegram echoes the secret_token we registered. Channels connected
        # before secret_token was sent do not carry the header at all, so an
        # absent header is accepted and logged rather than rejected -- breaking
        # every live bot to add a second lock is not worth it. The 256-bit path
        # secret is still the primary gate; this rejects a caller who learned
        # the URL but guessed the header wrong.
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

        if header_secret is None:
            logging.warning(
                "Telegram webhook delivered without a secret token header. "
                "Reconnect this channel to register one."
            )
        elif not hmac.compare_digest(
            header_secret.encode("utf-8", "replace"),
            webhook_secret.encode("utf-8", "replace"),
        ):
            logging.warning("Telegram webhook rejected: secret token mismatch")
            return jsonify({
                "status": "error",
                "message": "Invalid secret token"
            }), 403

        update = request.get_json(silent=True) or {}
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}

        # Fingerprint, never the secret itself: this path segment is the
        # primary authentication factor for the channel, and this file
        # already refuses to log the webhook URL for exactly that reason.
        logging.info(
            "Telegram webhook received for channel %s",
            hashlib.sha256(webhook_secret.encode()).hexdigest()[:12],
        )
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
        logging.error("Telegram webhook error (%s)", type(e).__name__)
        return jsonify({
            "status": "error",
            "message": "Internal Telegram webhook error"
        }), 500
