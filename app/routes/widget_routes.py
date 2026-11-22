"""widget_routes.py — website chat widget (FastBots-style embed).

Two groups of endpoints live here:

  Public (no JWT, cross-origin) — consumed by the embed script, the iframe
  and the share link. Addressed by `public_key`, never by chatbot_id.

      GET  /widget.js                           loader script
      GET  /widget/<public_key>                 iframe chat page
      GET  /chat/<public_key>                   full-page share link
      GET  /api/widget/<public_key>/config      public appearance config
      POST /api/widget/<public_key>/session     start a chat session
      POST /api/widget/<public_key>/message     send a message, get a reply
      POST /api/widget/<public_key>/messages    poll delivered staff replies
      POST /api/widget/<public_key>/lead        submit the lead form

  Dashboard (JWT + admin/owner) — used by the Embed tab.

      GET  /api/bots/<chatbot_id>/widget
      PUT  /api/bots/<chatbot_id>/widget
      POST /api/bots/<chatbot_id>/widget/regenerate-key
"""

import logging
import os
import re
from ipaddress import ip_address
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from app.decorators.auth_decorator import token_required
from app.database.agent_action_repository import is_conversation_escalated
from app.rate_limit import limiter
from app.services.ai_router import OPERATION_CHAT_REPLY, generate_response
from app.services.billing_guard import BillingLimitError
from app.services.channel_delivery_service import automatic_reply_allowed, resume_ai_after_staff_idle
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.company_status_service import (
    CompanyOperationalStatusError,
    company_operational_required,
    ensure_company_operational,
)
from app.services.web_widget_service import (
    WidgetError,
    assert_session_quota,
    capture_lead,
    ensure_widget,
    generate_session_id,
    is_origin_allowed,
    normalise_incoming_message,
    open_conversation,
    public_config,
    read_staff_messages,
    record_bot_message,
    record_customer_message,
    regenerate_public_key,
    resolve_public_widget,
    update_widget_settings,
    validate_session_id,
)
from app.utils.access_control import (
    get_current_company_id,
    role_required,
    verify_chatbot_access,
)
from app.utils.message_style_utils import parse_buttons_tag

logger = logging.getLogger(__name__)

widget_blueprint = Blueprint("widget", __name__)

FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
)

SILENT_REPLY_MARKER = "<SILENT_BOT_RESPONSE>"

# Public widget endpoints are unauthenticated, so they are rate limited by IP.
WIDGET_MESSAGE_RATELIMIT = "20/minute"
WIDGET_SESSION_RATELIMIT = "30/minute"
WIDGET_POLL_RATELIMIT = "120/minute"


# ── Cross-origin support ──────────────────────────────────────────────
# The app-wide CORS config only allows the dashboard origin. Widget routes
# are embedded on customer websites, so they answer any origin and are
# instead protected by the per-widget domain allowlist.

def _public_cors(response, origin=None):
    response.headers["Access-Control-Allow-Origin"] = origin or "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Vary"] = "Origin"
    return response


@widget_blueprint.after_request
def _apply_widget_headers(response):
    if request.path.startswith(("/api/widget/", "/widget/", "/chat/")) or \
            request.path == "/widget.js":
        _public_cors(response, request.headers.get("Origin"))
        # The chat UI is designed to be framed by third-party sites, so the
        # app-wide X-Frame-Options: DENY must not apply here.
        response.headers.pop("X-Frame-Options", None)
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors *")
    if request.path.startswith(("/api/widget/", "/widget/", "/chat/")):
        # Publication and domain permissions must be checked after disconnect.
        response.headers["Cache-Control"] = "no-store"
    return response


def _error(message, status=400, code="widget_error"):
    return jsonify({"status": "error", "code": code, "message": message}), status


