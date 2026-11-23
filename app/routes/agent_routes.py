from flask import Blueprint, current_app, g, jsonify, make_response, request
from functools import wraps
import logging

from app.decorators.auth_decorator import token_required
from app.rate_limit import limiter, user_rate_limit_key
from app.utils.access_control import get_current_role, role_required, verify_chatbot_access
from app.database.agent_action_repository import (
    get_pending_escalations,
    is_conversation_escalated,
    resolve_escalation,
)
from app.database.conversation_repository import get_conversation_by_id_and_chatbot
from app.database import held_replies
from app.database.message_repository import save_message

# Import dispatchers
from app.utils.whatsapp_utils import send_message as send_whatsapp_message
from app.utils.telegram_utils import send_telegram_message
from app.services.channel_delivery_service import ChannelDeliveryError, dispatch_conversation_reply, send_ai_resumed_notice, whatsapp_receipt_id
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.web_staff_reply_service import send_web_staff_reply, WebStaffReplyError
from app.services import content_filter
from app.services.chat_pipeline_service import record_content_flag

# HO-2 staff handoff API (see the block at the foot of this file).
from app.database import handoff_control_repository
from app.database.db import supabase
from app.services import handoff_service
from app.services.handoff_service import HandoffActor, HandoffService, handoff_control_enabled

agent_blueprint = Blueprint("agent", __name__)

@agent_blueprint.route("/api/agent/escalations", methods=["GET"])
@token_required
def get_escalations():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        access = verify_chatbot_access(chatbot_id)

        filters = {}
        conversation_id = request.args.get("conversation_id", type=int)
        if conversation_id:
            filters["conversation_id"] = conversation_id
        escalations = get_pending_escalations(
            chatbot_id,
            access["company_id"],
            **filters,
        )
        return jsonify({"status": "success", "data": escalations}), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error(f"Error fetching escalations: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@agent_blueprint.route("/api/agent/escalations/<int:action_id>/resolve", methods=["POST"])
@token_required
@role_required("admin", "owner")
def resolve_esc(action_id):
    try:
        data = request.get_json() or {}
        chatbot_id = data.get("chatbot_id")

        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        access = verify_chatbot_access(chatbot_id)
        resolved, changed = resolve_escalation(
            action_id,
            chatbot_id,
            access["company_id"],
        )
        if not resolved:
            return jsonify({"status": "error", "message": "Escalation not found."}), 404

        conversation_id = resolved.get("conversation_id")
        ai_resumed = resolved.get("_ai_resumed")
        if ai_resumed is None:
            ai_resumed = bool(conversation_id) and not is_conversation_escalated(conversation_id, chatbot_id)
        notification_status = "not_sent"
        notification_code = None
        if changed and ai_resumed:
            conversation = get_conversation_by_id_and_chatbot(conversation_id, chatbot_id)
            ai_resumed, notification_status, notification_code = send_ai_resumed_notice(
                conversation, chatbot_id, dispatch=_dispatch_conversation_reply, save=save_message,
                is_paused=is_conversation_escalated, lock=conversation_delivery_lock,
            )

        return jsonify({
            "status": "success", "message": "Escalation resolved." if changed else "Escalation was already resolved.",
            "data": {"already_resolved": not changed, "ai_resumed": ai_resumed,
                     "handoff_state": "ai" if ai_resumed else "human",
                     "notification_status": notification_status, "notification_code": notification_code},
        }), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


_staff_reply_limit = limiter.shared_limit(
    lambda: current_app.config.get("RATELIMIT_AGENT_REPLY", "20/minute;300/hour"),
    scope="staff_reply",
    key_func=user_rate_limit_key,
    override_defaults=False,
    on_breach=lambda _: make_response(jsonify(status="error", message="Too many staff replies. Please try again later."), 429),
)


@agent_blueprint.route("/api/conversations/<int:conversation_id>/agent-reply", methods=["POST"])
@token_required
@_staff_reply_limit
def agent_reply(conversation_id):
    try:
        data = request.get_json() or {}
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "A JSON object is required"}), 400
        chatbot_id = data.get("chatbot_id")
        text = data.get("text")

        if not chatbot_id or not text:
            return jsonify({"status": "error", "message": "chatbot_id and text are required"}), 400

        access = verify_chatbot_access(chatbot_id)

        conversation = get_conversation_by_id_and_chatbot(conversation_id, chatbot_id)
        if not conversation:
            return jsonify({"status": "error", "message": "Conversation not found"}), 404

        # An idle check must see either the completed staff reply or the handoff before the send.
        with conversation_delivery_lock(conversation_id):
            refusal = _staff_reply_refusal(conversation_id, chatbot_id, conversation)
            if refusal is not None:
                return refusal
            return _deliver_staff_reply(conversation_id, chatbot_id, access, conversation, text)

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        logging.error("Agent reply unavailable (%s)", type(e).__name__)
        return jsonify({"status": "error", "message": "The reply could not be confirmed. Refresh the conversation before retrying."}), 503


