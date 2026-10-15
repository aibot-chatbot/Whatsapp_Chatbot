"""Publish page: connect a WhatsApp number that runs on WhatChimp.

The owner pastes one thing, their WhatChimp API key. /numbers lists the
WhatsApp numbers on that account so they pick one instead of typing an ID;
/connect re-checks that the key really owns the picked number before the row is
activated. The API key is never returned to the browser.
"""

import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.database.bot_repository import get_bot_by_id
from app.database.channel_lifecycle_repository import ChannelActivationError, activate_channel, ensure_channel_slot
from app.database.whatchimp_channel_repository import (
    create_whatchimp_channel,
    disconnect_whatchimp_channel,
    get_whatchimp_channel_by_id,
    get_whatchimp_channel_by_secret,
    get_whatchimp_channels_by_chatbot,
    update_whatchimp_channel,
)
from app.decorators.auth_decorator import token_required
from app.rate_limit import limiter
from app.services.billing_guard import BillingLimitError
from app.services.company_status_service import company_operational_required
from app.services.webhook_worker import submit
from app.services.whatchimp_client import list_whatsapp_numbers
from app.services.whatchimp_service import process_whatchimp_webhook
from app.utils.access_control import role_required, verify_chatbot_access
from app.utils.api_errors import server_error

whatchimp_blueprint = Blueprint("whatchimp", __name__)

WRONG_KEY = "WhatChimp did not accept this API key. Copy it again from WhatChimp and paste it here."
NO_NUMBERS = "This WhatChimp account has no WhatsApp number yet. Connect your number in WhatChimp first."
NUMBER_NOT_ON_ACCOUNT = "That WhatsApp number is not on this WhatChimp account. Choose one from the list."
# Each of these routes holds a worker thread for up to 20 s on a live WhatChimp call.
LIVE_LOOKUP_LIMIT = "10/minute"
MAX_WEBHOOK_BYTES = 256 * 1024
_SECRET_SHAPE = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)


def safe_whatchimp_channel(channel):
    """Everything the Publish page needs, never the API key or the webhook secret on its own."""
    if not channel:
        return None
    return {key: channel.get(key) for key in (
        "id", "company_id", "chatbot_id", "phone_number_id", "display_phone_number", "business_name",
        "webhook_url", "connection_status", "last_error", "is_active", "created_at", "updated_at",
        "connection_attempted_at", "verified_at", "last_inbound_at")}


def _error(message, status=400, code=None, channel=None):
    body = {"status": "error", "message": message}
    if code:
        body["code"] = code
    if channel:
        body["data"] = safe_whatchimp_channel(channel)
    return jsonify(body), status


def _owned_channel(channel_id, chatbot_id, company_id):
    channel = get_whatchimp_channel_by_id(channel_id)
    if not channel or str(channel.get("chatbot_id")) != str(chatbot_id) or str(channel.get("company_id")) != str(company_id):
        return None
    return channel


def _lookup_numbers(api_token):
    """(numbers, None) or (None, an error response the owner can act on)."""
    result = list_whatsapp_numbers(api_token)
    if not result["success"]:
        unreachable = result["data"] is None
        return None, _error("WhatChimp is not answering right now. Please try again in a minute." if unreachable
                            else WRONG_KEY, 502 if unreachable else 400, "whatchimp_unreachable" if unreachable
                            else "whatchimp_key_rejected")
    if not result["data"]:
        return None, _error(NO_NUMBERS, 400, "whatchimp_no_numbers")
    return result["data"], None


@whatchimp_blueprint.route("/api/whatchimp/numbers", methods=["POST"])
@token_required
@role_required("admin", "owner")
@limiter.limit(LIVE_LOOKUP_LIMIT)
@company_operational_required
def whatchimp_numbers():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _error("chatbot_id is required")
        verify_chatbot_access(chatbot_id)
        api_token = str((request.get_json(silent=True) or {}).get("api_token") or "").strip()
        if not api_token:
            return _error("Paste your WhatChimp API key first.")
        numbers, failure = _lookup_numbers(api_token)
        if failure:
            return failure
        return jsonify({"status": "success", "data": numbers}), 200
    except PermissionError as e:
        return _error(str(e), 403)
    except Exception as e:
        return server_error("whatchimp_numbers", e)


