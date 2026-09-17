import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, request, jsonify

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import BillingLimitError
from app.services.company_status_service import company_operational_required
from app.database.bot_repository import get_bot_by_id
from app.database.whatsapp_channel_repository import (
    disconnect_whatsapp_channel as disconnect_whatsapp_channel_record,
    get_whatsapp_channels_by_chatbot,
    get_whatsapp_channel_by_id,
    sanitize_whatsapp_channel_for_frontend,
    upsert_whatsapp_channel_by_phone_number_id,
    create_whatsapp_channel,
    update_whatsapp_channel,
)
from app.database.channel_lifecycle_repository import (
    activate_channel, ensure_channel_slot, ChannelActivationError,
)
from app.services.provider_connection_verification import (
    verify_meta_connection, normalize_phone_number,
)
from app.utils.api_errors import server_error

whatsapp_blueprint = Blueprint("whatsapp", __name__)


def get_graph_api_version():
    return os.getenv("WHATSAPP_GRAPH_API_VERSION") or os.getenv("VERSION") or "v22.0"


def clean_public_base_url(url: str):
    if not url:
        return ""

    return url.strip().rstrip("/")


def exchange_embedded_signup_code(code: str):
    app_id = os.getenv("WHATSAPP_META_APP_ID")
    app_secret = os.getenv("WHATSAPP_META_APP_SECRET")
    version = get_graph_api_version()

    if not app_id or not app_secret:
        return None, "WHATSAPP_META_APP_ID or WHATSAPP_META_APP_SECRET is missing."

    response = requests.get(
        f"https://graph.facebook.com/{version}/oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "code": code,
        },
        timeout=15,
    )

    if response.status_code != 200:
        logging.error("Meta code exchange failed: HTTP %s", response.status_code)
        return None, "Failed to exchange Meta Embedded Signup code."

    token_data = response.json()

    if not token_data.get("access_token"):
        logging.error("Meta code exchange returned no access token")
        return None, "Meta did not return an access token."

    return token_data, None


def fetch_phone_number_metadata(phone_number_id: str, access_token: str):
    version = get_graph_api_version()

    response = requests.get(
        f"https://graph.facebook.com/{version}/{phone_number_id}",
        params={
            "fields": "id,display_phone_number,verified_name,quality_rating",
            "access_token": access_token,
        },
        timeout=15,
    )

    if response.status_code != 200:
        logging.error("Meta phone metadata fetch failed: HTTP %s", response.status_code)
        return None, "Failed to fetch WhatsApp phone number metadata."

    return response.json(), None


def calculate_token_expires_at(token_data: dict):
    expires_in = token_data.get("expires_in")

    if not expires_in:
        return None

    try:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        return expires_at.isoformat()
    except (TypeError, ValueError):
        return None


def build_webhook_url():
    public_base_url = clean_public_base_url(
        os.getenv("PUBLIC_BASE_URL")
    )

    if not public_base_url:
        return None

    return f"{public_base_url}/webhook"


def build_safe_signup_payload(waba_id, phone_number_id, business_id, phone_metadata):
    return {
        "source": "meta_embedded_signup",
        "waba_id": waba_id,
        "phone_number_id": phone_number_id,
        "business_id": business_id,
        "phone_metadata": {
            "id": phone_metadata.get("id"),
            "display_phone_number": phone_metadata.get("display_phone_number"),
            "verified_name": phone_metadata.get("verified_name"),
            "quality_rating": phone_metadata.get("quality_rating"),
        },
    }


