"""Merchant catalogue and explicit, session-bound guest trial confirmations."""
from functools import wraps
from flask import Blueprint, g, jsonify, request

from app.decorators.auth_decorator import token_required
from app.database.conversation_repository import find_widget_conversation
from app.routes.widget_routes import widget_blueprint, _load_widget_or_error, limiter
from app.services import tuition_service as service
from app.services.billing_guard import BillingLimitError, can_use_plan_feature
from app.services.company_status_service import CompanyOperationalStatusError, ensure_company_operational
from app.services.web_widget_service import WidgetError, open_conversation, validate_session_id
from app.utils.access_control import role_required, verify_chatbot_access

tuition_blueprint = Blueprint("tuition", __name__)


def _errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        try:
            return fn(*args, **kwargs)
        except service.TuitionError as exc:
            return jsonify(message=str(exc), code=exc.code), exc.status_code
        except WidgetError as exc:
            return jsonify(message=str(exc), code=exc.code), exc.status
        except (BillingLimitError, CompanyOperationalStatusError):
            return jsonify(message="Trial bookings are temporarily unavailable."), 403
        except PermissionError:
            return jsonify(message="This resource is unavailable."), 404
        except ValueError as exc:
            return jsonify(message=str(exc)), 400
        except Exception as exc:
            from flask import current_app
            current_app.logger.error("Trial request failed (%s)", type(exc).__name__)
            return jsonify(message="Trial booking is temporarily unavailable."), 503
    return wrapped


def _body(fields):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - set(fields):
        raise ValueError("Invalid trial request fields.")
    return body


def _admin(bot_id):
    verify_chatbot_access(bot_id)
    ensure_company_operational(g.company_id)
    can_use_plan_feature(g.company_id, "ai_generated_reports")
    return {"company_id": g.company_id, "chatbot_id": bot_id}


@tuition_blueprint.route("/api/tuition/bots/<int:bot_id>/catalog", methods=["GET", "POST"])
@token_required
@role_required("owner", "admin")
@_errors
def catalog(bot_id):
    scope = _admin(bot_id)
    if request.method == "GET":
        return jsonify(data={"courses": service.list_courses(**scope), "classes": service.list_classes(**scope),
                             "sessions": service.list_sessions(**scope), "bookings": service.list_bookings(**scope)})
    body = _body({"kind", "name", "course_id", "class_id", "starts_at", "ends_at", "total_capacity", "enrolled_seats", "trial_limit"})
    kind = body.pop("kind", None)
    fields = {"course": {"name"}, "class": {"course_id", "name"},
              "session": {"class_id", "starts_at", "ends_at", "total_capacity", "enrolled_seats", "trial_limit"}}
    if kind not in fields or set(body) != fields[kind]:
        raise ValueError("Provide the required course, class or session fields.")
    action = {"course": service.create_course, "class": service.create_class, "session": service.create_session}[kind]
    return jsonify(data=action(**scope, actor_user_id=g.user_id, **body)), 201


@tuition_blueprint.route("/api/tuition/bots/<int:bot_id>/sessions/<uuid:session_id>/capacity", methods=["POST"])
@token_required
@role_required("owner", "admin")
@_errors
def capacity(bot_id, session_id):
    scope = _admin(bot_id)
    body = _body({"expected_version", "total_capacity", "enrolled_seats", "trial_limit"})
    if len(body) != 4:
        raise ValueError("All capacity values and the current version are required.")
    return jsonify(data=service.update_session_capacity(**scope, actor_user_id=g.user_id, session_id=str(session_id), **body))


@widget_blueprint.route("/api/widget/<public_key>/tuition", methods=["POST", "OPTIONS"])
@limiter.limit("30/minute")
@_errors
def guest_trial(public_key):
    widget, bot = _load_widget_or_error()
    can_use_plan_feature(bot["company_id"], "ai_generated_reports")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("A trial request is required.")
    action = body.get("action")
    fields = {"list": set(), "participant": {"client_key", "label"},
              "prepare": {"participant_id", "session_id", "booking_id", "reminder_consent"},
              "confirm": {"confirmation_token"}, "cancel": {"booking_id", "client_message_id", "expected_version"}}
    if action not in fields or set(body) - (fields[action] | {"action", "session_id_token"}):
        raise ValueError("Invalid trial action or fields.")
    required = fields[action] - ({"booking_id", "reminder_consent"} if action == "prepare" else set())
    if not required.issubset(body):
        raise ValueError("Required trial details are missing.")
    session = validate_session_id(body.pop("session_id_token", None))
    body.pop("action")
    bot_scope = {"company_id": bot["company_id"], "chatbot_id": widget["chatbot_id"]}
    if action == "list":
        sessions = service.list_sessions(**bot_scope)
        conversation = find_widget_conversation(widget["chatbot_id"], session)
        scope = {**bot_scope, "conversation_id": conversation["id"]} if conversation else None
        return jsonify(data={"sessions": sessions,
                             "participants": service.list_participants(**scope) if scope else [],
                             "bookings": service.list_bookings(**scope) if scope else [],
                             "reminders_supported": False, "reminder_reason": "Web chat does not support scheduled outbound reminders."})
    service.require_trial_context(**bot_scope)
    conversation = find_widget_conversation(widget["chatbot_id"], session)
    if conversation is None and action != "participant":
        raise WidgetError("Start a trial request before confirming or changing it.", status=409, code="trial_session_missing")
    if conversation is None:
        conversation = open_conversation(widget, session)
    scope = {**bot_scope, "conversation_id": conversation["id"]}
    function = {"participant": service.create_participant, "prepare": service.prepare_trial,
                "confirm": service.confirm_trial, "cancel": service.cancel_trial}[action]
    # A web session is the contact identity. Never match or merge by entered name/phone.
    return jsonify(data=function(**scope, **body))
