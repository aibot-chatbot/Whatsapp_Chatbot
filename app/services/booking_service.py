"""booking_service.py - Rules for chat-collected bookings.

A chat request is recorded as 'requested'; only staff can confirm, cancel or complete it.
Everything that came out of the model or the customer is treated as untrusted text:
tenant, status, version and source are never taken from it. A new request rewrites the
company's one living CSV and tells the owner, off the chat reply path and best effort: a
storage or mail failure must never lose a booking, fail a staff update or slow a customer.
Chat requests are capped per conversation and per company, so a flood of made-up
conversations cannot flood the queue, the owner's inbox or the storage writes.
"""

import hashlib
import logging
import os
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone

from app.database import booking_availability_repository as availability_repo
from app.database import service_booking_repository as repo
from app.database.user_repository import get_company_billing_contact
from app.services.bookings_csv_service import refresh_company_csv
from app.services.client_job_limits import allow_client_email
from app.services.receipt_email_service import send_notice_email

logger = logging.getLogger(__name__)

KINDS = ("booking", "reservation", "appointment", "other")
STATUSES = ("requested", "confirmed", "cancelled", "completed")
TRANSITIONS = {
    "requested": frozenset({"confirmed", "cancelled"}),
    "confirmed": frozenset({"cancelled", "completed"}),
    "cancelled": frozenset(),
    "completed": frozenset(),
}
EDITABLE = frozenset({"status", "kind", "customer_name", "service_name", "scheduled_for", "party_size", "notes"})
# A repeat of a request that is still alive is the same request; a cancelled or completed one is not.
OPEN_STATUSES = frozenset({"requested", "confirmed"})

MAX_REQUESTS_PER_CONVERSATION_PER_HOUR = 3
MAX_CHAT_REQUESTS_PER_COMPANY_PER_HOUR = 20  # bounds rows, CSV rewrites and owner emails per company
NOTICE_WINDOW_MINUTES = 30                   # at most one owner email per company per window
_MAX_KEY_ATTEMPTS = 5
_LIMITS = {"customer_name": 120, "customer_phone": 40, "customer_ref": 100, "channel": 30,
           "service_name": 150, "notes": 1000}
_MAX_PARTY_SIZE = 10_000
MAX_SEATS_PER_TIME = 1000  # booking_slots.capacity's upper bound (data/073)
_MYT = timezone(timedelta(hours=8))  # Malaysia has no DST; customers say local times
_DROPPED = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})  # control, format (bidi), surrogate, private, unassigned
# A date alone ("2026-10-05") would silently become midnight, so a time is required.
_WHEN = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?")


class BookingError(Exception):
    status_code = 400
    code = "booking_error"


class BookingValidationError(BookingError):
    code = "invalid_booking"


class BookingNotFound(BookingError):
    status_code = 404
    code = "booking_not_found"


class BookingConflict(BookingError):
    status_code = 409
    code = "booking_changed"


# --- cleaning and parsing -----------------------------------------------------

def clean_text(value, maximum):
    """One line of printable text, or None. Strips control and bidi characters and truncates."""
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        return None
    pieces = []
    for char in str(value):
        if char.isspace():
            pieces.append(" ")
        elif unicodedata.category(char) not in _DROPPED:
            pieces.append(char)
    return " ".join("".join(pieces).split())[:maximum].strip() or None


def clean_party_size(value):
    """A whole number from 1 to 10000, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if type(value) is int and 1 <= value <= _MAX_PARTY_SIZE:
        return value
    return None


def parse_when(value, now, *, bounded):
    """A datetime in UTC, or None. Needs a date and a time; naive times are Malaysia time.

    bounded=True is for customer chat (a plausible upcoming time); staff edits only need
    a sane date, because they also record bookings that already happened.
    """
    text = clean_text(value, 100)
    if not text or not _WHEN.fullmatch(text):
        return None
    try:
        moment = datetime.fromisoformat(text.replace(" ", "T", 1).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=_MYT)
        moment = moment.astimezone(timezone.utc)
    except (ValueError, OverflowError):  # e.g. month 13, or year 0001 shifted below the minimum
        return None
    earliest, latest = (timedelta(days=1), timedelta(days=730)) if bounded else (timedelta(days=1826), timedelta(days=1826))
    return moment if now - earliest <= moment <= now + latest else None


def _utcnow(now):
    return now or datetime.now(timezone.utc)


def _best_effort(function, *args):
    try:
        function(*args)
    except Exception as exc:
        logger.warning("%s failed for company %s: %s",
                       getattr(function, "__name__", "step"), args[0] if args else "?", type(exc).__name__)


def _background(function, *args):
    """Run a best-effort side effect off the caller's thread. A restart can drop it; the next change repairs it."""
    threading.Thread(target=_best_effort, args=(function, *args), daemon=True).start()


