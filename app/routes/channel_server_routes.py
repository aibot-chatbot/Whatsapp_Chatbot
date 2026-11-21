"""Owner/admin manage devices for their own operational company. Only the signed webhook is public."""
import hashlib
import hmac
import os
import re
import secrets

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.database import channel_server_repository as repo
from app.database.channel_lifecycle_repository import ChannelActivationError, activate_channel, ensure_channel_slot
from app.database.db_errors import is_unique_violation
from app.decorators.auth_decorator import token_required
from app.decorators.security import read_webhook_body
from app.services import channel_server_service as server
from app.services.billing_guard import BillingLimitError
from app.services.company_status_service import (
    CompanyOperationalStatusError, company_operational_required, ensure_company_operational,
)
from app.utils.access_control import publish_test_block, role_required, verify_chatbot_access

channel_server_blueprint = Blueprint("channel_server", __name__, url_prefix="/api/channel-server")
bp = channel_server_blueprint
INSTRUCTIONS = "WhatsApp > Settings > Linked devices > Link a device > Link with phone number instead > enter the code"
STATUS = {"STARTING": "pending", "SCAN_QR_CODE": "pending", "WORKING": "connected",
          "FAILED": "failed", "STOPPED": "disconnected"}


def error(message, status):
    return jsonify(status="error", message=message), status


@bp.errorhandler(Exception)
def handle_error(exc):
    # No exception payloads: upstream and database errors may echo sensitive data.
    if isinstance(exc, PermissionError):
        return error("You do not have access to this chatbot.", 403)
    if isinstance(exc, BillingLimitError):
        return error(str(exc), 403)
    if isinstance(exc, ChannelActivationError):
        return error(str(exc), 409 if exc.code == "channel_limit" else 503)
    if isinstance(exc, CompanyOperationalStatusError):
        return error(exc.message, exc.status_code)
    if isinstance(exc, server.ChannelServerError):
        return error(str(exc), 503)
    if is_unique_violation(exc):
        return error("Manage the existing linked device before connecting another.", 409)
    return error("The linked-device request could not be completed.", 503)


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _owned(channel_id):
    row = repo.get(channel_id)
    if not row or row["company_id"] != g.company_id:
        return None
    verify_chatbot_access(row["chatbot_id"])
    return row


def _code(row):
    response = jsonify(status="success", channel_id=row["id"],
                       pairing_code=server.pairing_code(row["session_name"], row["phone_number"]),
                       instructions=INSTRUCTIONS)
    response.headers["Cache-Control"] = "no-store"
    return response


def _start(row):
    name = row["session_name"]
    server.create_session(name)
    if not repo.active_session(name):
        # Disconnect may have completed while the remote creation was in flight.
        server.disconnect(name)
        return error("Connection changed. Refresh before retrying.", 409)
    return _code(row)


@bp.post("/connect")
@token_required
@role_required("admin", "owner")
@company_operational_required
def connect():
    data = _body()
    chatbot_id = data.get("chatbot_id")
    if type(chatbot_id) is not int or chatbot_id <= 0:
        return error("Choose a chatbot.", 400)
    company_id = verify_chatbot_access(chatbot_id)["company_id"]
    if data.get("risk_consent") is not True:
        return error("Confirm that you understand the risk.", 400)
    phone = data.get("phone_number")
    # People type "+60 12-345 6789"; keep only the digits after an optional leading "+".
    phone = re.sub(r"[\s-]", "", phone).removeprefix("+") if isinstance(phone, str) else phone
    if not isinstance(phone, str) or not re.fullmatch(r"[0-9]{8,15}", phone):
        return error("Enter 8 to 15 digits with the country code.", 400)
    if phone.startswith("01"):
        phone = "60" + phone[1:]
    if len(phone) > 15 or phone.startswith("0"):
        return error("Enter 8 to 15 digits with the country code.", 400)
    blocked = publish_test_block(chatbot_id, company_id)
    if blocked is not None:
        return blocked
    ensure_channel_slot("whatsapp_link", chatbot_id, company_id)
    server.require_available()
    stamp = repo.now()
    row = repo.create(dict(chatbot_id=chatbot_id, company_id=company_id, phone_number=phone,
                           session_name="omx-" + secrets.token_urlsafe(18), risk_consent_at=stamp,
                           risk_consent_by=g.user_id, connection_attempted_at=stamp))
    return _start(row)