def _staff_reply_refusal(conversation_id, chatbot_id, conversation):
    # Reading held drafts and resolving them (send / edit and send / discard):
    # same rule as POST /api/conversations/<id>/agent-reply in app/routes/agent_routes.py
    # (owner/admin on any conversation of their company; other roles only on conversations
    # that are escalated/handed over), company-scoped, chatbot ownership verified.
    # Held draft text is returned only by those endpoints. Never put it in emails,
    # notifications, logs, agent_actions, Sentry or analytics.
    requires_handoff = get_current_role() not in {"owner", "admin"}
    if requires_handoff and not is_conversation_escalated(conversation_id, chatbot_id, conversation=conversation):
        return jsonify({
            "status": "error", "code": "STAFF_REPLY_NOT_ALLOWED",
            "message": "Only owners and admins can reply here. Members can reply to chats handed over to staff.",
        }), 403
    return None


def _deliver_staff_reply(conversation_id, chatbot_id, access, conversation, text):
    # Filter 1 (plan A3). Staff may still point a customer to self-harm support.
    # chatbot_id is the caller's own bot: verify_chatbot_access raised otherwise.
    flag = content_filter.check_bot_text(text, chatbot_id, include_self_harm=False)
    if flag is not None:
        record_content_flag(company_id=access["company_id"], chatbot_id=access["id"],
                            conversation_id=conversation_id, flag=flag, source="staff")
        return jsonify({"status": "error", "code": "CONTENT_BLOCKED",
                        "message": "This reply was not sent: it contains words Omnexa does not allow. "
                                   "Edit it and try again."}), 422

    if conversation.get("source_channel") == "web":
        try:
            accepted = send_web_staff_reply(
                conversation, company_id=access["company_id"],
                actor_user_id=g.user_id, text=text,
            )
        except WebStaffReplyError as error:
            return jsonify({"status": "error", "code": error.code, "message": str(error)}), error.status_code
        return jsonify({
            "status": "success",
            "message": "Reply saved. The visitor will receive it in this chat.",
            "data": accepted,
        }), 200

    try:
        delivery = _dispatch_conversation_reply(conversation, text)
    except ChannelDeliveryError as error:
        return jsonify({"status": "error", "code": error.code, "message": str(error)}), (
            502 if error.code == "DELIVERY_FAILED" else 409
        )
    except Exception as error:
        logging.error("Agent delivery failed (%s)", type(error).__name__)
        return jsonify({"status": "error", "code": "DELIVERY_FAILED", "message": "The provider did not confirm delivery. Check the conversation before retrying."}), 502

    # Persist only after the external channel accepted the message. This
    # prevents an unsupported or unavailable channel from creating a
    # transcript row that claims delivery.
    save_message(
        conversation_id=conversation_id,
        sender_type="bot",
        message_text=text,
        message_type="text",
        delivery_status="sent",
        ai_generated=False,
        **({"platform_message_id": whatsapp_receipt_id(delivery)} if conversation["source_channel"] == "whatsapp" else {}),
    )

    return jsonify({"status": "success", "message": "Reply sent successfully.", "data": {"delivery_status": "sent"}}), 200


