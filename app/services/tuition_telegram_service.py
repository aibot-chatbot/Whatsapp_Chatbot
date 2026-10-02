"""Explicit, stateless trial-booking buttons for verified Telegram private chats."""
import base64
from datetime import datetime
import logging
import os
import re
from uuid import UUID
from zoneinfo import ZoneInfo

from app.database.conversation_repository import get_conversation_by_id_and_chatbot
from app.database.agent_action_repository import is_conversation_escalated
from app.database.message_repository import save_message
from app.services import tuition_service as trials
from app.services.billing_guard import can_use_plan_feature
from app.services.channel_delivery_service import get_bound_channel, delivery_accepted
from app.services.company_status_service import ensure_company_operational
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.handoff_service import handoff_control_enabled

PREFIX = "tt:"
PAGE_SIZE = 8
logger = logging.getLogger(__name__)


def is_tuition_update(update):
    callback = update.get("callback_query") or {}
    text = (update.get("message") or {}).get("text")
    return (isinstance(callback.get("data"), str) and callback["data"].startswith(PREFIX)
            or isinstance(text, str) and (text.startswith(PREFIX) or re.match(r"^/trial(?:\s|$)", text)))


def _pack(*ids):
    return base64.urlsafe_b64encode(b"".join(UUID(value).bytes for value in ids)).decode().rstrip("=")


def _unpack(value, count=1):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid trial button")
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if len(raw) != 16 * count or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
        raise ValueError("Invalid trial button")
    return [str(UUID(bytes=raw[i:i + 16])) for i in range(0, len(raw), 16)]


def _button(label, action, payload=""):
    data = PREFIX + action + (":" + payload if payload else "")
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Trial button exceeds Telegram's limit")
    return [{"text": _plain(label, 64), "callback_data": data}]


def _plain(value, limit=150):
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value))[:limit]


