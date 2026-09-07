"""Validation and orchestration for tenant support request submission."""

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone

from app.database import tenant_support_repository
from app.database import user_repository
from app.services import email_service


logger = logging.getLogger(__name__)


class TenantSupportServiceError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


ALLOWED_CATEGORIES = frozenset({
    "technical",
    "account",
    "chatbot",
    "integration",
    "billing_question",
    "ai_credits",
    "other",
})
ALLOWED_FIELDS = frozenset({
    "category",
    "title",
    "redacted_description",
    "priority",
    "source",
    "escalation_context",
})

# Urgency is guidance for staff triage only - decision 7 in 01-requirements.md
# rules out SLAs, countdowns and breach tracking, so these are three labels and
# nothing more.
ALLOWED_PRIORITIES = frozenset({"low", "normal", "urgent"})
DEFAULT_PRIORITY = "normal"

# Where the escalation came from. The column's legacy value 'tenant' is
# deliberately absent: it describes who filed the row, not what led to it, and
# a browser may not claim it.
ALLOWED_SOURCES = frozenset({"faq_dead_end", "direct"})
DEFAULT_SOURCE = "direct"

# The self-service trail. Four keys, nothing else.
ESCALATION_LIST_KEYS = ("searches", "viewed", "unhelpful")
ESCALATION_FROM_PAGE_KEY = "from_page"
ESCALATION_CONTEXT_KEYS = frozenset(ESCALATION_LIST_KEYS + (ESCALATION_FROM_PAGE_KEY,))
MAX_ESCALATION_ITEMS = 10
MAX_ESCALATION_ITEM_LENGTH = 200
MAX_ESCALATION_FROM_PAGE_LENGTH = 64
# Per-item bounds alone permit ~6 KB, so the total is capped separately and the
# same number is enforced again by the CHECK constraint in migration 052.
MAX_ESCALATION_CONTEXT_BYTES = 4000

FORBIDDEN_TERMS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "provider payload",
    "payment reference",
    "payment_reference",
    "checkout",
    "gateway",
    "impersonat",
    "customer message",
    "conversation content",
)


# --- platform support notification ----------------------------------------
#
# A ticket nobody is told about sits unread in the admin console, so the
# platform support inbox gets an email. It is strictly advisory: the row is
# already committed by the time any of this runs, and every failure below is
# swallowed, because a support request that 503s because SMTP is down is worse
# than a support request nobody was emailed about.
PLATFORM_SUPPORT_INBOX_ENV = "PLATFORM_SUPPORT_INBOX_EMAIL"
# create_tenant_support_request returns only the new ID; rows start at `new`
# (see tenant_support_repository.ALLOWED_STATUSES).
NEW_REQUEST_STATUS = "new"
# _safe_text already caps the description at 2000 characters. The notice is a
# nudge to open the console, not a copy of the ticket, so bound it further.
NOTIFICATION_DESCRIPTION_LIMIT = 500
TRUNCATION_MARKER = " [truncated]"

_inbox_unset_logged = False


def _platform_support_inbox():
    """The notification recipient, or None when the feature is switched off."""
    global _inbox_unset_logged
    recipient = (os.getenv(PLATFORM_SUPPORT_INBOX_ENV) or "").strip()
    if recipient:
        return recipient
    if not _inbox_unset_logged:
        # Once per process, not once per request: an unset recipient is a
        # deployment choice, not a per-ticket event.
        _inbox_unset_logged = True
        logger.info(
            "%s is unset; tenant support notifications are disabled.",
            PLATFORM_SUPPORT_INBOX_ENV,
        )
    return None


def _run_in_background(target):
    """Run `target` off the request thread.

    ponytail: one daemon thread per notification, bounded by the 5/hour rate
    limit on POST /api/support/requests. Under gunicorn --workers 1 (Dockerfile)
    with fly.toml min_machines_running = 1 exactly one process sends. Scaling to
    several workers would not duplicate anything either - the thread is spawned
    by the worker that handled the request, so each ticket is still notified once.
    """
    threading.Thread(target=target, name="tenant-support-notify", daemon=True).start()