@bp.get("/channels")
@token_required
@role_required("admin", "owner")
@company_operational_required
def channels():
    chatbot_id = request.args.get("chatbot_id", type=int)
    if not chatbot_id:
        return error("Choose a chatbot.", 400)
    company_id = verify_chatbot_access(chatbot_id)["company_id"]
    fields = ("id", "chatbot_id", "phone_number", "connection_status", "is_active", "verified_at")
    rows = [row for row in repo.list_channels(chatbot_id) if row["company_id"] == company_id]
    available = server.available()
    for index, row in enumerate(rows):
        if available and row["is_active"] and row["connection_status"] == "pending":
            # Recover a missed WORKING callback using the same atomic activation path.
            try:
                raw = server.status(row["session_name"])
            except server.ChannelServerError:
                continue
            if isinstance(raw, str) and raw in STATUS and STATUS[raw] != "pending":
                rows[index] = _update_status(row, raw) or repo.get(row["id"]) or row
    return jsonify(status="success", available=available, data=[{key: row.get(key) for key in fields} for row in rows])


@bp.post("/channels/<int:channel_id>/code")
@token_required
@role_required("admin", "owner")
@company_operational_required
def code(channel_id):
    row = _owned(channel_id)
    if not row:
        return error("Channel not found.", 404)
    if not row["is_active"] or row["connection_status"] != "pending":
        return error("Reconnect the device to request a pairing code.", 409)
    blocked = publish_test_block(row["chatbot_id"], row["company_id"])
    if blocked is not None:
        return blocked
    return _code(row)


@bp.put("/channels/<int:channel_id>/disconnect")
@token_required
@role_required("admin", "owner")
@company_operational_required
def disconnect(channel_id):
    row = _owned(channel_id)
    if not row:
        return error("Channel not found.", 404)
    server.require_available()
    # Stop accepting webhook deliveries before removing the remote session.
    closing = repo.update(row, {"is_active": False, "connection_status": "failed", "verified_at": None})
    if not closing:
        return error("Connection changed. Refresh before retrying.", 409)
    server.disconnect(row["session_name"])
    if not repo.update(closing, {"connection_status": "disconnected"}):
        return error("Connection changed. Refresh before retrying.", 409)
    return jsonify(status="success")


@bp.put("/channels/<int:channel_id>/reconnect")
@token_required
@role_required("admin", "owner")
@company_operational_required
def reconnect(channel_id):
    row = _owned(channel_id)
    if not row:
        return error("Channel not found.", 404)
    blocked = publish_test_block(row["chatbot_id"], row["company_id"])
    if blocked is not None:
        return blocked
    ensure_channel_slot("whatsapp_link", row["chatbot_id"], row["company_id"])
    if row["connection_status"] not in ("disconnected", "failed"):
        return error("Disconnect the current device before reconnecting.", 409)
    server.require_available()
    if row["is_active"] or row["connection_status"] == "failed":
        row = repo.update(row, {"is_active": False, "connection_status": "failed", "verified_at": None})
        if not row:
            return error("Connection changed. Refresh before retrying.", 409)
        server.disconnect(row["session_name"])
    # A fresh session rejects delayed callbacks from the previous pairing.
    # Conversations remain bound to the same channel row and consented phone number.
    row = repo.update(row, {"connection_status": "pending", "is_active": True, "verified_at": None,
                            "session_name": "omx-" + secrets.token_urlsafe(18),
                            "connection_attempted_at": repo.now()})
    if not row:
        return error("Connection changed. Refresh before retrying.", 409)
    return _start(row)


def _update_status(row, raw):
    status = STATUS.get(raw) if isinstance(raw, str) else None
    if not status or status == row["connection_status"] == "connected":
        return
    changes = {"connection_status": status, "verified_at": None}
    if status == "connected":
        # WORKING verifies the session. The shared RPC enforces the paid slot under the company lock.
        candidate = repo.update(row, {"connection_status": "pending", "verified_at": repo.now()})
        if candidate:
            return activate_channel("whatsapp_link", row["id"], row["chatbot_id"], row["company_id"],
                                    expected_attempt_at=candidate.get("connection_attempted_at"))
    else:
        return repo.update(row, changes)


@bp.post("/webhook")
def webhook():
    key = os.environ.get("CHANNEL_SERVER_HMAC_KEY")
    signature = request.headers.get("X-Webhook-Hmac", "")
    if (not key or request.headers.get("X-Webhook-Hmac-Algorithm", "").lower() != "sha512"
            or not re.fullmatch(r"[a-fA-F0-9]{128}", signature)):
        return error("Invalid webhook signature.", 401)
    try:
        raw = read_webhook_body()
    except RequestEntityTooLarge:
        return error("Webhook body is too large.", 413)
    expected = hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        return error("Invalid webhook signature.", 401)
    data = _body()
    name, payload = data.get("session"), data.get("payload")
    if not isinstance(name, str) or not name or len(name) > 128 or not isinstance(payload, dict):
        return error("Invalid webhook event.", 400)
    row = repo.active_session(name)
    if not row or not row["is_active"]:
        return error("Channel not found.", 404)
    ensure_company_operational(row["company_id"])
    if data.get("event") == "session.status":
        _update_status(row, payload.get("status"))
    elif data.get("event") == "message" and row["connection_status"] == "connected":
        server.process_message(row, payload, repo.claim)
    return jsonify(status="success")