def _dispatch_conversation_reply(conversation, text):
    return dispatch_conversation_reply(conversation, text, send_telegram=send_telegram_message,
                                       send_whatsapp=send_whatsapp_message)


def _held_staff_route(view):
    """Bind the conversation to the session's company and check the same handoff as agent-reply."""
    @wraps(view)
    def wrapped(conversation_id, **kwargs):
        try:
            with conversation_delivery_lock(conversation_id):
                conversation = held_replies.get_conversation(conversation_id, g.company_id)
                if not conversation:
                    return jsonify(status="error", message="Conversation not found"), 404
                chatbot_id = conversation["chatbot_id"]
                access = verify_chatbot_access(chatbot_id)
                refusal = _staff_reply_refusal(conversation_id, chatbot_id, conversation)
                if refusal is not None:
                    return refusal
                return view(conversation, access, **kwargs)
        except PermissionError:
            return jsonify(status="error", message="You do not have access to this chatbot."), 403
        except Exception as error:
            logging.error("Held reply review unavailable (%s)", type(error).__name__)
            return jsonify(status="error", message="Review unavailable. Refresh the conversation."), 503
    return wrapped


@agent_blueprint.route("/api/conversations/<int:conversation_id>/held-replies", methods=["GET"])
@token_required
@_held_staff_route
def get_held_replies(conversation, access):
    from app.services.reply_check_service import grade_label

    rows = held_replies.list_pending(access["company_id"], access["id"], conversation["id"])
    response = jsonify(status="success", held_replies=[
        {"id": row["id"], "draft": row["draft"], "created_at": row["created_at"],
         "category": row["category"], "subtype": row["subtype"],
         "reason_label": grade_label(row["category"], row["subtype"]),
         "delivery_pending": row.get("resolved_by") is not None} for row in rows
    ])
    response.cache_control.no_store = True
    return response


@agent_blueprint.route("/api/conversations/<int:conversation_id>/held-replies/<int:held_id>/resolve", methods=["POST"])
@token_required
@_staff_reply_limit
@_held_staff_route
def resolve_held_reply(conversation, access, held_id):
    body = request.get_json(silent=True)
    action = body.get("action") if isinstance(body, dict) else None
    if action not in ("send", "edit", "discard"):
        return jsonify(status="error", message="Choose send, edit or discard."), 400

    text = body.get("text")
    if action == "edit" and (not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000):
        return jsonify(status="error", message="Reply must contain between 1 and 2000 characters."), 400

    scope = (access["company_id"], access["id"], conversation["id"], held_id)
    if action == "discard":
        if held_replies.discard(*scope, g.user_id):
            return jsonify(status="success", resolution="discarded")
        row = None
    else:
        row = held_replies.claim(*scope, g.user_id)
    if not row:
        if not held_replies.exists(*scope):
            return jsonify(status="error", message="Held reply not found."), 404
        return jsonify(status="error", message="This reply has already been claimed or resolved."), 409

    text = text.strip() if action == "edit" else row["draft"]
    if not text.strip() or len(text) > 2000:
        held_replies.release(*scope, g.user_id)
        return jsonify(status="error", message="Edit this reply to between 1 and 2000 characters."), 400
    response, status = _deliver_staff_reply(conversation["id"], access["id"], access, conversation, text)
    if status != 200:
        # The provider may have received an unacknowledged send. Keep the reservation on
        # uncertain outcomes so another worker or browser retry cannot deliver twice.
        if status < 500:
            held_replies.release(*scope, g.user_id)
        return response, status

    status = "edited" if action == "edit" else "sent"
    if not held_replies.finish(*scope, g.user_id, status):
        raise RuntimeError("Held reply resolution was not confirmed")
    return jsonify(status="success", resolution=status)