def _notify_platform_support(*, request_id, company_id, category, description):
    recipient = _platform_support_inbox()
    if not recipient:
        return

    if len(description) > NOTIFICATION_DESCRIPTION_LIMIT:
        description = description[:NOTIFICATION_DESCRIPTION_LIMIT] + TRUNCATION_MARKER
    submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _send():
        try:
            email_service.send_tenant_support_request_notification_email(
                recipient,
                request_id=request_id,
                company_id=company_id,
                category=category,
                status=NEW_REQUEST_STATUS,
                submitted_at=submitted_at,
                redacted_description=description,
            )
        except Exception:
            logger.error(
                "Tenant support notification failed for request %s", request_id
            )

    try:
        _run_in_background(_send)
    except Exception:
        # Thread creation itself can fail. The ticket exists; drop the notice.
        logger.error(
            "Could not dispatch tenant support notification for request %s", request_id
        )


# --- tenant reply notification (FR-5) --------------------------------------
#
# The complement of the notice above: when platform staff post a tenant-visible
# reply, the requester is emailed that a reply is waiting. The notice carries no
# part of the ticket - not the reply, not the title, not the description.
# `support.html` promises that internal notes are not exposed, and an email that
# quoted the thread would move that boundary without moving the page copy. The
# sender's signature has nowhere to put ticket text, so this is structural
# rather than a rule someone has to remember.
#
# Advisory, exactly like the staff notice: the reply row is committed before any
# of this runs and every failure below is swallowed.
TENANT_VISIBLE_REPLY_STATUS = "visible"
PLATFORM_REPLY_AUTHOR_TYPE = "platform_admin"

# One email per reply is structural, not hopeful: the only path that creates a
# tenant-visible reply is create_platform_support_case_reply, and each call
# inserts exactly one row with a fresh identity. This deque only has to absorb a
# re-entrant call for a reply already dispatched.
# ponytail: process-local and an O(n) scan of 512 entries - fine under
# `gunicorn --workers 1`, and a restart at worst re-arms one reply. The durable
# form is an 'email' row in tenant_support_reply_notifications, which needs a
# migration to relax that table's channel CHECK; not worth it for a notice that
# is never retried and carries nothing.
NOTIFIED_REPLY_MEMORY = 512
_notified_reply_ids = deque(maxlen=NOTIFIED_REPLY_MEMORY)


def _positive_int(value):
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _tenant_reply_recipient(request_id, company_id):
    """The requester's address, or None.

    Scoped to the reply's own company on both hops: the request must belong to
    it, and the user is loaded through the company-scoped lookup. A reply whose
    request has been re-pointed at another tenant resolves to nobody rather than
    to the wrong inbox.
    """
    request = tenant_support_repository.get_tenant_support_request_for_platform_admin(
        request_id
    )
    if not isinstance(request, dict) or request.get("company_id") != company_id:
        return None
    requester_user_id = request.get("requester_user_id")
    if not _positive_int(requester_user_id):
        return None
    user = user_repository.get_user_by_id_for_company(requester_user_id, company_id)
    if not isinstance(user, dict):
        return None
    return (user.get("email") or "").strip() or None


def notify_tenant_of_reply(reply):
    """Tell the requester a reply is waiting. Never raises, never blocks.

    Takes the raw reply row from create_platform_support_case_reply. Both
    recipient lookups happen on the worker thread, so the staff member waiting
    on POST .../replies pays for neither.
    """
    reply_id = None
    try:
        if not isinstance(reply, dict):
            return
        # Defence in depth. The schema pins both columns today
        # (tenant_support_replies_author_type_check and
        # ..._visibility_status_check) and the repository re-checks them, so an
        # internal note - a platform_support_case_events row - can never arrive
        # here. These stay because relaxing either CHECK must not silently start
        # emailing tenants about staff-only text.
        if reply.get("visibility_status") != TENANT_VISIBLE_REPLY_STATUS:
            return
        if reply.get("author_type") != PLATFORM_REPLY_AUTHOR_TYPE:
            return

        reply_id = reply.get("id")
        request_id = reply.get("request_id")
        company_id = reply.get("company_id")
        if not all(_positive_int(value) for value in (reply_id, request_id, company_id)):
            return
        if reply_id in _notified_reply_ids:
            return
        _notified_reply_ids.append(reply_id)

        def _send():
            try:
                recipient = _tenant_reply_recipient(request_id, company_id)
                if not recipient:
                    return
                email_service.send_tenant_support_reply_notification_email(
                    recipient, request_id=request_id
                )
            except Exception:
                logger.error(
                    "Tenant reply notification failed for reply %s", reply_id
                )

        _run_in_background(_send)
    except Exception:
        # Thread creation and the guards above. The reply exists; drop the notice.
        logger.error(
            "Could not dispatch tenant reply notification for reply %s", reply_id
        )