# --- a chat request ---------------------------------------------------------------

def _intake_key(conversation_id, kind, service, when_key, party_size, day):
    raw = "|".join([str(conversation_id), kind, (service or "").lower(), when_key, str(party_size or ""), day])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _open_duplicate(company_id, key):
    existing = repo.get_booking_by_intake_key(company_id, key)
    return existing if existing and existing.get("status") in OPEN_STATUSES else None


def _insert(row, base_key):
    """Insert the request. Returns (booking, created).

    A replay of a request that is still open returns that booking without creating another.
    One that was cancelled or completed does not block a fresh request: it gets a new key.
    """
    for attempt in range(1, _MAX_KEY_ATTEMPTS + 1):
        key = base_key if attempt == 1 else f"{base_key}-{attempt}"
        booking = repo.create_booking(dict(row, intake_key=key))
        if booking is not None:
            return booking, True
        existing = repo.get_booking_by_intake_key(row["company_id"], key)
        if existing is None or existing.get("status") in OPEN_STATUSES:
            return existing, False
    return None, False


def record_chat_request(*, company_id, chatbot_id, conversation_id, channel, customer_phone,
                        customer_ref, fields, now=None):
    """Record one customer-confirmed request as 'requested'. None when it was not recorded.

    The scope (company, chatbot, conversation, channel, phone) comes from the caller, which
    derives it server-side; `fields` is the untrusted model output and only contributes the
    booking details. A repeat of a request that is still open returns it quietly. Over a
    limit, only such a repeat is returned; anything new is refused.
    """
    now = _utcnow(now)
    fields = fields if isinstance(fields, dict) else {}
    kind = str(fields.get("kind") or "").strip().lower()
    kind = kind if kind in KINDS else "other"
    service = clean_text(fields.get("service"), _LIMITS["service_name"])
    when_text = clean_text(fields.get("when"), 100)
    moment = parse_when(when_text, now, bounded=True)
    if service is None and moment is None:
        raise BookingValidationError("A booking needs at least what to book or a usable time.")

    notes = clean_text(fields.get("notes"), _LIMITS["notes"])
    if when_text and moment is None:
        # Keep what the customer said instead of losing a real request over an odd time.
        notes = clean_text("Requested time: " + when_text + (" | " + notes if notes else ""), _LIMITS["notes"])
    party_size = clean_party_size(fields.get("party_size"))
    scheduled_for = moment.isoformat() if moment else None
    key = _intake_key(conversation_id, kind, service, scheduled_for or (when_text or "").lower(), party_size,
                      now.astimezone(_MYT).date().isoformat())

    since = (now - timedelta(hours=1)).isoformat()
    if (repo.count_recent_for_conversation(company_id, conversation_id, since) >= MAX_REQUESTS_PER_CONVERSATION_PER_HOUR
            or repo.count_recent_for_company(company_id, since) >= MAX_CHAT_REQUESTS_PER_COMPANY_PER_HOUR):
        logger.warning("Booking request refused: limit reached (company %s, conversation %s)", company_id, conversation_id)
        return _open_duplicate(company_id, key)

    row = {
        "company_id": company_id, "chatbot_id": chatbot_id, "conversation_id": conversation_id,
        "kind": kind, "status": "requested", "source": "chat",
        "customer_name": clean_text(fields.get("name"), _LIMITS["customer_name"]),
        "customer_phone": clean_text(customer_phone, _LIMITS["customer_phone"]),
        "customer_ref": clean_text(customer_ref, _LIMITS["customer_ref"]),
        "channel": clean_text(channel, _LIMITS["channel"]),
        "service_name": service, "scheduled_for": scheduled_for, "party_size": party_size, "notes": notes,
    }
    booking, created = _insert(row, key)
    if created:
        _background(refresh_company_csv, company_id)
        _background(_notify_if_first_in_window, company_id, booking, now)
    return booking