def _time(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Session timezone is missing")
    return date.astimezone(ZoneInfo("Asia/Kuala_Lumpur")).strftime("%d %b %Y, %H:%M MYT")


def _reminder_text(requested, *, reviewing=False):
    if not requested:
        return "No reminder will be sent."
    if os.getenv("TUITION_REMINDERS_ENABLED", "false").lower() != "true":
        return "Reminder consent will be saved, but automated reminders are currently unavailable." if reviewing else "Reminder consent saved; automated reminders are currently unavailable."
    return "Telegram reminder requested." if reviewing else "Telegram reminder enabled."


def _guard(conversation, channel, recipient, *, require_trials=True):
    """Refresh identity and policy at each operation and immediately before sending."""
    current = get_conversation_by_id_and_chatbot(conversation["id"], channel["chatbot_id"])
    if (not current or current.get("conversation_status") != "open"
            or current.get("source_channel") != "telegram"
            or current.get("source_channel_id") != channel["id"]
            or str(current.get("source_provider_id")) != str(channel["telegram_bot_id"])
            or current.get("platform_user_id") != recipient):
        raise trials.TuitionError("Trial conversation is unavailable.", "tuition_scope_denied", 404)
    bound = get_bound_channel(current)
    if bound.get("company_id") != channel["company_id"] or bound.get("id") != channel["id"]:
        raise trials.TuitionError("Trial channel is unavailable.", "tuition_scope_denied", 404)
    ensure_company_operational(bound["company_id"])
    can_use_plan_feature(bound["company_id"], "ai_generated_reports")
    if is_conversation_escalated(current["id"], bound["chatbot_id"], conversation=current):
        raise trials.TuitionError("Staff are handling this conversation.", "tuition_human_controlled", 409)
    if handoff_control_enabled():
        from app.database.handoff_control_repository import load
        control = load(current["id"])
        if (control is None or control.company_id != bound["company_id"]
                or control.chatbot_id != bound["chatbot_id"] or control.mode != "ai_active"):
            raise trials.TuitionError("Staff control could not be cleared.", "tuition_human_controlled", 409)
    if require_trials:
        trials.require_trial_context(bound["company_id"], bound["chatbot_id"])
    return current, bound


def _send(conversation, channel, recipient, text, buttons=None, *, require_trials=True):
    from app.utils.telegram_utils import send_telegram_message
    with conversation_delivery_lock(conversation["id"]):
        current, bound = _guard(conversation, channel, recipient, require_trials=require_trials)
        try:
            result = send_telegram_message(bound["bot_token"], recipient, text,
                reply_markup={"inline_keyboard": buttons} if buttons else None, parse_mode=None)
        except Exception:
            result = None
        receipt = result.get("result") if isinstance(result, dict) else None
        receipt = receipt if isinstance(receipt, dict) else {}
        chat = receipt.get("chat")
        accepted = (delivery_accepted("telegram", result) and type(receipt.get("message_id")) is int
                    and receipt["message_id"] > 0 and isinstance(chat, dict) and str(chat.get("id")) == recipient)
        try:
            save_message(conversation_id=current["id"], sender_type="bot", message_text=text,
                ai_generated=False, delivery_status="sent" if accepted else "failed",
                last_error=None if accepted else "Trial reply delivery is unconfirmed; review before retrying.")
        except Exception:
            logger.warning("Trial reply transcript was not recorded; delivery must not be retried")
        # The webhook update was already claimed. Ambiguous sends are never retried here.
        return accepted


def _page(rows, offset, make_button, next_action, next_prefix=""):
    if not offset.isdigit() or int(offset) > 1000:
        raise ValueError("Invalid page")
    start = int(offset)
    buttons = [make_button(row) for row in rows[start:start + PAGE_SIZE]]
    if start + PAGE_SIZE < len(rows):
        buttons.append(_button("More", next_action, next_prefix + str(start + PAGE_SIZE)))
    buttons.append(_button("My bookings", "b"))
    return buttons


def _find(rows, key):
    row = next((row for row in rows if row["id"] == key), None)
    if row is None:
        raise trials.TuitionError("This trial selection is no longer available.", "tuition_scope_denied", 404)
    return row


def _menu(scope, offset="0"):
    participants = trials.list_participants(**scope)
    return ("Choose a participant, or send /trial followed by their name to add one. No place is reserved yet.",
        _page(participants, offset, lambda p: _button(p["label"], "p", _pack(p["id"])), "m"))


def _bookings(scope, offset="0"):
    bookings = trials.list_bookings(**scope)
    if not bookings:
        return "You have no trial bookings in this chat. Send /trial to begin.", [_button("Choose participant", "m")]
    return ("Your trial bookings. Choose one to view its status, cancel, or change its session.",
        _page(bookings, offset, lambda b: _button(f"{b.get('participant_label', 'Participant')} · {b['status']} · {b['id'][:8]}",
            "v", _pack(b["id"])), "b"))


def _sessions(scope, entity_id, *, reschedule=False, offset="0"):
    if reschedule:
        booking = _find(trials.list_bookings(**scope), entity_id)
        if booking["status"] != "confirmed":
            raise ValueError("Only confirmed trials can be rescheduled")
    else:
        _find(trials.list_participants(**scope), entity_id)
    sessions = trials.list_sessions(company_id=scope["company_id"], chatbot_id=scope["chatbot_id"])
    sessions = [row for row in sessions if row.get("available_trial_seats", 0) > 0
                and (not reschedule or row["id"] != booking["session_id"])]
    if not sessions:
        return "There are no available trial places. Please contact the centre.", [_button("My bookings", "b")]
    return ("Choose an available session. Times are in Malaysia time; availability is checked again when you confirm.",
        _page(sessions, offset, lambda s: _button(f"{s['class_name']} · {_time(s['starts_at'])}",
            "t" if reschedule else "s", _pack(entity_id, s["id"])), "r" if reschedule else "p", _pack(entity_id) + ":"))


def _callback_reply(scope, action, args, callback_id):
    if action in {"m", "b"}:
        return (_menu if action == "m" else _bookings)(scope, args[0] if args else "0")
    if action in {"p", "r"}:
        return _sessions(scope, _unpack(args[0])[0], reschedule=action == "r", offset=args[1] if len(args) > 1 else "0")
    if action in {"s", "t", "y", "n", "Y", "N"}:
        entity_id, session_id = _unpack(args[0], 2)
        reschedule = action in {"t", "Y", "N"}
        booking = _find(trials.list_bookings(**scope), entity_id) if reschedule else None
        participant_id = booking["participant_id"] if booking else entity_id
        _find(trials.list_participants(**scope), participant_id)
        session = _find(trials.list_sessions(company_id=scope["company_id"], chatbot_id=scope["chatbot_id"]), session_id)
        if action in {"s", "t"}:
            return (f"{_plain(session['class_name'])}\n{_time(session['starts_at'])}\n"
                "Would you like one Telegram reminder about 24 hours before this trial? A reminder is available only when booked more than 24 hours ahead.",
                [_button("Yes, remind me", "Y" if reschedule else "y", args[0]),
                 _button("No reminder", "N" if reschedule else "n", args[0])])
        prepared = trials.prepare_trial(**scope, participant_id=participant_id, session_id=session_id,
            booking_id=booking["id"] if booking else None, reminder_consent=action in {"y", "Y"})
        token = prepared["confirmation_token"]
        packed = _pack(token[:36], token[36:])
        reminder = _reminder_text(prepared.get("reminder_supported") and prepared["reminder_consent"], reviewing=True)
        return (f"Review {'session change' if booking else 'trial'} for {_plain(prepared['participant']['label'], 80)}\n"
            f"{_plain(session['class_name'])}\n{_time(prepared['session']['starts_at'])}\n{reminder}\n"
            f"Confirm before {_time(prepared['expires_at'])}. No place is reserved until confirmation.",
            [_button("Confirm session change" if booking else "Confirm trial", "c", packed), _button("Back to my bookings", "b")])
    if action == "c":
        token = "".join(_unpack(args[0], 2))
        result = trials.confirm_trial(**scope, confirmation_token=token)
        booking, session = result["booking"], result["session"]
        if booking["status"] != "confirmed":
            return f"This booking is {booking['status']}. Send /trial list to view your bookings.", [_button("My bookings", "b")]
        reminder = _reminder_text(booking.get("reminder_enabled"))
        return (f"Trial confirmed. Booking: {booking['id']}\n{_time(session['starts_at'])}\n{reminder}", [_button("My bookings", "b")])
    if action in {"v", "x", "d"}:
        booking_id = _unpack(args[0])[0]
        booking = _find(trials.list_bookings(**scope), booking_id)
        if action == "d":
            if len(args) != 2 or str(booking["version"]) != args[1]:
                raise ValueError("Booking changed; review it again")
            cancelled = trials.cancel_trial(**scope, booking_id=booking_id, expected_version=int(args[1]),
                client_message_id="tg:" + callback_id)
            return f"Trial booking {cancelled['id']} is {cancelled['status']}.", [_button("My bookings", "b")]
        if action == "x":
            if booking["status"] != "confirmed":
                raise ValueError("This booking is no longer confirmed")
            return (f"Cancel trial booking {booking_id} for {_plain(booking.get('participant_label', 'participant'), 80)}?",
                [_button("Confirm cancellation", "d", args[0] + ":" + str(booking["version"])), _button("Keep booking", "b")])
        buttons = [_button("My bookings", "b")]
        if booking["status"] == "confirmed":
            buttons = [_button("Change session", "r", args[0]), _button("Cancel trial", "x", args[0])] + buttons
        sessions = trials.list_sessions(company_id=scope["company_id"], chatbot_id=scope["chatbot_id"])
        session = next((s for s in sessions if s["id"] == booking["session_id"]), None)
        detail = f"\n{_plain(session['class_name'])}\n{_time(session['starts_at'])}" if session else ""
        return f"Booking {booking_id}\n{_plain(booking.get('participant_label', 'Participant'), 80)} · {booking['status']}{detail}", buttons
    raise ValueError("Unknown trial button")


def handle_tuition_update(update, *, conversation, channel):
    """Consume only /trial and reserved buttons; ordinary text stays on its existing path."""
    if not is_tuition_update(update):
        return False
    callback = update.get("callback_query")
    message = (callback or {}).get("message") if callback else update.get("message")
    author = (callback or message or {}).get("from") or {}
    chat = (message or {}).get("chat") or {}
    recipient = str(chat.get("id"))
    if (chat.get("type") != "private" or type(chat.get("id")) is not int or chat["id"] <= 0
            or type(author.get("id")) is not int or author["id"] != chat["id"]):
        return True
    try:
        with conversation_delivery_lock(conversation["id"]):
            current, bound = _guard(conversation, channel, recipient)
            scope = {"company_id": bound["company_id"], "chatbot_id": bound["chatbot_id"], "conversation_id": current["id"]}
            if callback:
                data = callback["data"]
                # Telegram clients may submit arbitrary data. Require a button on
                # this bot's actual message, then still scope every ID in services.
                buttons = (message.get("reply_markup") or {}).get("inline_keyboard") or []
                if (len(data.encode("utf-8")) > 64 or not isinstance(callback.get("id"), str)
                        or len(callback["id"]) > 90 or not callback["id"]
                        or (message.get("from") or {}).get("is_bot") is not True
                        or str((message.get("from") or {}).get("id")) != str(bound["telegram_bot_id"])
                        or not any(b.get("callback_data") == data for row in buttons for b in row)):
                    raise ValueError("Invalid trial button origin")
            # Control interactions are not free-form customer text. Do not feed
            # them to the paid business-observation trigger. Booking outcomes
            # already have authoritative business_events in the RPC transaction.
            if callback:
                _, action, *args = callback["data"].split(":")
                text, buttons = _callback_reply(scope, action, args, callback["id"])
            elif message["text"].startswith(PREFIX):
                text, buttons = "Use the trial buttons, or send /trial to begin. Typed button codes cannot change bookings.", [_button("Choose participant", "m")]
            else:
                label = message["text"][6:].strip()
                if label.lower() == "list":
                    text, buttons = _bookings(scope)
                elif label:
                    participant = trials.create_participant(**scope, client_key="telegram:" + str(update["update_id"]), label=label)
                    text, buttons = _sessions(scope, participant["id"])
                else:
                    text, buttons = _menu(scope)
            _send(current, bound, recipient, text, buttons)
    except Exception as error:
        # No callback payload, token, provider URL, contact, or exception text in logs.
        logger.warning("Trial Telegram action declined (%s)", type(error).__name__)
        text = ("That trial selection expired or changed. Send /trial list to check your bookings, or /trial to start again."
                if isinstance(error, ValueError) and getattr(error, "status_code", 400) < 500
                and getattr(error, "code", "") not in {"tuition_industry_required", "tuition_disabled"}
                else "Trial booking is currently unavailable. Please contact the centre or try /trial later.")
        try:
            _send(conversation, channel, recipient, text, require_trials=False)
        except Exception:
            # A paused, disconnected, suspended or unverified conversation gets no automatic reply.
            pass
    return True
