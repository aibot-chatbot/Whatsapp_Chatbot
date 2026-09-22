"""Telegram trial reminders, admitted and sent in the existing Flask process."""
from datetime import datetime
import os
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from app.database import tuition_reminder_repository as repository
from app.database.automation_event_repository import get_automation_event_by_id
from app.database.tuition_repository import TuitionError, positive, uuid
from app.services.billing_guard import BillingLimitError, can_use_plan_feature
from app.services.company_status_service import CompanyOperationalStatusError, ensure_company_operational
from app.services.channel_delivery_service import ChannelDeliveryError, get_bound_channel, delivery_accepted
from app.services.conversation_delivery_lock import conversation_delivery_lock


def _enabled():
    if any(os.getenv(name, "false").lower() != "true" for name in ("TUITION_TRIALS_ENABLED", "TUITION_REMINDERS_ENABLED")):
        raise TuitionError("Trial reminders are not enabled.", "tuition_reminders_disabled", 503)


def enqueue_due_reminders(*, limit=100):
    _enabled()
    return repository.enqueue_due(limit=limit)


def _authorize(company_id):
    ensure_company_operational(company_id)
    can_use_plan_feature(company_id, "ai_generated_reports")


def _text(context):
    start = datetime.fromisoformat(context["starts_at"].replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("Reminder session time requires a timezone")
    local = start.astimezone(ZoneInfo("Asia/Kuala_Lumpur"))
    name = re.sub(r"[\x00-\x1f\x7f]", " ", str(context["class_name"]))[:150]
    return (f"Trial reminder: {name}\n{local:%d %b %Y, %H:%M} (Malaysia time).\n"
            "This is a reminder for your confirmed trial booking. Please contact the centre if you need to change it.")


def execute_tuition_reminder(*, event_id, lease_token):
    """Internal HTTP only. The authenticated route accepts IDs, never recipients."""
    _enabled()
    event_id, lease_token = positive(event_id), uuid(lease_token)
    event = get_automation_event_by_id(event_id)
    if (not event or event.get("event_type") != "tuition_reminder" or event.get("worker_kind") != "tuition_reminder"
            or event.get("lease_token") != lease_token):
        raise TuitionError("Reminder job is unavailable.", "reminder_scope_denied", 404)
    conversation_id = positive((event.get("payload") or {}).get("conversation_id"))
    def apply(operation, output=None):
        return repository.apply_reminder(event_id=event_id, lease_token=lease_token, operation=operation, output=output)

    # Handoff and tuition mutations use this same lock in singleton Flask.
    with conversation_delivery_lock(conversation_id):
        context = apply("inspect")
        if context.get("status") != "ready":
            return {"status": context.get("status"), "result": context.get("result")}
        if (context.get("company_id") != event["company_id"] or context.get("chatbot_id") != event["chatbot_id"]
                or (context.get("conversation") or {}).get("id") != conversation_id):
            raise TuitionError("Reminder scope changed.", "reminder_scope_denied", 404)
        conversation = context["conversation"]
        if conversation.get("source_channel") != "telegram":
            return apply("skip")
        try:
            _authorize(event["company_id"])
            channel = get_bound_channel(conversation)
        except (BillingLimitError, CompanyOperationalStatusError, ChannelDeliveryError):
            return apply("skip")
        if channel.get("company_id") != event["company_id"] or not channel.get("bot_token"):
            return apply("skip")
        recipient = conversation.get("platform_user_id")
        if not isinstance(recipient, str) or not re.fullmatch(r"-?\d{1,20}", recipient):
            return apply("skip")
        text = _text(context)
        started = apply("begin")
        if started.get("started") is not True or started.get("status") != "ready":
            return {"status": started.get("status"), "result": started.get("result")}
        # All potentially ambiguous failures after durable admission require review.
        try:
            from app.utils.telegram_utils import send_telegram_message
            result = send_telegram_message(channel["bot_token"], recipient, text, parse_mode=None)
            receipt = (result or {}).get("result") or {}
            message_id = receipt.get("message_id")
            if (not delivery_accepted("telegram", result) or type(message_id) is not int or message_id <= 0
                    or str((receipt.get("chat") or {}).get("id")) != recipient):
                return apply("uncertain")
            return apply("finish", {"provider_message_id": str(message_id), "text": text})
        except Exception:
            try:
                return apply("uncertain")
            except Exception:
                raise TuitionError("Reminder delivery needs review.", "reminder_result_uncertain", 503) from None


def process_tuition_reminder(event):
    """Worker forwards IDs to Flask so it never bypasses the handoff send lock."""
    _enabled()
    base = os.getenv("FLASK_AGENT_BASE_URL", "").strip().rstrip("/")
    parsed = urlparse(base)
    token = os.getenv("AGENT_INTERNAL_TOKEN", "")
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or len(token) < 32):
        raise ValueError("Reminder Flask bridge requires authenticated HTTPS")
    payload = {"event_id": positive(event["id"]), "lease_token": uuid(event["lease_token"])}
    with httpx.Client(timeout=25, follow_redirects=False) as client:
        response = client.post(base + "/internal/tuition-reminders/send",
            headers={"Authorization": "Bearer " + token}, json=payload)
        response.raise_for_status()
        if len(response.content) > 65536:
            raise RuntimeError("Reminder response exceeds its limit")
        data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        raise RuntimeError("Reminder bridge returned no outcome")
    return data["data"]