@whatchimp_blueprint.route("/api/whatchimp/connect", methods=["POST"])
@token_required
@role_required("admin", "owner")
@limiter.limit(LIVE_LOOKUP_LIMIT)
@company_operational_required
def connect_whatchimp():
    channel = None
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _error("chatbot_id is required")
        access = verify_chatbot_access(chatbot_id)
        data = request.get_json(silent=True) or {}
        api_token = str(data.get("api_token") or "").strip()
        phone_number_id = str(data.get("phone_number_id") or "").strip()
        if not api_token or not phone_number_id:
            return _error("Paste your WhatChimp API key and choose a WhatsApp number.")

        bot = get_bot_by_id(chatbot_id, access["company_id"])
        if not bot:
            return _error("Chatbot not found.", 404)
        company_id = bot.get("company_id")

        public_base_url = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if not public_base_url:
            return _error("PUBLIC_BASE_URL is missing. Configure a deployed public HTTPS server URL.")

        # The browser's choice is only a hint: the key must own the number right now.
        numbers, failure = _lookup_numbers(api_token)
        if failure:
            return failure
        chosen = next((number for number in numbers if number["phone_number_id"] == phone_number_id), None)
        if not chosen:
            return _error(NUMBER_NOT_ON_ACCOUNT, 400, "whatchimp_number_not_on_account")

        ensure_channel_slot("whatchimp", chatbot_id, company_id)
        webhook_secret = secrets.token_urlsafe(32)
        channel = create_whatchimp_channel(
            company_id=company_id, chatbot_id=chatbot_id, api_token=api_token,
            phone_number_id=chosen["phone_number_id"], display_phone_number=chosen["display_phone_number"],
            business_name=chosen["business_name"], webhook_secret=webhook_secret,
            webhook_url=f"{public_base_url}/whatchimp/webhook/{webhook_secret}")
        if not channel:
            return _error("Could not save the WhatChimp connection. Please try again.", 500)

        verified = update_whatchimp_channel(channel["id"], {"verified_at": datetime.now(timezone.utc).isoformat()},
                                            expected_attempt_at=channel.get("connection_attempted_at"))
        active = verified and activate_channel("whatchimp", channel["id"], chatbot_id, company_id,
                                               expected_attempt_at=channel.get("connection_attempted_at"))
        if not active:
            return _fail(channel, "A newer connection attempt has replaced this one.", 409, "connection_superseded")
        return jsonify({"status": "success", "message": "WhatChimp number connected.",
                        "data": safe_whatchimp_channel(active)}), 200

    except PermissionError as e:
        return _error(str(e), 403)
    except BillingLimitError as e:
        return _error(str(e), 403, e.code)
    except ChannelActivationError as e:
        return _fail(channel, str(e), 409, e.code)
    except Exception as e:
        if getattr(e, "code", None) == "23505":
            return _fail(channel, "This WhatsApp number is already connected to another bot.", 409,
                         "provider_identity_in_use")
        return server_error("connect_whatchimp", e)


def _fail(channel, message, status, code):
    """Retire a pending row that could not be activated, so it never holds the number or a live key."""
    if channel and channel.get("connection_status") == "pending":
        try:
            channel = update_whatchimp_channel(channel["id"], {"connection_status": "failed", "is_active": False,
                                                              "verified_at": None, "last_error": message,
                                                              "api_token": None},
                                               expected_status="pending") or channel
        except Exception as error:
            logging.warning("Could not retire a pending WhatChimp row (%s)", type(error).__name__)
    return _error(message, status, code, channel)