def reserve_chat_slot(*, company_id, chatbot_id, conversation_id, channel, customer_phone,
                      customer_ref, fields, slot_id, confirm, now=None):
    """Book one listed time for a customer who confirmed it in chat (availability booking).

    The seat is taken by the database's booking_reserve, which locks the slot, so the model
    can never overbook or book a closed, past or foreign slot. Scope comes from the caller,
    as in record_chat_request; `fields` only contributes the name, party size and notes.
    Returns {"outcome": confirmed | held | replayed | full | unavailable | limited, ...}.
    """
    now = _utcnow(now)
    fields = fields if isinstance(fields, dict) else {}
    party_size = clean_party_size(fields.get("party_size")) or 1
    if party_size > MAX_SEATS_PER_TIME:
        return {"outcome": "full"}  # no time can ever seat this many
    name = clean_text(fields.get("name"), _LIMITS["customer_name"])
    # No date in the key: the slot fixes the time, so the same marker sent again after midnight
    # is still the same booking. The name keeps two people booked one after the other apart.
    key, existing = _slot_key(company_id, _intake_key(
        conversation_id, "slot", f"S{slot_id}", (name or "").casefold(), party_size, ""))
    if existing is not None:
        return {"outcome": "replayed", "booking": existing}

    since = (now - timedelta(hours=1)).isoformat()
    if (key is None
            or repo.count_recent_for_conversation(company_id, conversation_id, since) >= MAX_REQUESTS_PER_CONVERSATION_PER_HOUR
            or repo.count_recent_for_company(company_id, since) >= MAX_CHAT_REQUESTS_PER_COMPANY_PER_HOUR):
        logger.warning("Slot booking refused: limit reached (company %s, conversation %s)", company_id, conversation_id)
        return {"outcome": "limited"}

    booking = {
        "intake_key": key, "conversation_id": conversation_id, "kind": "booking",
        "customer_name": name,
        "customer_phone": clean_text(customer_phone, _LIMITS["customer_phone"]),
        "customer_ref": clean_text(customer_ref, _LIMITS["customer_ref"]),
        "channel": clean_text(channel, _LIMITS["channel"]),
        "notes": clean_text(fields.get("notes"), _LIMITS["notes"]),
    }
    result = availability_repo.reserve(company_id, chatbot_id, slot_id, party_size, confirm, booking)
    result = result if isinstance(result, dict) else {}
    if result.get("outcome") in ("confirmed", "held"):
        _background(refresh_company_csv, company_id)
        _background(_notify_if_first_in_window, company_id, result.get("booking"), now)
    return result


def _slot_key(company_id, base_key):
    """The key for a new seat request, and the open booking already made under it, if any.

    As in _insert, a cancelled or completed booking does not block booking the same time
    again: the request moves on to the next key.
    """
    for attempt in range(1, _MAX_KEY_ATTEMPTS + 1):
        key = base_key if attempt == 1 else f"{base_key}-{attempt}"
        existing = repo.get_booking_by_intake_key(company_id, key)
        if existing is None:
            return key, None
        if existing.get("status") in OPEN_STATUSES:
            return key, existing
    return None, None


def _notify_if_first_in_window(company_id, booking, now):
    """Email the owner once per window. Sent by the request that was first in it, so a race
    between two requests in the same instant still produces exactly one notice."""
    window_start = now.replace(minute=now.minute - now.minute % NOTICE_WINDOW_MINUTES, second=0, microsecond=0)
    created_at = booking.get("created_at") if isinstance(booking, dict) else None
    if created_at:
        earlier = repo.count_recent_for_company(company_id, window_start.isoformat(), before_iso=created_at)
        if earlier > 0:
            return
    elif repo.count_recent_for_company(company_id, window_start.isoformat()) > 1:
        return
    notify_owner_of_new_request(company_id)


