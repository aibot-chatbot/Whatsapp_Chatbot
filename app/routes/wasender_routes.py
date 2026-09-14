import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone

import requests

from flask import Blueprint, request, jsonify

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import BillingLimitError
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
from app.database.channel_lifecycle_repository import (
    activate_channel, ensure_channel_slot, ChannelActivationError,
)
from app.services.provider_connection_verification import (
    normalize_phone_number, verify_wasender_connection,
)
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
        "connection_attempted_at": channel.get("connection_attempted_at"),
        "verified_at": channel.get("verified_at"),
    }


def _wasender_failure(channel, message, status=400, code="provider_verification_failed"):
    if channel:
        changes = {"last_error": message}
        if channel.get("connection_status") != "connected":
            changes.update(connection_status="failed", is_active=False, verified_at=None)
        updated = update_wasender_channel(channel["id"], changes,
                                          expected_attempt_at=channel.get("connection_attempted_at"),
                                          expected_status="connected" if channel.get("connection_status") == "connected" else "pending")
        if not updated:
            try:
                current = get_wasender_channel_by_id(channel["id"])
            except Exception:
                return jsonify({"status": "error", "code": "activation_state_unknown",
                                "message": "Connection status is unavailable. Refresh before retrying."}), 503
            if (current and current.get("connection_status") == "connected" and current.get("is_active")
                    and all(str(current.get(key)) == str(channel.get(key))
                            for key in ("company_id", "chatbot_id", "connection_attempted_at"))):
                return jsonify({"status": "error", "code": "activation_state_unknown",
                                "message": "The connection is saved as active. Refresh status before retrying.",
                                "data": safe_wasender_channel(current)}), 503
            return jsonify({"status": "error", "code": "connection_superseded",
                            "message": "A newer connection attempt has replaced this attempt."}), 409
        channel = updated
    return jsonify({"status": "error", "code": code, "message": message,
                    "data": safe_wasender_channel(channel)}), status