def _http_origin(value):
    """Compare browser origins including scheme and effective port."""
    try:
        parsed = urlsplit(value or "")
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
        port = parsed.port
        return parsed.scheme, parsed.hostname, port if port is not None else (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def _load_widget_or_error():
    """Resolve + origin-check the widget for the current request."""
    public_key = request.view_args.get("public_key")
    widget, bot = resolve_public_widget(public_key)
    try:
        ensure_company_operational(bot.get("company_id"))
    except CompanyOperationalStatusError:
        raise WidgetError(
            "This chatbot is temporarily unavailable.",
            status=403,
            code="company_suspended",
        )

    origin = request.headers.get("Origin") or request.headers.get("Referer")
    hosted_origin = _http_origin(origin)
    # Both chat HTML routes enforce the embedding site's allowlist through
    # frame-ancestors. Their API calls originate on our own host, not that site.
    is_hosted = hosted_origin is not None and hosted_origin == _http_origin(request.host_url)
    if not is_hosted and not is_origin_allowed(widget, origin):
        raise WidgetError(
            "This chatbot is not permitted on this website.",
            status=403,
            code="origin_not_allowed",
        )

    return widget, bot


# ── Public: loader script and chat pages ──────────────────────────────

@widget_blueprint.route("/widget.js", methods=["GET", "OPTIONS"])
def widget_loader():
    """Serve the embed loader with a JavaScript content type."""
    if request.method == "OPTIONS":
        return ("", 204)

    response = send_from_directory(
        FRONTEND_DIR,
        "widget.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


def _widget_chat_page(public_key):
    response = send_from_directory(FRONTEND_DIR, "widget-chat.html")
    try:
        widget, _bot = resolve_public_widget(public_key)
    except WidgetError:
        # Keep the visitor-facing error UI; the API explains inactive links.
        ancestors = "'none'"
    else:
        allowed = widget.get("allowed_domains") or []
        sources = ["'self'"]
        for domain in allowed:
            # Stored domain values must never become arbitrary CSP syntax.
            if not isinstance(domain, str) or not re.fullmatch(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*", domain):
                continue
            for scheme in ("http", "https"):
                sources.extend((f"{scheme}://{domain}:*", f"{scheme}://*.{domain}:*"))
        ancestors = " ".join(sources) if allowed else "*"
    response.headers["Content-Security-Policy"] = f"frame-ancestors {ancestors}"
    return response


@widget_blueprint.route("/widget/<public_key>", methods=["GET"])
def widget_frame(public_key):
    """Chat UI rendered inside the embedded iframe."""
    return _widget_chat_page(public_key)


@widget_blueprint.route("/chat/<public_key>", methods=["GET"])
def widget_share_page(public_key):
    """Standalone full-page chat, for sharing as a direct link."""
    return _widget_chat_page(public_key)


# ── Public: JSON API ──────────────────────────────────────────────────

@widget_blueprint.route("/api/widget/<public_key>/config", methods=["GET", "OPTIONS"])
def widget_config(public_key):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        widget, _bot = _load_widget_or_error()
    except WidgetError as e:
        return _error(str(e), e.status, e.code)

    return jsonify({"status": "success", "data": public_config(widget)}), 200


@widget_blueprint.route("/api/widget/<public_key>/session", methods=["POST", "OPTIONS"])
@limiter.limit(WIDGET_SESSION_RATELIMIT)
def widget_start_session(public_key):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        widget, _bot = _load_widget_or_error()
    except WidgetError as e:
        return _error(str(e), e.status, e.code)

    session_id = generate_session_id()

    return jsonify({
        "status": "success",
        "data": {
            "session_id": session_id,
            "welcome_message": widget.get("welcome_message") or "",
            "suggested_questions": widget.get("suggested_questions") or [],
        },
    }), 200


@widget_blueprint.route("/api/widget/<public_key>/messages", methods=["POST", "OPTIONS"])
@limiter.limit(WIDGET_POLL_RATELIMIT)
def widget_staff_messages(public_key):
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        widget, _bot = _load_widget_or_error()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise WidgetError("A JSON object is required.", code="invalid_request")
        page = read_staff_messages(widget, payload.get("session_id"), payload.get("after_id", 0))
        return jsonify({"status": "success", "data": page}), 200
    except WidgetError as error:
        return _error(str(error), error.status, error.code)
    except Exception:
        # Database exception text can contain the session capability. Keep it
        # out of logs, URLs and the public error response.
        logger.error("Widget staff-message polling unavailable")
        return _error("Messages are temporarily unavailable. Please try again.",
                      503, "temporarily_unavailable")


def _waiting_for_staff(remaining=None):
    return jsonify({"status": "success", "data": {
        "reply": "", "handled_by": "human",
        "messages_remaining": max(remaining - 1, 0) if remaining is not None else None,
    }}), 200


@widget_blueprint.route("/api/widget/<public_key>/message", methods=["POST", "OPTIONS"])
@limiter.limit(WIDGET_MESSAGE_RATELIMIT)
def widget_send_message(public_key):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        widget, _bot = _load_widget_or_error()

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise WidgetError("A JSON object is required.", code="invalid_request")
        session_id = validate_session_id(payload.get("session_id"))
        message = normalise_incoming_message(payload.get("message"))

        conversation = open_conversation(widget, session_id)
        with conversation_delivery_lock(conversation["id"]):
            resume_ai_after_staff_idle(conversation, widget["chatbot_id"])
            paused = is_conversation_escalated(
                conversation["id"], chatbot_id=widget["chatbot_id"], conversation=conversation)
            remaining = None if paused else assert_session_quota(widget, conversation["id"])
            customer_message = record_customer_message(conversation["id"], message)
            if customer_message is None:
                raise WidgetError("Could not save your message. Please try again.", status=503)
        if paused:
            return _waiting_for_staff()

        reply = generate_response(
            message,
            session_id,
            widget["chatbot_id"],
            source_channel="web",
            operation_type=OPERATION_CHAT_REPLY,
            conversation_id=conversation["id"],
            **({"message_id": customer_message["id"]}
               if isinstance(customer_message, dict) and customer_message.get("id") is not None else {}),
        )

        with conversation_delivery_lock(conversation["id"]):
            paused = is_conversation_escalated(
                conversation["id"], chatbot_id=widget["chatbot_id"], conversation=conversation)
            if reply == SILENT_REPLY_MARKER or not automatic_reply_allowed(conversation, reply, paused=paused):
                return _waiting_for_staff(remaining)
            if record_bot_message(conversation["id"], reply) is None:
                raise WidgetError("Could not save the reply. Please try again.", status=503)

        text, buttons = parse_buttons_tag(reply)
        return jsonify({
            "status": "success",
            "data": {
                "reply": text,
                "buttons": buttons,
                "handled_by": "bot",
                "messages_remaining": max(remaining - 1, 0),
            },
        }), 200

    except WidgetError as e:
        return _error(str(e), e.status, e.code)
    except BillingLimitError as e:
        # Never leak the company's billing state to a website visitor.
        logger.warning(
            "Widget message blocked by billing guard (chatbot=%s, code=%s)",
            public_key,
            e.code,
        )
        return _error(
            "This chatbot is temporarily unavailable. Please try again later.",
            503,
            "temporarily_unavailable",
        )
    except Exception:
        logger.error("Widget message unavailable")
        return _error(
            "Sorry, something went wrong. Please try again.",
            500,
            "internal_error",
        )


@widget_blueprint.route("/api/widget/<public_key>/lead", methods=["POST", "OPTIONS"])
@limiter.limit(WIDGET_SESSION_RATELIMIT)
def widget_submit_lead(public_key):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        widget, _bot = _load_widget_or_error()

        if not widget.get("collect_lead"):
            return _error("Lead capture is not enabled.", 400, "lead_disabled")

        payload = request.get_json(silent=True) or {}
        session_id = validate_session_id(payload.get("session_id"))

        conversation = open_conversation(
            widget,
            session_id,
            customer_name=(payload.get("name") or "").strip() or None,
        )
        capture_lead(widget, conversation, payload)

        return jsonify({"status": "success", "data": {"captured": True}}), 200

    except WidgetError as e:
        return _error(str(e), e.status, e.code)
    except Exception:
        logger.exception("Widget lead capture failed for key=%s", public_key)
        return _error("Could not save your details.", 500, "internal_error")


# ── Dashboard: widget configuration ───────────────────────────────────

def _delivery_metadata(base, configured):
    """Describe URL suitability without making a network or uptime claim."""
    kind = "missing" if not configured else "invalid"
    origin = _http_origin(base)
    if configured and origin:
        parsed = urlsplit(base)
        scheme, host, port = origin
        if port > 0 and not parsed.path and not parsed.query and not parsed.fragment:
            valid_host = True
            try:
                local = not ip_address(host).is_global
            except ValueError:
                try:
                    host = host.encode("idna").decode("ascii").removesuffix(".")
                    valid_host = len(host) <= 253 and all(
                        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label, re.I)
                        for label in host.split(".")
                    )
                except UnicodeError:
                    valid_host = False
                local = "." not in host or host.endswith((".localhost", ".local"))
            if not valid_host:
                kind = "invalid"
            elif local:
                kind = "local"
            elif host.endswith((".trycloudflare.com", ".trycloudflare.app")):
                kind = "temporary"
            elif scheme == "https":
                kind = "permanent"
    messages = {
        "permanent": "This link uses your configured HTTPS address. Reachability has not been checked.",
        "temporary": "This test link can stop when the tunnel closes. Use a permanent address for customers.",
        "local": "This address is for local testing. Use a permanent public address for customers.",
        "missing": "Set a permanent public address before sharing this bot with customers.",
        "invalid": "A valid HTTPS public address is required before sharing this bot with customers.",
    }
    return {
        "base_configured": configured,
        "base_kind": kind,
        "persistent_url": kind == "permanent",
        "reachability": "not_checked",
        "message": messages[kind],
    }


def _embed_urls(widget):
    configured_base = (current_app.config.get("PUBLIC_BASE_URL")
                       or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    base = configured_base or request.host_url.rstrip("/")
    key = widget.get("public_key")

    return {
        "base_url": base,
        "delivery": _delivery_metadata(base, bool(configured_base)),
        "script_url": f"{base}/widget.js",
        "share_url": f"{base}/chat/{key}",
        "iframe_url": f"{base}/widget/{key}",
        "script_snippet": (
            f'<script src="{base}/widget.js" '
            f'data-chatbot-key="{key}" defer></script>'
        ),
        "iframe_snippet": (
            f'<iframe src="{base}/widget/{key}" '
            f'style="width:100%;height:600px;border:0;" '
            f'frameborder="0" allow="clipboard-write"></iframe>'
        ),
    }


@widget_blueprint.route("/api/bots/<int:chatbot_id>/widget", methods=["GET"])
@token_required
@company_operational_required
@role_required("admin", "owner")
def get_bot_widget(chatbot_id):
    try:
        verify_chatbot_access(chatbot_id)
        widget = ensure_widget(chatbot_id, get_current_company_id())

        return jsonify({
            "status": "success",
            "data": {"widget": widget, "embed": _embed_urls(widget)},
        }), 200

    except WidgetError as e:
        return _error(str(e), e.status, e.code)
    except PermissionError as e:
        return _error(str(e), 403, "forbidden")
    except Exception as e:
        logger.exception("Failed to load widget for chatbot %s", chatbot_id)
        return _error(str(e), 500, "internal_error")


@widget_blueprint.route("/api/bots/<int:chatbot_id>/widget", methods=["PUT", "PATCH"])
@token_required
@company_operational_required
@role_required("admin", "owner")
def put_bot_widget(chatbot_id):
    try:
        verify_chatbot_access(chatbot_id)
        widget = update_widget_settings(
            chatbot_id,
            get_current_company_id(),
            request.get_json(silent=True) or {},
        )

        return jsonify({
            "status": "success",
            "data": {"widget": widget, "embed": _embed_urls(widget)},
        }), 200

    except WidgetError as e:
        return _error(str(e), e.status, e.code)
    except PermissionError as e:
        return _error(str(e), 403, "forbidden")
    except Exception as e:
        logger.exception("Failed to update widget for chatbot %s", chatbot_id)
        return _error(str(e), 500, "internal_error")


@widget_blueprint.route(
    "/api/bots/<int:chatbot_id>/widget/regenerate-key", methods=["POST"]
)
@token_required
@company_operational_required
@role_required("admin", "owner")
def post_regenerate_widget_key(chatbot_id):
    try:
        verify_chatbot_access(chatbot_id)
        widget = regenerate_public_key(chatbot_id, get_current_company_id())

        return jsonify({
            "status": "success",
            "data": {"widget": widget, "embed": _embed_urls(widget)},
        }), 200

    except WidgetError as e:
        return _error(str(e), e.status, e.code)
    except PermissionError as e:
        return _error(str(e), 403, "forbidden")
    except Exception as e:
        logger.exception("Failed to regenerate widget key for chatbot %s", chatbot_id)
        return _error(str(e), 500, "internal_error")