def notify_owner_of_new_request(company_id):
    """Tell the account owner there is something to confirm. Names no customer."""
    contact = get_company_billing_contact(company_id)
    if not contact:
        return
    # Customer-triggered, so it counts against the Client's hourly email budget.
    if not allow_client_email(company_id, "booking_notice"):
        return
    base = (os.getenv("FRONTEND_URL") or "").rstrip("/")
    send_notice_email(
        contact["email"],
        title="New booking request",
        message=("A customer asked for a booking through your chatbot. Open Bookings to review and "
                 "confirm it. Your bookings file updates automatically."),
        label="Bookings",
        footer=("You are receiving this because you are the account owner. Booking requests also "
                "appear in your Omnexa dashboard. You get at most one of these emails every "
                f"{NOTICE_WINDOW_MINUTES} minutes."),
        recipient_name=contact["full_name"],
        action_label="Open bookings" if base else None,
        action_url=(base + "/bookings.html") if base else None,
    )


# --- staff ------------------------------------------------------------------------

def list_for_company(company_id, *, chatbot_id=None, status=None, limit=50, offset=0):
    if status is not None and status not in STATUSES:
        raise BookingValidationError("Unknown status.")
    return repo.list_bookings(company_id, chatbot_id=chatbot_id, status=status, limit=limit, offset=offset)


def set_intake_enabled(company_id, chatbot_id, enabled):
    """Switch chat intake on or off for one of the company's chatbots. False when it is not theirs."""
    return repo.set_intake_enabled(company_id, chatbot_id, enabled)


def _text_change(value):
    if value is not None and not isinstance(value, str):
        raise BookingValidationError("That field must be text.")
    return value


def _normalized_changes(current, changes, now):
    unknown = set(changes) - EDITABLE
    if unknown or not changes:
        raise BookingValidationError("Nothing to change." if not changes else "These fields cannot be changed.")
    if current["status"] in ("cancelled", "completed"):
        raise BookingValidationError("A finished booking cannot be changed.")
    if current.get("slot_id") and {"scheduled_for", "party_size"} & set(changes):
        # Its seats were counted for that exact time and party; the database refuses this too.
        raise BookingValidationError("This booking holds a seat. Cancel it and book a new time instead.")

    normalized = {}
    if "status" in changes:
        target = changes["status"]
        if not isinstance(target, str) or target not in TRANSITIONS[current["status"]]:
            raise BookingValidationError(f"A {current['status']} booking cannot be moved to that status.")
        normalized["status"] = target
        if target == "confirmed":
            normalized["confirmed_at"] = now.isoformat()
        if target == "cancelled":
            normalized["cancelled_at"] = now.isoformat()
    if "kind" in changes:
        if not isinstance(changes["kind"], str) or changes["kind"] not in KINDS:
            raise BookingValidationError("Unknown kind.")
        normalized["kind"] = changes["kind"]
    for field in ("customer_name", "service_name", "notes"):
        if field in changes:
            normalized[field] = clean_text(_text_change(changes[field]), _LIMITS[field])
    if "party_size" in changes:
        size = clean_party_size(changes["party_size"])
        if changes["party_size"] is not None and size is None:
            raise BookingValidationError("Party size must be a whole number from 1 to 10000.")
        normalized["party_size"] = size
    if "scheduled_for" in changes:
        when = _text_change(changes["scheduled_for"])
        if when in (None, ""):
            normalized["scheduled_for"] = None
        else:
            moment = parse_when(when, now, bounded=False)
            if moment is None:
                raise BookingValidationError("That date and time could not be understood. Include both, like 2026-10-06 20:30.")
            normalized["scheduled_for"] = moment.isoformat()
    return normalized


def update_booking(company_id, booking_id, expected_version, changes, now=None):
    """Apply a staff edit or status change, then rewrite the company's CSV."""
    now = _utcnow(now)
    current = repo.get_booking(company_id, booking_id)
    if current is None:
        raise BookingNotFound("Booking not found.")
    if current["version"] != expected_version:
        raise BookingConflict("This booking was changed by someone else. Reload and try again.")
    normalized = _normalized_changes(current, changes, now)
    updated = repo.update_booking(company_id, booking_id, expected_version, normalized)
    if updated is None:
        raise BookingConflict("This booking was changed by someone else. Reload and try again.")
    _best_effort(refresh_company_csv, company_id)
    return updated
