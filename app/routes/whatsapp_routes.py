import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, request, jsonify

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import can_connect_channel, BillingLimitError
from app.services.company_status_service import company_operational_required
from app.database.bot_repository import get_bot_by_id
from app.database.whatsapp_channel_repository import (
    disconnect_whatsapp_channel as disconnect_whatsapp_channel_record,
    get_whatsapp_channels_by_chatbot,
    get_whatsapp_channel_by_id,
    sanitize_whatsapp_channel_for_frontend,
    upsert_whatsapp_channel_by_phone_number_id,
)

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
        logging.error(f"Meta code exchange failed: {response.status_code} {response.text}")
        return None, "Failed to exchange Meta Embedded Signup code."

    token_data = response.json()

    if not token_data.get("access_token"):
        logging.error(f"Meta code exchange returned no access token: {token_data}")
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
        logging.error(f"Meta phone metadata fetch failed: {response.status_code} {response.text}")
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


@whatsapp_blueprint.route("/api/whatsapp/embedded-signup/complete", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def complete_embedded_signup():
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

        if not code:
            return jsonify({
                "status": "error",
                "message": "Meta Embedded Signup code is required."
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

        token_data, token_error = exchange_embedded_signup_code(code)

        if token_error:
            return jsonify({
                "status": "error",
                "message": token_error
            }), 400

        access_token = token_data["access_token"]
        phone_metadata, metadata_error = fetch_phone_number_metadata(
            phone_number_id,
            access_token,
        )

        if metadata_error:
            return jsonify({
                "status": "error",
                "message": metadata_error
            }), 400

        # Check subscription limit before connecting channel
        can_connect_channel(bot.get("company_id"))
        channel = upsert_whatsapp_channel_by_phone_number_id(
            phone_number_id,
            {
                "company_id": bot.get("company_id"),
                "chatbot_id": chatbot_id,
                "phone_number_id": phone_number_id,
                "whatsapp_business_account_id": waba_id,
                "waba_id": waba_id,
                "business_id": business_id,
                "access_token": access_token,
                "token_type": token_data.get("token_type"),
                "token_expires_at": calculate_token_expires_at(token_data),
                "display_phone_number": phone_metadata.get("display_phone_number"),
                "verified_name": phone_metadata.get("verified_name"),
                "quality_rating": phone_metadata.get("quality_rating"),
                "meta_app_id": os.getenv("WHATSAPP_META_APP_ID"),
                "connection_status": "connected",
                "is_active": True,
                "last_error": None,
                "webhook_url": build_webhook_url(),
                "signup_payload": build_safe_signup_payload(
                    waba_id,
                    phone_number_id,
                    business_id,
                    phone_metadata,
                ),
            },
        )

        if not channel:
            return jsonify({
                "status": "error",
                "message": "Failed to save WhatsApp channel."
            }), 500

        return jsonify({
            "status": "success",
            "message": "WhatsApp channel connected successfully.",
            "data": sanitize_whatsapp_channel_for_frontend(channel)
        }), 200

    except requests.RequestException as e:
        logging.error(f"Meta Embedded Signup request error: {e}")
        return jsonify({
            "status": "error",
            "message": "Unable to connect to Meta Graph API."
        }), 502
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Complete WhatsApp Embedded Signup error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


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

        verify_chatbot_access(chatbot_id)

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
        logging.error(f"List WhatsApp channels error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


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

    except Exception as e:
        logging.error(f"Disconnect WhatsApp channel error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