# -- HO-2 staff handoff API ------------------------------------------------
# These routes sit BESIDE the three above; none of their behaviour changes.
# The whole surface is dark until HANDOFF_CONTROL_ENABLED is on (default off),
# and while it is off nothing here reads the 060 tables.
#
# Authority is deliberately NOT expressed as a @role_required decorator. Who
# may act on a conversation is the assignee-vs-supervisor rule that lives in
# HandoffService; a second copy of it here would be a copy that drifts.

_handoff = HandoffService(handoff_control_repository)

# Every refusal the domain can return, and the honest HTTP answer for it. A
# code missing from this map falls to 400: a refusal never becomes a 200.
_HANDOFF_STATUS_BY_CODE = {
    handoff_service.CONFLICT: 409,
    handoff_service.INVALID_STATE: 409,
    handoff_service.CROSS_TENANT: 403,
    handoff_service.NOT_ASSIGNEE: 403,
    handoff_service.NOT_SUPERVISOR: 403,
    handoff_service.CONTROL_UNREADABLE: 503,
    handoff_service.NOTE_EMPTY: 400,
}

_NOTE_REFUSALS = {
    handoff_service.CROSS_TENANT: ("This conversation belongs to another company.", 403),
    handoff_service.NOTE_EMPTY: ("An internal note needs text.", 400),
}


def _control_json(control):
    """The control state a staff UI needs. `company_id` is the caller's own
    and adds nothing, so it is not echoed back."""
    if control is None:
        return None
    return {
        "conversation_id": control.conversation_id,
        "chatbot_id": control.chatbot_id,
        "mode": control.mode,
        "resolution": control.resolution,
        "assignee_user_id": control.assignee_user_id,
        "episode_id": control.episode_id,
        "version": control.version,
        "automation_epoch": control.automation_epoch,
        "source": control.source,
    }


def _handoff_json(result, **extra):
    """One HandoffResult as an HTTP answer.

    A refusal carries whatever control the domain supplied, so a 409 shows the
    UI who actually holds the conversation instead of making it guess. A
    CROSS_TENANT refusal carries none, by the domain's design.
    """
    status = 200 if result.ok else _HANDOFF_STATUS_BY_CODE.get(result.code, 400)
    data = {"control": _control_json(result.control), "override": result.override}
    data.update(extra)
    return jsonify({
        "status": "success" if result.ok else "error",
        "code": result.code,
        "message": result.reason,
        "data": data,
    }), status


def _refuse(code, message, status):
    return jsonify({
        "status": "error", "code": code, "message": message,
        "data": {"control": None, "override": False},
    }), status


def _handoff_staff_route(view):
    """The feature flag, the request shape and the actor -- once, for every
    route below.

    The ownership gate is deliberately NOT here. `verify_chatbot_access()` is
    the first line of each handler instead, so the check is visible in the
    handler that depends on it and stays where this repo's route-handler
    ownership guard looks for it. This decorator only guarantees that a
    PermissionError raised by that call becomes a 403.
    """

    @wraps(view)
    def wrapped(conversation_id, *args, **kwargs):
        # First, and before any storage is touched: off means dark.
        if not handoff_control_enabled():
            return _refuse("HANDOFF_CONTROL_DISABLED",
                           "Human handoff control is not enabled.", 503)
        body = {} if request.method == "GET" else (request.get_json(silent=True) or {})
        chatbot_id = (request.args.get("chatbot_id", type=int) if request.method == "GET"
                      else body.get("chatbot_id"))
        if isinstance(chatbot_id, bool) or not isinstance(chatbot_id, int) or chatbot_id <= 0:
            return _refuse("CHATBOT_ID_REQUIRED", "chatbot_id is required.", 400)
        try:
            # The actor is the authenticated session and nothing else. A
            # user_id, company_id or role in the request body is never read.
            actor = HandoffActor(user_id=g.user_id, company_id=g.company_id, role=g.role)
            return view(conversation_id, actor, chatbot_id, body)
        except PermissionError as error:
            return jsonify({"status": "error", "message": str(error)}), 403
        except Exception:
            logging.exception("Handoff staff route failed (%s)", view.__name__)
            return _refuse("HANDOFF_UNAVAILABLE",
                           "Handoff control is temporarily unavailable.", 500)

    return wrapped