@whatchimp_blueprint.route("/api/whatchimp/channels", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_whatchimp_channels():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _error("chatbot_id is required")
        verify_chatbot_access(chatbot_id)
        return jsonify({"status": "success", "data": [
            safe_whatchimp_channel(channel) for channel in get_whatchimp_channels_by_chatbot(chatbot_id)]}), 200
    except PermissionError as e:
        return _error(str(e), 403)
    except Exception as e:
        return server_error("list_whatchimp_channels", e)


@whatchimp_blueprint.route("/api/whatchimp/channels/<int:channel_id>/delivery", methods=["GET"])
@token_required
@role_required("admin", "owner")
@limiter.limit("30/minute")
def whatchimp_delivery(channel_id):
    """Sending works while the key still owns the number; receiving works once a message has arrived."""
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _error("chatbot_id is required")
        access = verify_chatbot_access(chatbot_id)
        channel = _owned_channel(channel_id, chatbot_id, access["company_id"])
        if not channel:
            return _error("WhatChimp channel not found.", 404)
        status, message = "unknown", "This channel is inactive."
        if channel.get("is_active") and channel.get("connection_status") == "connected":
            result = list_whatsapp_numbers(channel.get("api_token"))
            if not result["success"]:
                status, message = ("unknown", "WhatChimp is temporarily unavailable.") if result["data"] is None else (
                    "failed", "WhatChimp no longer accepts the saved API key. Connect again with a new key.")
            elif not any(n["phone_number_id"] == channel.get("phone_number_id") for n in result["data"]):
                status, message = "failed", "This number was removed from the WhatChimp account."
            elif not channel.get("last_inbound_at"):
                status, message = "unknown", "Connected. Paste the webhook link into WhatChimp, then send your number a test message."
            else:
                status, message = "ok", "Sending and receiving messages."
        return jsonify({"status": "success", "data": {
            **safe_whatchimp_channel(channel), "delivery_status": status, "delivery_error": message, "message": message,
            "checked_at": datetime.now(timezone.utc).isoformat()}}), 200
    except PermissionError as e:
        return _error(str(e), 403)
    except Exception as e:
        return server_error("whatchimp_delivery", e)


@whatchimp_blueprint.route("/api/whatchimp/channels/<int:channel_id>/disconnect", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def disconnect_whatchimp(channel_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return _error("chatbot_id is required")
        access = verify_chatbot_access(chatbot_id)
        if not _owned_channel(channel_id, chatbot_id, access["company_id"]):
            return _error("WhatChimp channel not found.", 404)
        updated = disconnect_whatchimp_channel(channel_id)
        if not updated:
            return _error("Failed to disconnect the WhatChimp channel.", 500)
        return jsonify({"status": "success", "message": "WhatChimp channel disconnected.",
                        "data": safe_whatchimp_channel(updated)}), 200
    except PermissionError as e:
        return _error(str(e), 403)
    except Exception as e:
        return server_error("disconnect_whatchimp", e)


@whatchimp_blueprint.route("/whatchimp/webhook/<webhook_secret>", methods=["GET"])
def whatchimp_webhook_health(webhook_secret):
    return jsonify({"status": "ok", "message": "WhatChimp webhook endpoint is active."}), 200


@whatchimp_blueprint.route("/whatchimp/webhook/<webhook_secret>", methods=["POST"])
def whatchimp_webhook_post(webhook_secret):
    # Unauthenticated: junk links and bodies are dropped here so they never take a slot in the
    # webhook queue that every channel shares. Unknown links still answer 200, so there is no oracle.
    if not _SECRET_SHAPE.fullmatch(webhook_secret or ""):
        return jsonify({"status": "ok"}), 200
    body = request.stream.read(MAX_WEBHOOK_BYTES + 1)
    if len(body) > MAX_WEBHOOK_BYTES:
        return jsonify({"status": "error", "message": "Payload too large"}), 413
    # The path secret is the only authentication factor, so only its fingerprint is logged.
    fingerprint = hashlib.sha256(webhook_secret.encode()).hexdigest()[:12]
    if not get_whatchimp_channel_by_secret(webhook_secret):
        logging.warning("WhatChimp webhook has no active channel for %s; delivery dropped.", fingerprint)
        return jsonify({"status": "ok"}), 200
    logging.info("WhatChimp webhook received for channel %s", fingerprint)
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # Answer WhatChimp before the ~7 s AI reply, so a slow reply is not redelivered.
    if not submit("WhatChimp webhook", lambda: process_whatchimp_webhook(payload, webhook_secret)):
        logging.warning("WhatChimp webhook queue is full; asking the provider to redeliver.")
        return jsonify({"status": "busy", "message": "Busy"}), 503
    return jsonify({"status": "ok"}), 200