def _meta_failure(channel, message, status=400, code="provider_verification_failed"):
    if channel:
        changes = {"last_error": message}
        if channel.get("connection_status") != "connected":
            changes.update(connection_status="failed", is_active=False, verified_at=None)
        updated = update_whatsapp_channel(channel["id"], changes,
                                          expected_attempt_at=channel.get("connection_attempted_at"),
                                          expected_status="connected" if channel.get("connection_status") == "connected" else "pending")
        if not updated:
            try:
                current = get_whatsapp_channel_by_id(channel["id"])
            except Exception:
                return jsonify({"status": "error", "code": "activation_state_unknown",
                                "message": "Connection status is unavailable. Refresh before retrying."}), 503
            if (current and current.get("connection_status") == "connected" and current.get("is_active")
                    and all(str(current.get(key)) == str(channel.get(key))
                            for key in ("company_id", "chatbot_id", "connection_attempted_at"))):
                return jsonify({"status": "error", "code": "activation_state_unknown",
                                "message": "The connection is saved as active. Refresh status before retrying.",
                                "data": sanitize_whatsapp_channel_for_frontend(current)}), 503
            return jsonify({"status": "error", "code": "connection_superseded",
                            "message": "A newer connection attempt has replaced this attempt."}), 409
        channel = updated
    return jsonify({"status": "error", "code": code, "message": message,
                    "data": sanitize_whatsapp_channel_for_frontend(channel)}), status