def _verify_wasender_candidate(channel, personal_access_token, chatbot_id, company_id):
    verification = verify_wasender_connection(channel, personal_access_token)
    changes = {"last_error": None}
    if verification.get("provider_user_id"):
        changes["provider_user_id"] = verification["provider_user_id"]
    if verification["verified"]:
        changes["verified_at"] = datetime.now(timezone.utc).isoformat()
    updated = update_wasender_channel(channel["id"], changes,
                                      expected_attempt_at=channel.get("connection_attempted_at"))
    if not updated:
        return _wasender_failure(None, "A newer connection attempt has replaced this attempt.", 409,
                                 "connection_superseded")
    if verification["verified"] and (channel.get("connection_status") != "connected" or not channel.get("is_active")):
        active = activate_channel("wasender", channel["id"], chatbot_id, company_id,
                                  expected_attempt_at=channel.get("connection_attempted_at"))
        if not active:
            return _wasender_failure(channel, "A newer connection attempt has replaced this attempt.", 409,
                                     "connection_superseded")
        updated = active
    return jsonify({"status": "success" if verification["verified"] else "pending",
                    "message": verification["message"], "data": safe_wasender_channel(updated),
                    "next_action": verification["next_action"],
                    "setup_link": "https://wasenderapi.com/dashboard" if not verification["verified"] else None}), (
                        200 if verification["verified"] else 202)


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
        "session_name": "optional"
    }

    The callback destination is taken from PUBLIC_BASE_URL on the server and is
    deliberately not accepted from the request.
    """
    channel = None
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
        session_id = str(data.get("session_id") or "").strip() or None
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
        phone_number = normalize_phone_number(phone_number)
        if session_id and not session_id.isdigit():
            return _wasender_failure(None, "WasenderAPI session ID must be numeric.")

        bot = get_bot_by_id(chatbot_id, access["company_id"])

        if not bot:
            return jsonify({
                "status": "error",
                "message": "Chatbot not found."
            }), 404

        company_id = bot.get("company_id")

        public_base_url = clean_public_base_url(os.getenv("PUBLIC_BASE_URL"))

        if not public_base_url:
            return jsonify({
                "status": "error",
                "message": "PUBLIC_BASE_URL is missing. Configure a deployed public HTTPS server URL."
            }), 400

        webhook_secret = secrets.token_urlsafe(32)
        webhook_url = f"{public_base_url}/wasender/webhook/{webhook_secret}"

        # Check subscription limit before creating channel
        ensure_channel_slot("wasender", chatbot_id, company_id)

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

        return _verify_wasender_candidate(channel, data.get("personal_access_token"), chatbot_id, company_id)

    except requests.RequestException:
        return _wasender_failure(channel, "Unable to verify WasenderAPI. The previous connection is unchanged.", 502)
    except ChannelActivationError as e:
        return _wasender_failure(channel, str(e), 409, e.code)
    except ValueError as e:
        return _wasender_failure(channel, str(e))

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        if getattr(e, "code", None) == "23505":
            return _wasender_failure(channel, "This WasenderAPI number is already assigned to an active connection.", 409,
                                     "provider_identity_in_use")
        return server_error("connect_wasender", e)


@wasender_blueprint.route("/api/wasender/channels/<int:channel_id>/reconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def reconnect_wasender(channel_id):
    channel = None
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _wasender_failure(None, "chatbot_id is required")
        access = verify_chatbot_access(chatbot_id)
        existing = get_wasender_channel_by_id(channel_id)
        if not existing:
            return _wasender_failure(None, "WasenderAPI channel not found.", 404)
        if (str(existing.get("chatbot_id")) != str(chatbot_id)
                or str(existing.get("company_id")) != str(access["company_id"])):
            return _wasender_failure(None, "This channel does not belong to this chatbot.", 403)
        ensure_channel_slot("wasender", chatbot_id, access["company_id"])
        changes = {"connection_attempted_at": datetime.now(timezone.utc).isoformat()}
        if existing.get("connection_status") != "connected" or not existing.get("is_active"):
            changes.update(connection_status="pending", is_active=True, verified_at=None)
        data = request.get_json(silent=True) or {}
        if data.get("session_id"):
            session_id = str(data["session_id"]).strip()
            if not session_id.isdigit():
                return _wasender_failure(None, "WasenderAPI session ID must be numeric.")
            if existing.get("session_id") and str(existing["session_id"]) != session_id:
                return _wasender_failure(None, "Use Connect to replace the WasenderAPI session.")
            changes["session_id"] = session_id
        channel = update_wasender_channel(channel_id, changes)
        if not channel:
            return _wasender_failure(None, "Unable to prepare the connection attempt.", 503)
        return _verify_wasender_candidate(channel, data.get("personal_access_token"), chatbot_id, access["company_id"])
    except PermissionError as e:
        return _wasender_failure(None, str(e), 403)
    except BillingLimitError as e:
        return _wasender_failure(channel, str(e), 403, e.code)
    except ChannelActivationError as e:
        return _wasender_failure(channel, str(e), 409, e.code)
    except requests.RequestException:
        return _wasender_failure(channel, "Unable to verify WasenderAPI. The previous connection is unchanged.", 502)
    except ValueError as e:
        return _wasender_failure(channel, str(e))
    except Exception as e:
        if getattr(e, "code", None) == "23505":
            return _wasender_failure(channel, "This number is already reserved by another connection.", 409,
                                     "provider_identity_in_use")
        return server_error("reconnect_wasender", e)


@wasender_blueprint.route("/api/wasender/channels/<int:channel_id>/delivery", methods=["GET"])
@token_required
@role_required("admin", "owner")
def wasender_delivery(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _wasender_failure(None, "chatbot_id is required")
        access = verify_chatbot_access(chatbot_id)
        channel = get_wasender_channel_by_id(channel_id)
        if not channel:
            return _wasender_failure(None, "WasenderAPI channel not found.", 404)
        if (str(channel.get("chatbot_id")) != str(chatbot_id)
                or str(channel.get("company_id")) != str(access["company_id"])):
            return _wasender_failure(None, "This channel does not belong to this chatbot.", 403)
        result = {"delivery_status": "unknown", "message": "This channel is inactive."}
        if channel.get("is_active") and channel.get("connection_status") == "connected":
            try:
                result = verify_wasender_connection(channel)
                if result.get("provider_user_id"):
                    result.update(delivery_status="unknown", message="Session is connected; webhook needs verification with a personal access token.")
                else:
                    result["delivery_status"] = "failed"
            except requests.RequestException:
                result = {"delivery_status": "unknown", "message": "WasenderAPI status is temporarily unavailable."}
            except ValueError:
                result = {"delivery_status": "failed", "message": "Provider identity or credentials could not be verified."}
        return jsonify({"status": "success", "data": {**safe_wasender_channel(channel),
                        "delivery_status": result["delivery_status"], "delivery_error": result["message"],
                        "message": result["message"],
                        "session_status": "connected" if result.get("provider_user_id") else (
                            "disconnected" if result["delivery_status"] == "failed" else "unknown"),
                        "webhook_verified_at": channel.get("verified_at"),
                        "checked_at": datetime.now(timezone.utc).isoformat()}}), 200
    except PermissionError as e:
        return _wasender_failure(None, str(e), 403)
    except Exception as e:
        return server_error("wasender_delivery", e)


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

        access = verify_chatbot_access(chatbot_id)

        channels = get_wasender_channels_by_chatbot(chatbot_id)

        safe_channels = [safe_wasender_channel(channel) for channel in channels]

        return jsonify({
            "status": "success",
            "data": safe_channels
        }), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
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

        access = verify_chatbot_access(chatbot_id)

        channel = get_wasender_channel_by_id(channel_id)

        if not channel:
            return jsonify({
                "status": "error",
                "message": "WasenderAPI channel not found."
            }), 404

        if (str(channel.get("chatbot_id")) != str(chatbot_id)
                or str(channel.get("company_id")) != str(access["company_id"])):
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

    except PermissionError as e:
        return _wasender_failure(None, str(e), 403)
    except Exception as e:
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
        process_wasender_webhook(payload, webhook_secret)

        return jsonify({
            "status": "ok"
        }), 200

    except Exception as e:
        logging.error("Wasender webhook error (%s)", type(e).__name__)
        return jsonify({
            "status": "error",
            "message": "Internal Wasender webhook error."
        }), 500
