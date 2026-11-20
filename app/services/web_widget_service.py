"""web_widget_service.py — website chat widget business logic.

Powers the embeddable chat bubble, the iframe embed and the public share
link. The widget is reached by unauthenticated visitors, so everything in
this module treats its input as hostile:

  * the chatbot is addressed by an unguessable `public_key`, never by id
  * an optional hostname allowlist restricts where the widget may be embedded
  * a per-session message cap limits AI credit burn from a public endpoint
  * only a whitelisted subset of the config is ever returned publicly
"""

import logging
import re
import secrets
from urllib.parse import urlparse

from app.database.bot_repository import get_bot_by_id
from app.database.agent_action_repository import is_conversation_escalated
from app.database.conversation_repository import find_widget_conversation, get_or_create_platform_conversation
from app.database.crm_lead_repository import create_crm_lead
from app.database.message_repository import (
    count_messages_by_conversation,
    get_widget_human_messages,
    save_message,
)
from app.database.web_widget_repository import (
    create_widget,
    get_widget_by_chatbot_id,
    get_widget_by_public_key,
    update_widget,
)
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.message_limits import MAX_MESSAGE_LENGTH

logger = logging.getLogger(__name__)

SOURCE_CHANNEL = "web"
PUBLIC_KEY_BYTES = 24

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_SESSION_ID_RE = re.compile(r"^web_[0-9a-zA-Z_-]{16,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Text fields the dashboard may update, with their maximum stored length.
_TEXT_FIELDS = {
    "display_name": 80,
    "subtitle": 120,
    "launcher_label": 40,
    "welcome_message": 1000,
    "input_placeholder": 80,
    "branding_text": 60,
    "lead_prompt": 300,
}

_COLOR_FIELDS = ("primary_color", "text_color")

_BOOL_FIELDS = (
    "is_enabled",
    "show_branding",
    "collect_lead",
    "lead_require_name",
    "lead_require_email",
    "lead_require_phone",
)

MAX_SUGGESTED_QUESTIONS = 4
MAX_ALLOWED_DOMAINS = 20


class WidgetError(Exception):
    """Raised for widget problems that map to a specific HTTP status."""

    def __init__(self, message, status=400, code="widget_error"):
        super().__init__(message)
        self.status = status
        self.code = code


# ── Key generation ────────────────────────────────────────────────────

def generate_public_key():
    return f"wgt_{secrets.token_urlsafe(PUBLIC_KEY_BYTES)}"


def generate_session_id():
    return f"web_{secrets.token_urlsafe(18)}"


# ── Dashboard-side operations ─────────────────────────────────────────

def ensure_widget(chatbot_id, company_id):
    """Return the config; new widgets wait for the owner's channel choice."""
    existing = get_widget_by_chatbot_id(chatbot_id, company_id)
    if existing:
        return existing

    bot = get_bot_by_id(chatbot_id, company_id)
    if not bot:
        raise WidgetError("Chatbot not found.", status=404, code="chatbot_not_found")

    defaults = {"is_enabled": False}
    bot_name = (bot.get("bot_name") or "").strip()
    if bot_name:
        defaults["display_name"] = bot_name[:80]

    bot_welcome = (bot.get("welcome_message") or "").strip()
    if bot_welcome:
        defaults["welcome_message"] = bot_welcome[:1000]

    created = create_widget(chatbot_id, company_id, generate_public_key(), defaults)
    if not created:
        raise WidgetError("Could not create the widget configuration.", status=500)

    return created


def _clean_domain(raw):
    """Reduce a user-entered origin to a bare lowercase hostname."""
    value = (raw or "").strip().lower()
    if not value:
        return None

    if "://" not in value:
        value = f"//{value}"

    host = urlparse(value).hostname
    if not host:
        return None

    return host


def _normalise_string_list(raw, max_items, max_length, cleaner=None):
    if raw is None:
        return None

    if isinstance(raw, str):
        raw = [part for part in re.split(r"[\n,]", raw)]

    if not isinstance(raw, list):
        raise WidgetError("Expected a list of strings.")

    cleaned = []
    for item in raw:
        if not isinstance(item, str):
            continue
        value = cleaner(item) if cleaner else item.strip()
        if not value:
            continue
        cleaned.append(value[:max_length])
        if len(cleaned) >= max_items:
            break

    # Preserve order, drop duplicates.
    return list(dict.fromkeys(cleaned))


def update_widget_settings(chatbot_id, company_id, payload):
    """Validate and persist dashboard-supplied widget settings."""
    ensure_widget(chatbot_id, company_id)

    payload = payload or {}
    updates = {}

    for field, max_length in _TEXT_FIELDS.items():
        if field in payload:
            value = payload.get(field)
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise WidgetError(f"'{field}' must be text.")
            updates[field] = value.strip()[:max_length]

    for field in _COLOR_FIELDS:
        if field in payload:
            value = (payload.get(field) or "").strip()
            if not _HEX_COLOR_RE.match(value):
                raise WidgetError(
                    f"'{field}' must be a hex colour such as #4F46E5."
                )
            updates[field] = value.upper()

    for field in _BOOL_FIELDS:
        if field in payload:
            updates[field] = bool(payload.get(field))

    if "launcher_position" in payload:
        value = (payload.get("launcher_position") or "").strip().lower()
        if value not in ("left", "right"):
            raise WidgetError("'launcher_position' must be 'left' or 'right'.")
        updates["launcher_position"] = value

    if "avatar_url" in payload:
        value = (payload.get("avatar_url") or "").strip()
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https"):
                raise WidgetError("'avatar_url' must be an http(s) URL.")
            value = value[:500]
        updates["avatar_url"] = value or None

    if "max_messages_per_session" in payload:
        try:
            value = int(payload.get("max_messages_per_session"))
        except (TypeError, ValueError):
            raise WidgetError("'max_messages_per_session' must be a number.")
        if not 1 <= value <= 500:
            raise WidgetError("'max_messages_per_session' must be between 1 and 500.")
        updates["max_messages_per_session"] = value

    if "suggested_questions" in payload:
        updates["suggested_questions"] = _normalise_string_list(
            payload.get("suggested_questions"),
            MAX_SUGGESTED_QUESTIONS,
            160,
        ) or []

    if "allowed_domains" in payload:
        updates["allowed_domains"] = _normalise_string_list(
            payload.get("allowed_domains"),
            MAX_ALLOWED_DOMAINS,
            253,
            cleaner=_clean_domain,
        ) or []

    if not updates:
        raise WidgetError("No valid settings were supplied.")

    updated = update_widget(chatbot_id, company_id, updates)
    if not updated:
        raise WidgetError("Could not update the widget configuration.", status=500)

    return updated


def regenerate_public_key(chatbot_id, company_id):
    """Issue a new public key, invalidating every existing embed snippet."""
    ensure_widget(chatbot_id, company_id)

    updated = update_widget(
        chatbot_id,
        company_id,
        {"public_key": generate_public_key()},
    )
    if not updated:
        raise WidgetError("Could not regenerate the widget key.", status=500)

    return updated


# ── Public (unauthenticated) operations ───────────────────────────────

def resolve_public_widget(public_key):
    """Load an enabled widget whose chatbot is still live."""
    widget = get_widget_by_public_key(public_key)
    if not widget:
        raise WidgetError("Chatbot not found.", status=404, code="widget_not_found")

    if not widget.get("is_enabled"):
        raise WidgetError(
            "This chatbot is not currently available.",
            status=403,
            code="widget_disabled",
        )

    bot = get_bot_by_id(widget["chatbot_id"])
    if not bot or not bot.get("is_active"):
        raise WidgetError(
            "This chatbot is not currently available.",
            status=403,
            code="chatbot_inactive",
        )

    return widget, bot


def is_origin_allowed(widget, origin_header):
    """An empty allowlist permits any origin; otherwise match the hostname."""
    allowed = widget.get("allowed_domains") or []
    if not allowed:
        return True

    host = _clean_domain(origin_header)
    if not host:
        # Direct navigation (share link) sends no Origin header.
        return True

    for entry in allowed:
        if host == entry or host.endswith(f".{entry}"):
            return True

    return False


def public_config(widget):
    """The only widget fields ever exposed to an unauthenticated visitor."""
    return {
        "public_key": widget.get("public_key"),
        "display_name": widget.get("display_name") or "Chat with us",
        "subtitle": widget.get("subtitle") or "",
        "primary_color": widget.get("primary_color") or "#4F46E5",
        "text_color": widget.get("text_color") or "#FFFFFF",
        "avatar_url": widget.get("avatar_url") or "",
        "launcher_position": widget.get("launcher_position") or "right",
        "launcher_label": widget.get("launcher_label") or "",
        "welcome_message": widget.get("welcome_message") or "",
        "input_placeholder": widget.get("input_placeholder") or "Type your message...",
        "suggested_questions": widget.get("suggested_questions") or [],
        "show_branding": bool(widget.get("show_branding", True)),
        "branding_text": widget.get("branding_text") or "",
        "collect_lead": bool(widget.get("collect_lead")),
        "lead_prompt": widget.get("lead_prompt") or "",
        "lead_require_name": bool(widget.get("lead_require_name")),
        "lead_require_email": bool(widget.get("lead_require_email")),
        "lead_require_phone": bool(widget.get("lead_require_phone")),
        "max_messages_per_session": widget.get("max_messages_per_session") or 50,
    }


def validate_session_id(session_id):
    value = session_id.strip() if isinstance(session_id, str) else ""
    if not _SESSION_ID_RE.match(value):
        raise WidgetError("Invalid session.", status=400, code="invalid_session")
    return value


def read_staff_messages(widget, session_id, after_id=0):
    """Read one capability-scoped page; never create a conversation on polling."""
    session_id = validate_session_id(session_id)
    if isinstance(after_id, bool) or not isinstance(after_id, int) or not 0 <= after_id <= 9223372036854775807:
        raise WidgetError("Invalid message cursor.", code="invalid_cursor")
    page = {"messages": [], "last_message_id": after_id,
            "has_more": False, "awaiting_human": False}
    conversation = find_widget_conversation(widget["chatbot_id"], session_id)
    if conversation is None:
        return page
    # The staff writer uses this same lock: the cursor must not pass a row
    # whose ID was allocated earlier but whose transaction is still pending.
    with conversation_delivery_lock(conversation["id"]):
        rows = get_widget_human_messages(conversation["id"], after_id, limit=51)
        page["awaiting_human"] = is_conversation_escalated(
            conversation["id"], chatbot_id=widget["chatbot_id"], conversation=conversation)
        page["messages"] = [{key: row[key] for key in ("id", "message_text", "created_at", "sender_type")}
                            for row in rows[:50]]
        page["has_more"] = len(rows) > 50
        if page["messages"]:
            page["last_message_id"] = page["messages"][-1]["id"]
    return page


def open_conversation(widget, session_id, customer_name=None):
    """Get or create the inbox conversation backing a widget session."""
    return get_or_create_platform_conversation(
        chatbot_id=widget["chatbot_id"],
        platform_user_id=session_id,
        customer_name=customer_name,
        source_channel=SOURCE_CHANNEL,
    )


def assert_session_quota(widget, conversation_id):
    """Stop a single visitor from draining the company's AI credit."""
    cap = widget.get("max_messages_per_session") or 50
    used = count_messages_by_conversation(conversation_id, sender_type="customer")

    if used >= cap:
        raise WidgetError(
            "This chat has reached its message limit. Please start a new chat.",
            status=429,
            code="session_limit_reached",
        )

    return cap - used


def normalise_incoming_message(raw):
    message = raw.strip() if isinstance(raw, str) else ""
    if not message:
        raise WidgetError("Message is required.", code="empty_message")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise WidgetError(
            f"Message is too long (max {MAX_MESSAGE_LENGTH} characters).",
            code="message_too_long",
        )
    return message


def record_customer_message(conversation_id, message):
    return save_message(
        conversation_id=conversation_id,
        sender_type="customer",
        message_text=message,
        message_type="text",
        delivery_status="received",
        ai_generated=False,
    )


def record_bot_message(conversation_id, message):
    return save_message(
        conversation_id=conversation_id,
        sender_type="bot",
        message_text=message,
        message_type="text",
        delivery_status="sent",
        ai_generated=True,
    )


def capture_lead(widget, conversation, payload):
    """Store widget lead-form details as a CRM lead."""
    payload = payload or {}

    name = (payload.get("name") or "").strip()[:120]
    email = (payload.get("email") or "").strip()[:160]
    phone = (payload.get("phone") or "").strip()[:32]

    if widget.get("lead_require_name") and not name:
        raise WidgetError("Name is required.", code="name_required")
    if widget.get("lead_require_email") and not email:
        raise WidgetError("Email is required.", code="email_required")
    if widget.get("lead_require_phone") and not phone:
        raise WidgetError("Phone number is required.", code="phone_required")

    if email and not _EMAIL_RE.match(email):
        raise WidgetError("Please enter a valid email address.", code="invalid_email")

    summary_parts = [part for part in (email, phone) if part]
    summary = "Website widget lead" + (f" — {', '.join(summary_parts)}" if summary_parts else "")

    try:
        lead = create_crm_lead(
            company_id=widget["company_id"],
            chatbot_id=widget["chatbot_id"],
            conversation_id=conversation.get("id"),
            customer_phone=phone or None,
            customer_name=name,
            source_channel=SOURCE_CHANNEL,
            lead_type="follow_up",
            status="new",
            priority="medium",
            summary=summary[:500],
            notes=f"Email: {email or 'n/a'}\nPhone: {phone or 'n/a'}",
        )
    except Exception:
        # A duplicate open lead for this conversation is not a visitor-facing
        # failure - the details are already captured.
        logger.warning(
            "Widget lead capture failed for chatbot %s conversation %s",
            widget.get("chatbot_id"),
            conversation.get("id"),
            exc_info=True,
        )
        return None

    return lead