@whatsapp_blueprint.route("/api/whatsapp/connect", methods=["POST"])
@whatsapp_blueprint.route("/api/whatsapp/embedded-signup/complete", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def complete_embedded_signup():
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
        code = (data.get("code") or "").strip()
        waba_id = (data.get("waba_id") or "").strip()
        phone_number_id = (data.get("phone_number_id") or "").strip()
        business_id = (data.get("business_id") or "").strip() or None
        access_token = (data.get("access_token") or "").strip()
        expected_phone = data.get("phone_number")
        if expected_phone:
            expected_phone = normalize_phone_number(expected_phone)

        if not code and not access_token:
            return jsonify({
                "status": "error",
                "message": "Meta Embedded Signup code or authorized access token is required."
            }), 400

        if not waba_id:
            return jsonify({
                "status": "error",
                "message": "WhatsApp Business Account ID is required."
            }), 400

        if not phone_number_id:
            return jsonify({
                "status": "error",
                "message": "WhatsApp phone number ID is required."
            }), 400

        bot = get_bot_by_id(chatbot_id, access["company_id"])

        if not bot:
            return jsonify({
                "status": "error",
                "message": "Chatbot not found."
            }), 404

        if not phone_number_id.isdigit() or not waba_id.isdigit():
            return _meta_failure(None, "Meta phone number ID and WABA ID must be numeric.")
        ensure_channel_slot("whatsapp", chatbot_id, bot["company_id"])
        channel = create_whatsapp_channel(
            company_id=bot["company_id"], chatbot_id=chatbot_id,
            phone_number_id=phone_number_id, whatsapp_business_account_id=waba_id,
            business_id=business_id, access_token=access_token or None,
            display_phone_number=expected_phone, webhook_url=build_webhook_url(),
            meta_app_id=os.getenv("WHATSAPP_META_APP_ID"),
            connection_status="pending", is_active=True,
        )
        if not channel:
            return _meta_failure(None, "Failed to save WhatsApp connection attempt.", 503)
        token_data = {"access_token": access_token}
        if code:
            token_data, token_error = exchange_embedded_signup_code(code)
            if token_error:
                return _meta_failure(channel, token_error)
        access_token = token_data["access_token"]
        metadata = verify_meta_connection(phone_number_id, waba_id, access_token, expected_phone)
        verified = update_whatsapp_channel(channel["id"], {
            "access_token": access_token, "token_type": token_data.get("token_type"),
            "token_expires_at": calculate_token_expires_at(token_data),
            "display_phone_number": metadata.get("display_phone_number"),
            "verified_name": metadata.get("verified_name"), "quality_rating": metadata.get("quality_rating"),
            "verified_at": datetime.now(timezone.utc).isoformat(), "last_error": None,
            "signup_payload": build_safe_signup_payload(waba_id, phone_number_id, business_id, metadata),
        }, expected_attempt_at=channel.get("connection_attempted_at"))
        if not verified:
            return _meta_failure(None, "A newer connection attempt has replaced this attempt.", 409,
                                 "connection_superseded")
        active = activate_channel("whatsapp", channel["id"], chatbot_id, bot["company_id"],
                                  expected_attempt_at=channel.get("connection_attempted_at"))
        if not active:
            return _meta_failure(channel, "A newer connection attempt has replaced this attempt.", 409,
                                 "connection_superseded")
        return jsonify({
            "status": "success",
            "message": "WhatsApp channel connected successfully.",
            "data": sanitize_whatsapp_channel_for_frontend(active)
        }), 200

    except requests.RequestException:
        return _meta_failure(channel, "Unable to verify Meta Graph API. The previous connection is unchanged.", 502)
    except ChannelActivationError as e:
        return _meta_failure(channel, str(e), 409, e.code)
    except ValueError as e:
        return _meta_failure(channel, str(e))
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
            return _meta_failure(channel, "This WhatsApp number is already assigned to an active connection.", 409,
                                 "provider_identity_in_use")
        return server_error("complete_embedded_signup", e)


@whatsapp_blueprint.route("/api/whatsapp/channels/<int:channel_id>/reconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def reconnect_whatsapp(channel_id):
    channel = None
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _meta_failure(None, "chatbot_id is required")
        access = verify_chatbot_access(chatbot_id)
        existing = get_whatsapp_channel_by_id(channel_id)
        if not existing:
            return _meta_failure(None, "WhatsApp channel not found.", 404)
        if (str(existing.get("chatbot_id")) != str(chatbot_id)
                or str(existing.get("company_id")) != str(access["company_id"])):
            return _meta_failure(None, "This channel does not belong to this chatbot.", 403)
        if not existing.get("access_token"):
            return _meta_failure(None, "Authorize the new WhatsApp number again using Connect.", 400)
        ensure_channel_slot("whatsapp", chatbot_id, access["company_id"])
        changes = {"connection_attempted_at": datetime.now(timezone.utc).isoformat()}
        if existing.get("connection_status") != "connected" or not existing.get("is_active"):
            changes.update(connection_status="pending", is_active=True, verified_at=None)
        channel = update_whatsapp_channel(channel_id, changes)
        if not channel:
            return _meta_failure(None, "Unable to prepare the connection attempt.", 503)
        verify_meta_connection(channel["phone_number_id"], channel.get("whatsapp_business_account_id") or channel.get("waba_id"),
                               channel["access_token"], channel.get("display_phone_number"))
        verified = update_whatsapp_channel(channel_id, {"verified_at": datetime.now(timezone.utc).isoformat(), "last_error": None},
                                           expected_attempt_at=channel.get("connection_attempted_at"))
        if not verified:
            return _meta_failure(None, "A newer connection attempt has replaced this attempt.", 409, "connection_superseded")
        active = verified
        if channel.get("connection_status") != "connected" or not channel.get("is_active"):
            active = activate_channel("whatsapp", channel_id, chatbot_id, access["company_id"],
                                      expected_attempt_at=channel.get("connection_attempted_at"))
        if not active:
            return _meta_failure(channel, "A newer connection attempt has replaced this attempt.", 409, "connection_superseded")
        return jsonify({"status": "success", "message": "WhatsApp connection verified.",
                        "data": sanitize_whatsapp_channel_for_frontend(active)}), 200
    except PermissionError as e:
        return _meta_failure(None, str(e), 403)
    except BillingLimitError as e:
        return _meta_failure(channel, str(e), 403, e.code)
    except ChannelActivationError as e:
        return _meta_failure(channel, str(e), 409, e.code)
    except requests.RequestException:
        return _meta_failure(channel, "Unable to verify Meta Graph API. The previous connection is unchanged.", 502)
    except ValueError as e:
        return _meta_failure(channel, str(e))
    except Exception as e:
        if getattr(e, "code", None) == "23505":
            return _meta_failure(channel, "This number is already reserved by another connection.", 409, "provider_identity_in_use")
        return server_error("reconnect_whatsapp", e)


@whatsapp_blueprint.route("/api/whatsapp/channels/<int:channel_id>/delivery", methods=["GET"])
@token_required
@role_required("admin", "owner")
def whatsapp_delivery(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _meta_failure(None, "chatbot_id is required")
        access = verify_chatbot_access(chatbot_id)
        channel = get_whatsapp_channel_by_id(channel_id)
        if not channel:
            return _meta_failure(None, "WhatsApp channel not found.", 404)
        if (str(channel.get("chatbot_id")) != str(chatbot_id)
                or str(channel.get("company_id")) != str(access["company_id"])):
            return _meta_failure(None, "This channel does not belong to this chatbot.", 403)
        status, error = "unknown", "This channel is inactive."
        if channel.get("is_active") and channel.get("connection_status") == "connected":
            try:
                verify_meta_connection(channel["phone_number_id"], channel.get("whatsapp_business_account_id") or channel.get("waba_id"),
                                       channel.get("access_token"), channel.get("display_phone_number"))
                status, error = "connected", None
            except requests.RequestException:
                status, error = "unknown", "Meta verification is temporarily unavailable."
            except ValueError:
                status, error = "failed", "Meta identity or webhook subscription could not be verified."
        return jsonify({"status": "success", "data": {**sanitize_whatsapp_channel_for_frontend(channel),
                        "delivery_status": status, "delivery_error": error,
                        "message": error or "Phone identity and Meta app subscription verified.",
                        "checked_at": datetime.now(timezone.utc).isoformat()}}), 200
    except PermissionError as e:
        return _meta_failure(None, str(e), 403)
    except Exception as e:
        return server_error("whatsapp_delivery", e)


@whatsapp_blueprint.route("/api/whatsapp/embedded-signup/config", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_embedded_signup_config():
    app_id = os.getenv("WHATSAPP_META_APP_ID")
    config_id = os.getenv("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID")

    if not app_id or not config_id:
        return jsonify({
            "status": "error",
            "message": "WhatsApp Embedded Signup is not configured. Missing app ID or configuration ID."
        }), 500

    return jsonify({
        "status": "success",
        "data": {
            "app_id": app_id,
            "config_id": config_id,
            "graph_api_version": get_graph_api_version(),
        }
    }), 200


@whatsapp_blueprint.route("/api/whatsapp/channels", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_whatsapp_channels():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        access = verify_chatbot_access(chatbot_id)

        channels = get_whatsapp_channels_by_chatbot(chatbot_id)

        safe_channels = [
            sanitize_whatsapp_channel_for_frontend(channel)
            for channel in channels
        ]

        return jsonify({
            "status": "success",
            "data": safe_channels
        }), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return server_error("list_whatsapp_channels", e)


@whatsapp_blueprint.route("/api/whatsapp/channels/<int:channel_id>/disconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def disconnect_whatsapp_channel(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        access = verify_chatbot_access(chatbot_id)

        channel = get_whatsapp_channel_by_id(channel_id)

        if not channel:
            return jsonify({
                "status": "error",
                "message": "WhatsApp channel not found"
            }), 404

        if (str(channel.get("chatbot_id")) != str(chatbot_id)
                or str(channel.get("company_id")) != str(access["company_id"])):
            return jsonify({
                "status": "error",
                "message": "This WhatsApp channel does not belong to this chatbot"
            }), 403

        updated_channel = disconnect_whatsapp_channel_record(channel_id)

        if not updated_channel:
            return jsonify({
                "status": "error",
                "message": "Failed to update WhatsApp channel"
            }), 500

        return jsonify({
            "status": "success",
            "message": "WhatsApp channel disconnected successfully",
            "data": sanitize_whatsapp_channel_for_frontend(updated_channel)
        }), 200

    except PermissionError as e:
        return _meta_failure(None, str(e), 403)
    except Exception as e:
        return server_error("disconnect_whatsapp_channel", e)
