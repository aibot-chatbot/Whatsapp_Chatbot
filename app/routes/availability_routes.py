"""availability_routes.py - The owner's availability booking API (Pro).

Packages, weekly hours, one-off times, closed dates and the instant-confirm switch for one
chatbot. The company always comes from the signed-in user's token; every package, time and
date is looked up within that company and its chatbot is access-checked. Reads are open to
members, writes to admins and owners. The plan gate (Pro) is enforced by the service.
"""

from functools import wraps

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.database.bot_repository import get_bot_by_id
from app.decorators.auth_decorator import token_required
from app.routes.booking_routes import _error, _read_json_object
from app.services import availability_service, booking_service
from app.services.company_status_service import company_operational_required
from app.utils.access_control import role_required, verify_chatbot_access
from app.utils.api_errors import server_error

availability_blueprint = Blueprint("availability", __name__)


def _handled(view):
    """One error mapping for every endpoint; nothing internal reaches the response."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except PermissionError as exc:
            return _error(str(exc), 403)
        except RequestEntityTooLarge:
            return _error("Request body is too large.", 413)
        except (availability_service.AvailabilityError, booking_service.BookingError) as exc:
            return _error(str(exc), exc.status_code, exc.code)
        except Exception as exc:
            return server_error(view.__name__, exc)
    return wrapper


def _chatbot_id(value):
    if type(value) is not int or value < 1:
        raise availability_service.AvailabilityError("chatbot_id is required.")
    verify_chatbot_access(value)
    return value


def _own_package(package_id):
    package = availability_service.get_package(g.company_id, package_id)
    verify_chatbot_access(package["chatbot_id"])
    return package


def _version(body):
    version = body.pop("expected_version", None)
    if type(version) is not int or version < 1:
        raise availability_service.AvailabilityError("expected_version is required.")
    return version


@availability_blueprint.route("/api/bookings/availability", methods=["GET"])
@token_required
@_handled
def get_availability():
    chatbot_id = _chatbot_id(request.args.get("chatbot_id", type=int))
    bot = get_bot_by_id(chatbot_id, company_id=g.company_id)
    data = availability_service.overview(g.company_id, chatbot_id, bot)
    return jsonify({"status": "success", "data": data}), 200


@availability_blueprint.route("/api/bookings/packages", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def create_package():
    body = _read_json_object()
    chatbot_id = _chatbot_id(body.pop("chatbot_id", None))
    body.pop("company_id", None)  # always the token's company
    package = availability_service.create_package(g.company_id, chatbot_id, body)
    return jsonify({"status": "success", "data": {"package": package}}), 201


@availability_blueprint.route("/api/bookings/packages/<int:package_id>", methods=["PATCH"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def update_package(package_id):
    body = _read_json_object()
    _own_package(package_id)
    package = availability_service.update_package(g.company_id, package_id, _version(body), body)
    return jsonify({"status": "success", "data": {"package": package}}), 200


@availability_blueprint.route("/api/bookings/packages/<int:package_id>/hours", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def replace_hours(package_id):
    body = _read_json_object()
    _own_package(package_id)
    hours = availability_service.replace_weekly_hours(g.company_id, package_id, body.get("hours"))
    return jsonify({"status": "success", "data": {"hours": hours}}), 200


@availability_blueprint.route("/api/bookings/slots", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def create_slot():
    body = _read_json_object()
    _own_package(body.get("package_id"))
    slot = availability_service.add_one_off_slot(g.company_id, body.get("package_id"), body.get("starts_at"),
                                                 body.get("capacity"))
    return jsonify({"status": "success", "data": {"slot": slot}}), 201


@availability_blueprint.route("/api/bookings/slots/<int:slot_id>", methods=["PATCH"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def update_slot(slot_id):
    body = _read_json_object()
    chatbot_id = _chatbot_id(body.pop("chatbot_id", None))
    slot = availability_service.update_slot(g.company_id, chatbot_id, slot_id, _version(body), body)
    return jsonify({"status": "success", "data": {"slot": slot}}), 200


@availability_blueprint.route("/api/bookings/closures", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def create_closure():
    body = _read_json_object()
    chatbot_id = _chatbot_id(body.get("chatbot_id"))
    closure = availability_service.add_closure(g.company_id, chatbot_id, body.get("closed_on"),
                                               body.get("package_id"), body.get("reason"))
    return jsonify({"status": "success", "data": {"closure": closure}}), 201


@availability_blueprint.route("/api/bookings/closures/<int:closure_id>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def delete_closure(closure_id):
    closure = availability_service.remove_closure(g.company_id, closure_id)
    return jsonify({"status": "success", "data": {"closure": closure}}), 200


@availability_blueprint.route("/api/bookings/availability/settings", methods=["PUT"])
@token_required
@role_required("admin", "owner")
@company_operational_required
@_handled
def update_settings():
    body = _read_json_object()
    chatbot_id = _chatbot_id(body.get("chatbot_id"))
    enabled = availability_service.set_auto_confirm(g.company_id, chatbot_id, body.get("auto_confirm"))
    return jsonify({"status": "success", "data": {"chatbot_id": chatbot_id, "auto_confirm": enabled}}), 200