def _expected_version(body):
    """The optimistic-concurrency token, straight from the request body.

    Absent is a 400, never a read-modify-write: a caller that does not say
    which version it read must not overwrite whoever wrote last.
    """
    value = body.get("expected_version")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, _refuse("EXPECTED_VERSION_REQUIRED",
                             "expected_version is required and must be a non-negative integer.", 400)
    return value, None


def _supervisor_override(body):
    # Only a literal JSON true asks to act over the assignee. "true", 1 and
    # "yes" do not: widening an authority flag by coercion is how an override
    # gets requested by accident.
    return body.get("supervisor_override") is True


def _load_own_control(conversation_id, actor, chatbot_id):
    """Bind every handoff operation to the company and verified chatbot.

    A company may own several bots. Access to the requested bot must not
    authorize a conversation on another bot, including an archived one.
    """
    control = handoff_control_repository.load(conversation_id)
    if not isinstance(control, handoff_service.ConversationControl):
        return None, _refuse(handoff_service.CONTROL_UNREADABLE,
                             "This conversation's control state could not be read.", 503)
    if control.company_id != actor.company_id:
        return None, _refuse(handoff_service.CROSS_TENANT,
                             "This conversation belongs to another company.", 403)
    if control.chatbot_id != chatbot_id:
        return None, _refuse("CHATBOT_MISMATCH",
                             "This conversation does not belong to the requested chatbot.", 403)
    return control, None


def _create_internal_note(conversation_id, chatbot_id, actor, text):
    """Persist a staff-only note through 060's writer function.

    ponytail: the one Supabase call in this module. It belongs in app/database
    beside the other repositories; the RPC contract is the seam, so moving it
    later is a one-line change.
    """
    response = supabase.rpc("create_conversation_internal_note", {
        "p_conversation_id": conversation_id,
        "p_chatbot_id": chatbot_id,
        # The author is the authenticated session; the function re-derives the
        # company from the conversation and refuses a foreign author itself.
        "p_author_user_id": actor.user_id,
        "p_note_text": text,
    }).execute()
    outcome = response.data
    # Only an explicit created:true is a write. A null payload, a list or a
    # truthy-but-not-True value all mean "not stored".
    return outcome if isinstance(outcome, dict) else {}


@agent_blueprint.route("/api/conversations/<int:conversation_id>/handoff/claim", methods=["POST"])
@token_required
@_handoff_staff_route
def handoff_claim(conversation_id, actor, chatbot_id, body):
    verify_chatbot_access(chatbot_id)
    version, refusal = _expected_version(body)
    if refusal is not None:
        return refusal
    with conversation_delivery_lock(conversation_id):
        _, refusal = _load_own_control(conversation_id, actor, chatbot_id)
        if refusal is not None:
            return refusal
        return _handoff_json(_handoff.claim(conversation_id, actor, expected_version=version))


@agent_blueprint.route("/api/conversations/<int:conversation_id>/handoff/assign", methods=["POST"])
@token_required
@_handoff_staff_route
def handoff_assign(conversation_id, actor, chatbot_id, body):
    verify_chatbot_access(chatbot_id)
    version, refusal = _expected_version(body)
    if refusal is not None:
        return refusal
    to_user_id = body.get("to_user_id")
    if isinstance(to_user_id, bool) or not isinstance(to_user_id, int) or to_user_id <= 0:
        return _refuse("TO_USER_ID_REQUIRED",
                       "to_user_id is required and must be a positive integer.", 400)
    with conversation_delivery_lock(conversation_id):
        _, refusal = _load_own_control(conversation_id, actor, chatbot_id)
        if refusal is not None:
            return refusal
        return _handoff_json(_handoff.assign(
            conversation_id, actor, to_user_id=to_user_id, expected_version=version,
            supervisor_override=_supervisor_override(body)))