def _validation(code, message):
    raise TenantSupportServiceError(400, code, message)


def _positive_context_id(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TenantSupportServiceError(
            500,
            "authentication_context_invalid",
            f"Authenticated {field_name} context is invalid.",
        )
    return value


def _positive_request_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TenantSupportServiceError(
            400, "invalid_request_id", "Request ID must be a positive integer."
        )
    return value


def _integer_parameter(value, *, name, default, minimum, maximum=None):
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise TenantSupportServiceError(400, f"invalid_{name}", f"{name} must be an integer.")
    if parsed < minimum or (maximum is not None and parsed > maximum):
        bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        raise TenantSupportServiceError(400, f"invalid_{name}", f"{name} must be {bounds}.")
    return parsed


def _safe_text(value, *, field_name, maximum):
    if not isinstance(value, str):
        _validation(f"invalid_{field_name}", f"{field_name} must be text.")
    normalized = value.strip()
    if not 1 <= len(normalized) <= maximum:
        _validation(
            f"invalid_{field_name}",
            f"{field_name} must contain 1 to {maximum} characters.",
        )
    if any(term in normalized.casefold() for term in FORBIDDEN_TERMS):
        _validation(
            f"invalid_{field_name}",
            f"{field_name} contains unsupported sensitive content.",
        )
    return normalized


def _enumerated(value, *, field_name, allowed, default):
    """One of `allowed`, or `default` when the key is absent entirely."""
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or isinstance(value, bool) or value not in allowed:
        _validation(f"invalid_{field_name}", f"Unsupported support {field_name}.")
    return value


def _escalation_string(value, *, maximum):
    if not isinstance(value, str) or isinstance(value, bool):
        _invalid_escalation_context("every trail value must be text.")
    normalized = value.strip()
    if len(normalized) > maximum:
        # Rejected, never trimmed: a truncated search term or article title is
        # misleading evidence, and staff would have no way to know it was cut.
        _invalid_escalation_context(f"trail values are limited to {maximum} characters.")
    return normalized


def _invalid_escalation_context(detail):
    _validation("invalid_escalation_context", f"escalation_context is invalid: {detail}")


def _escalation_context(value):
    """A bounded, structurally validated self-service trail, or None.

    FORBIDDEN_TERMS is deliberately NOT applied here. That check exists for
    user-authored prose in redacted_description, where a mention of a password
    or a token is a sign the user pasted something they should not have. This
    field carries machine-collected article titles and search terms instead, so
    a perfectly legitimate help article called "Rotate your API token" would
    otherwise make escalation impossible for the users who most need it. The
    defence here is structural: four known keys, ten items, 200 characters an
    item, and a hard cap on the serialised whole.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        _invalid_escalation_context("it must be an object.")
    unknown = set(value) - ESCALATION_CONTEXT_KEYS
    if unknown:
        _invalid_escalation_context("it contains unsupported keys.")

    context = {}
    for key in ESCALATION_LIST_KEYS:
        if key not in value:
            continue
        items = value[key]
        if not isinstance(items, list):
            _invalid_escalation_context(f"{key} must be a list.")
        if len(items) > MAX_ESCALATION_ITEMS:
            _invalid_escalation_context(
                f"{key} is limited to {MAX_ESCALATION_ITEMS} entries."
            )
        cleaned = [
            item
            for item in (
                _escalation_string(entry, maximum=MAX_ESCALATION_ITEM_LENGTH)
                for entry in items
            )
            if item
        ]
        if cleaned:
            context[key] = cleaned

    if ESCALATION_FROM_PAGE_KEY in value:
        from_page = _escalation_string(
            value[ESCALATION_FROM_PAGE_KEY], maximum=MAX_ESCALATION_FROM_PAGE_LENGTH
        )
        if from_page:
            context[ESCALATION_FROM_PAGE_KEY] = from_page

    if not context:
        # An empty trail is no trail: store SQL NULL rather than {} so staff can
        # tell "the page sent nothing" from "the page sent an empty object".
        return None
    serialized = json.dumps(context, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_ESCALATION_CONTEXT_BYTES:
        _invalid_escalation_context(
            f"it exceeds {MAX_ESCALATION_CONTEXT_BYTES} bytes."
        )
    return context


def submit_tenant_support_request(payload, *, company_id, requester_user_id):
    company_id = _positive_context_id(company_id, "company")
    requester_user_id = _positive_context_id(requester_user_id, "requester")
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be an object.")

    unsupported = set(payload) - ALLOWED_FIELDS
    if unsupported:
        _validation("unsupported_field", "Request contains unsupported fields.")

    category = payload.get("category")
    if not isinstance(category, str) or category.strip() not in ALLOWED_CATEGORIES:
        _validation("invalid_category", "Unsupported support category.")
    category = category.strip()
    title = _safe_text(payload.get("title"), field_name="title", maximum=160)
    description = _safe_text(
        payload.get("redacted_description"),
        field_name="redacted_description",
        maximum=2000,
    )
    priority = _enumerated(
        payload.get("priority"),
        field_name="priority",
        allowed=ALLOWED_PRIORITIES,
        default=DEFAULT_PRIORITY,
    )
    source = _enumerated(
        payload.get("source"),
        field_name="source",
        allowed=ALLOWED_SOURCES,
        default=DEFAULT_SOURCE,
    )
    escalation_context = _escalation_context(payload.get("escalation_context"))

    try:
        request_id = tenant_support_repository.create_tenant_support_request(
            company_id=company_id,
            requester_user_id=requester_user_id,
            category=category,
            title=title,
            redacted_description=description,
            priority=priority,
            source=source,
            escalation_context=escalation_context,
        )
    except Exception:
        logger.error("Tenant support request RPC failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support request submission is temporarily unavailable.",
        )

    _notify_platform_support(
        request_id=request_id,
        company_id=company_id,
        category=category,
        description=description,
    )
    return {"request_id": request_id}


def _safe_tenant_request(row, *, include_content=False):
    if not isinstance(row, dict):
        row = {}
    safe = {
        "request_id": row.get("id"),
        "category": row.get("category"),
        "status": row.get("status"),
        "source": row.get("source"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "closed_at": row.get("closed_at"),
    }
    if include_content:
        safe["title"] = row.get("title")
        safe["redacted_description"] = row.get("redacted_description")
    return safe


def _safe_tenant_reply(row):
    if not isinstance(row, dict):
        row = {}
    return {
        "reply_id": row.get("id"),
        "request_id": row.get("request_id"),
        "author_type": row.get("author_type"),
        "redacted_body": row.get("redacted_body"),
        "created_at": row.get("created_at"),
    }


def list_tenant_support_requests(*, company_id, requester_user_id, limit=None, offset=None):
    company_id = _positive_context_id(company_id, "company")
    requester_user_id = _positive_context_id(requester_user_id, "requester")
    limit = _integer_parameter(limit, name="limit", default=25, minimum=1, maximum=100)
    offset = _integer_parameter(offset, name="offset", default=0, minimum=0)
    try:
        rows, total = tenant_support_repository.list_tenant_support_requests_for_tenant(
            company_id=company_id,
            requester_user_id=requester_user_id,
            limit=limit,
            offset=offset,
        )
    except Exception:
        logger.error("Tenant support request history lookup failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support request history is temporarily unavailable.",
        )
    return {
        "requests": [_safe_tenant_request(row) for row in rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_more": offset + len(rows) < total,
        },
    }


def get_tenant_support_request(request_id, *, company_id, requester_user_id):
    request_id = _positive_request_id(request_id)
    company_id = _positive_context_id(company_id, "company")
    requester_user_id = _positive_context_id(requester_user_id, "requester")
    try:
        row = tenant_support_repository.get_tenant_support_request_for_tenant(
            request_id,
            company_id=company_id,
            requester_user_id=requester_user_id,
        )
    except Exception:
        logger.error("Tenant support request detail lookup failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support request detail is temporarily unavailable.",
        )
    if not row:
        raise TenantSupportServiceError(
            404, "tenant_support_request_not_found", "Support request not found."
        )
    try:
        replies = tenant_support_repository.list_tenant_support_replies_for_tenant(
            request_id, company_id=company_id
        )
    except Exception:
        logger.error("Tenant support reply lookup failed")
        raise TenantSupportServiceError(
            503,
            "tenant_support_unavailable",
            "Support conversation is temporarily unavailable.",
        )
    return {
        "request": _safe_tenant_request(row, include_content=True),
        "replies": [_safe_tenant_reply(reply) for reply in replies],
    }
