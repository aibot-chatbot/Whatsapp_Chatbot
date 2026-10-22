"""booking_routes.py - Staff-facing bookings API.

The company always comes from the signed-in user's token, never from the request. Staff list,
confirm, edit and cancel bookings and download the bookings CSV (the company's, or one chatbot's);
an admin turns chat booking intake on or off per chatbot.
"""

import json

from flask import Blueprint, Response, g, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.database.bot_repository import get_bot_by_id
from app.decorators.auth_decorator import token_required
from app.services import booking_service, bookings_csv_service
from app.services.company_status_service import company_operational_required
from app.utils.access_control import role_required, verify_chatbot_access
from app.utils.api_errors import server_error

booking_blueprint = Blueprint("bookings", __name__)
_MAX_BODY_BYTES = 64 * 1024
_MAX_OFFSET = 100_000  # the CSV holds 5000 rows; nobody pages past this


def _error(message, status, code=None):
    body = {"status": "error", "message": message}
    if code:
        body["code"] = code
    return jsonify(body), status


def _int_arg(name, default=None, *, minimum=None, maximum=None):
    """A query-string integer. Absent gives the default; present but unusable is a 400.

    Silently ignoring a bad value would turn ?chatbot_id=abc into "every chatbot".
    """
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise booking_service.BookingValidationError(f"{name} must be a whole number.") from None
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise booking_service.BookingValidationError(f"{name} is out of range.")
    return value


def _read_json_object():
    """Read a bounded JSON object, counting the real stream so chunked bodies are limited too."""
    if request.content_length is not None and request.content_length > _MAX_BODY_BYTES:
        raise RequestEntityTooLarge()
    raw = request.stream.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        raise RequestEntityTooLarge()
    try:
        data = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise booking_service.BookingValidationError("Request body must be valid JSON.") from None
    if not isinstance(data, dict):
        raise booking_service.BookingValidationError("Request body must be a JSON object.")
    return data


@booking_blueprint.route("/api/bookings", methods=["GET"])
@token_required
def list_bookings():
    try:
        chatbot_id = _int_arg("chatbot_id", minimum=1)
        limit = _int_arg("limit", 50, minimum=1)  # the repository caps the page size
        offset = _int_arg("offset", 0, minimum=0, maximum=_MAX_OFFSET)
        if chatbot_id is not None:
            verify_chatbot_access(chatbot_id)
        bookings = booking_service.list_for_company(
            g.company_id, chatbot_id=chatbot_id, status=request.args.get("status"), limit=limit, offset=offset)
        return jsonify({"status": "success", "data": {"bookings": bookings}}), 200
    except PermissionError as exc:
        return _error(str(exc), 403)
    except booking_service.BookingError as exc:
        return _error(str(exc), exc.status_code, exc.code)
    except Exception as exc:
        return server_error("list_bookings", exc)


@booking_blueprint.route("/api/bookings/<int:booking_id>", methods=["PATCH"])
@token_required
@company_operational_required
def update_booking(booking_id):
    try:
        changes = _read_json_object()
        expected_version = changes.pop("expected_version", None)
        if type(expected_version) is not int or expected_version < 1:
            return _error("expected_version is required.", 400, "invalid_booking")
        if not changes:
            return _error("Nothing to change.", 400, "invalid_booking")
        booking = booking_service.update_booking(g.company_id, booking_id, expected_version, changes)
        return jsonify({"status": "success", "data": {"booking": booking}}), 200
    except RequestEntityTooLarge:
        return _error("Request body is too large.", 413)
    except booking_service.BookingError as exc:
        return _error(str(exc), exc.status_code, exc.code)
    except Exception as exc:
        return server_error("update_booking", exc)


@booking_blueprint.route("/api/bookings/export.csv", methods=["GET"])
@token_required
def export_bookings_csv():
    try:
        chatbot_id = _int_arg("chatbot_id", minimum=1)
        if chatbot_id is None:
            content, filename = bookings_csv_service.build_company_csv(g.company_id), "bookings.csv"
        else:
            verify_chatbot_access(chatbot_id)
            content = bookings_csv_service.build_company_csv(g.company_id, chatbot_id=chatbot_id)
            filename = f"bookings-bot-{chatbot_id}.csv"
    except PermissionError as exc:
        return _error(str(exc), 403)
    except booking_service.BookingError as exc:
        return _error(str(exc), exc.status_code, exc.code)
    except Exception as exc:
        return server_error("export_bookings_csv", exc)
    return Response(content, headers={
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@booking_blueprint.route("/api/bookings/settings", methods=["GET"])
@token_required
def get_booking_settings():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if chatbot_id is None:
            return _error("chatbot_id is required.", 400)
        verify_chatbot_access(chatbot_id)
        bot = get_bot_by_id(chatbot_id, company_id=g.company_id)
        enabled = bool(bot and bot.get("booking_intake_enabled") is True)
        return jsonify({"status": "success", "data": {"chatbot_id": chatbot_id, "enabled": enabled}}), 200
    except PermissionError as exc:
        return _error(str(exc), 403)
    except Exception as exc:
        return server_error("get_booking_settings", exc)


@booking_blueprint.route("/api/bookings/settings", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def update_booking_settings():
    try:
        body = _read_json_object()
        chatbot_id, enabled = body.get("chatbot_id"), body.get("enabled")
        if type(chatbot_id) is not int or chatbot_id < 1 or type(enabled) is not bool:
            return _error("chatbot_id and a true/false enabled value are required.", 400)
        verify_chatbot_access(chatbot_id)
        if not booking_service.set_intake_enabled(g.company_id, chatbot_id, enabled):
            return _error("Chatbot not found.", 404)
        return jsonify({"status": "success", "data": {"chatbot_id": chatbot_id, "enabled": enabled}}), 200
    except PermissionError as exc:
        return _error(str(exc), 403)
    except RequestEntityTooLarge:
        return _error("Request body is too large.", 413)
    except booking_service.BookingError as exc:
        return _error(str(exc), exc.status_code, exc.code)
    except Exception as exc:
        return server_error("update_booking_settings", exc)