@agent_blueprint.route("/api/conversations/<int:conversation_id>/handoff/resolve", methods=["POST"])
@token_required
@_handoff_staff_route
def handoff_resolve(conversation_id, actor, chatbot_id, body):
    verify_chatbot_access(chatbot_id)
    version, refusal = _expected_version(body)
    if refusal is not None:
        return refusal
    with conversation_delivery_lock(conversation_id):
        _, refusal = _load_own_control(conversation_id, actor, chatbot_id)
        if refusal is not None:
            return refusal
        return _handoff_json(_handoff.resolve(
            conversation_id, actor, expected_version=version,
            supervisor_override=_supervisor_override(body)))


@agent_blueprint.route("/api/conversations/<int:conversation_id>/handoff/reopen", methods=["POST"])
@token_required
@_handoff_staff_route
def handoff_reopen(conversation_id, actor, chatbot_id, body):
    verify_chatbot_access(chatbot_id)
    version, refusal = _expected_version(body)
    if refusal is not None:
        return refusal
    _, refusal = _load_own_control(conversation_id, actor, chatbot_id)
    if refusal is not None:
        return refusal
    with conversation_delivery_lock(conversation_id):
        # reopen() carries no actor -- the customer's message is what reopens
        # the work -- so it is told which company it acts for. That is the
        # authenticated session, the same value the actor was built from,
        # never anything off the request body.
        return _handoff_json(_handoff.reopen(
            conversation_id, company_id=actor.company_id, expected_version=version))


@agent_blueprint.route("/api/conversations/<int:conversation_id>/handoff/resume-ai", methods=["POST"])
@token_required
@_handoff_staff_route
def handoff_resume_ai(conversation_id, actor, chatbot_id, body):
    verify_chatbot_access(chatbot_id)
    version, refusal = _expected_version(body)
    if refusal is not None:
        return refusal
    with conversation_delivery_lock(conversation_id):
        _, refusal = _load_own_control(conversation_id, actor, chatbot_id)
        if refusal is not None:
            return refusal
        return _handoff_json(_handoff.resume_ai(
            conversation_id, actor, expected_version=version,
            supervisor_override=_supervisor_override(body)))


@agent_blueprint.route("/api/conversations/<int:conversation_id>/handoff/notes", methods=["POST"])
@token_required
@_handoff_staff_route
def handoff_note(conversation_id, actor, chatbot_id, body):
    """A staff-only note. It carries no expected_version because it changes no
    control state, and it never reaches save_message() or a provider -- that is
    the whole of what makes it internal."""
    verify_chatbot_access(chatbot_id)
    _, refusal = _load_own_control(conversation_id, actor, chatbot_id)
    if refusal is not None:
        return refusal
    text = body.get("text")
    authorised = _handoff.record_internal_note(conversation_id, actor, text=text)
    if not authorised.ok:
        return _handoff_json(authorised)
    outcome = _create_internal_note(conversation_id, chatbot_id, actor, text)
    if outcome.get("created") is not True:
        reason = outcome.get("reason") or "NOTE_UNWRITABLE"
        message, status = _NOTE_REFUSALS.get(reason, ("The note could not be stored.", 503))
        return _refuse(reason, message, status)
    return _handoff_json(authorised, note=outcome.get("note"))


@agent_blueprint.route("/api/conversations/<int:conversation_id>/handoff/state", methods=["GET"])
@token_required
@_handoff_staff_route
def handoff_state(conversation_id, actor, chatbot_id, body):
    verify_chatbot_access(chatbot_id)
    control, refusal = _load_own_control(conversation_id, actor, chatbot_id)
    if refusal is not None:
        return refusal
    return jsonify({
        "status": "success", "code": "CONTROL_READ",
        "message": "Current handoff control state.",
        "data": {"control": _control_json(control), "override": False},
    }), 200
