"""Consent-based follow-ups for conversations with a delivered AI reply."""
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import time
from zoneinfo import ZoneInfo

from postgrest.exceptions import APIError

from app.database import follow_up_repository as repo
from app.database.agent_action_repository import is_conversation_escalated
from app.database.message_repository import save_message
from app.services.ai_router import generate_follow_up_draft
from app.services.billing_guard import BillingLimitError, can_use_plan_feature
from app.services.bot_config_fields import resolve_persona_fields
from app.services.channel_delivery_service import (
    ChannelDeliveryError, FOLLOWUP_CHANNELS, deliver_follow_up, delivery_accepted, whatsapp_receipt_id,
    whatsapp_window_open,
)
from app.services.company_status_service import CompanyOperationalStatusError, ensure_company_operational
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.free_trial_status_service import parse_iso_datetime
from app.services.needs_card_service import STAGES

logger = logging.getLogger(__name__)

OPT_OUT_STOP_RATE = 0.05
OPT_OUT_MIN_CUSTOMERS = 20
OPT_OUT_WINDOW_DAYS = 30

_MODES = dict.fromkeys(("retail_shop", "car_workshop", "property_agent", "travel_agency",
                        "restaurant", "beauty_salon", "tuition_center"), "sales")
_MODES["clinic"] = "service_only"


def follow_up_mode(published_industry):
    template = published_industry.get("template_id") if isinstance(published_industry, dict) else None
    return _MODES.get(template, "gentle") if isinstance(template, str) else "gentle"


def _allowed_time(at):
    local = at.astimezone(ZoneInfo("Asia/Kuala_Lumpur"))
    if 9 <= local.hour < 21:
        return at
    morning = local.replace(hour=9, minute=0, second=0, microsecond=0)
    if local.hour >= 21:
        morning += timedelta(days=1)
    return morning.astimezone(timezone.utc)


def _scope(conversation, company_id):
    return {"company_id": company_id, "chatbot_id": conversation["chatbot_id"],
            "conversation_id": conversation["id"]}


def _rate_start(bot, at):
    start = at - timedelta(days=OPT_OUT_WINDOW_DAYS)
    return max(start, parse_iso_datetime(bot.get("followups_enabled_at")) or start)


def _touch_counts(rows, start, at):
    followed, opted_out = set(), set()
    sent = 0
    for row in rows:
        withdrawal = parse_iso_datetime(row.get("withdrawn_at"))
        touch = parse_iso_datetime(row["sent_at"])
        if start <= touch <= at:
            sent += 1
            followed.add(row["conversation_id"])
            if withdrawal and touch < withdrawal <= at:
                opted_out.add(row["conversation_id"])
    return len(followed), len(opted_out), sent


def _check_opt_out_rate(bot, at, rows=None):
    start = _rate_start(bot, at)
    if rows is None:
        rows = repo.receipts(bot["company_id"], bot["id"], start, at)
    followed, opted_out, _ = _touch_counts(rows, start, at)
    ratio = opted_out / followed if followed else 0
    rate = {"followed": followed, "opted_out": opted_out, "percent": ratio * 100}
    if bot["followups_enabled"] and followed >= OPT_OUT_MIN_CUSTOMERS and ratio > OPT_OUT_STOP_RATE:
        if not repo.auto_stop(bot, at, rate):
            # The owner or another worker changed the switch during this read.
            raise RuntimeError("Follow-up settings changed during the rate check")
        logger.info("Follow-ups stopped company_id=%s chatbot_id=%s followed=%s opted_out=%s",
                    bot["company_id"], bot["id"], followed, opted_out)
        bot = {**bot, "followups_enabled": False, "followups_auto_stopped_at": at.isoformat(),
               "followups_auto_stop_counts": rate}
    return bot, rate


def follow_up_summary(bot, *, now=None):
    from app.database.whatsapp_template_repository import list_eligible

    at = now or datetime.now(timezone.utc)
    company_id, bot_id = bot["company_id"], bot["id"]
    start = at - timedelta(days=OPT_OUT_WINDOW_DAYS)
    rows = repo.receipts(company_id, bot_id, start, at)
    bot, rate = _check_opt_out_rate(bot, at, rows)
    followed, opted_out, sent = _touch_counts(rows, start, at)
    counts = {"followed": followed, "messages_sent": sent, "opted_out": opted_out,
              "replied": 0, "won": 0, "no_reply": 0, "held": 0, "delivery_failed": 0}
    won, replied, no_reply = set(), set(), set()
    for row in repo.window_outcomes(company_id, bot_id, start, at):
        reason = row.get("stop_reason")
        if reason == "lead_won" or row["kind"] == "check_in":
            outcome_at = parse_iso_datetime(row.get("won_at") or (
                row["created_at"] if row["kind"] == "check_in" else row["updated_at"]))
            if start <= outcome_at <= at:
                won.add(row["conversation_id"])
        if not start <= parse_iso_datetime(row["updated_at"]) <= at:
            continue
        if reason == "customer_replied" and row["touch_count"] > 0:
            replied.add(row["conversation_id"])
        elif reason == "no_reply":
            no_reply.add(row["conversation_id"])
        elif reason == "held_by_check":
            counts["held"] += 1
        elif reason in ("delivery_failed", "needs_review"):
            counts["delivery_failed"] += 1
    counts.update(won=len(won), replied=len(replied), no_reply=len(no_reply))
    try:
        entitled = can_use_plan_feature(company_id, "automation_workflows")
    except BillingLimitError:
        entitled = False
    has_whatsapp, wabas = repo.connected_whatsapp_accounts(company_id, bot_id)
    templates = list_eligible(company_id, wabas) if wabas else []
    reason = None
    if not entitled:
        reason = "Follow-ups require a Pro plan."
    elif not repo.has_connected_follow_up_channel(company_id, bot_id, has_whatsapp=has_whatsapp):
        reason = "Connect Telegram or official WhatsApp to enable follow-ups."
    persona = repo.deployed_persona(company_id, bot_id, bot.get("deployed_profile_name"))
    return {"enabled": bot["followups_enabled"], "available": reason is None, "reason": reason,
            "has_official_whatsapp": has_whatsapp, "followup_template_id": bot.get("followup_template_id"),
            "templates": [{key: row[key] for key in ("id", "name", "language")} for row in templates],
            "tone": resolve_persona_fields(persona)["tone"] or "Friendly",
            "auto_stopped_at": bot.get("followups_auto_stopped_at"),
            "auto_stop_counts": bot.get("followups_auto_stop_counts"), "counts": counts, "rate": rate,
            "thresholds": {"percent": OPT_OUT_STOP_RATE * 100, "minimum_customers": OPT_OUT_MIN_CUSTOMERS,
                           "window_days": OPT_OUT_WINDOW_DAYS}, "recent": repo.recent_follow_ups(company_id, bot_id)}


def _eligibility(scope, platform, source_message_id, now, *, before_send=False):
    chat = repo.conversation(scope)
    bot = (chat or {}).get("chatbots") or {}
    if (not chat or platform not in FOLLOWUP_CHANNELS or platform == "whatsapp_link"
            or chat.get("source_channel") != platform or not chat.get("platform_user_id")
            or bot.get("id") != scope["chatbot_id"] or bot.get("company_id") != scope["company_id"]):
        return "channel_unavailable", None, None
    if bot.get("followups_enabled") is not True:
        return "followups_disabled", None, None
    try:
        ensure_company_operational(scope["company_id"])
        if not can_use_plan_feature(scope["company_id"], "automation_workflows"):
            return "plan_ineligible", None, None
    except CompanyOperationalStatusError:
        return "company_inactive", None, None
    except BillingLimitError:
        return "plan_ineligible", None, None
    if repo.consent_status(scope["company_id"], platform, chat["platform_user_id"]) != "granted":
        return "consent_missing", None, None
    if is_conversation_escalated(chat["id"], chat["chatbot_id"], conversation=chat):
        return "staff_handling", None, None
    customer = repo.latest_customer(scope)
    if not customer or customer["id"] != source_message_id:
        return "customer_replied", None, None
    if follow_up_mode(bot.get("industry_template_published")) == "service_only":
        return "service_only", None, None
    if (chat.get("customer_needs") or {}).get("stage") not in STAGES[1:]:
        return "stage_ineligible", None, None
    if before_send and not _check_opt_out_rate(bot, now)[0]["followups_enabled"]:
        return "followups_disabled", None, None
    return None, chat, customer


def schedule_after_reply(conversation, company_id, source_message_id, *, now=None):
    platform = conversation.get("source_channel")
    if not company_id or not source_message_id or platform not in FOLLOWUP_CHANNELS:
        return
    at = now or datetime.now(timezone.utc)
    scope = _scope(conversation, company_id)
    try:
        with conversation_delivery_lock(scope["conversation_id"]):
            reason, chat, _ = _eligibility(scope, platform, source_message_id, at)
            if reason or (repo.latest_lead(scope) or {}).get("status") in {"won", "lost"}:
                return
            mode = follow_up_mode(chat["chatbots"].get("industry_template_published"))
            delay = timedelta(hours=4) if mode == "sales" else timedelta(days=1)
            repo.schedule({**scope, "platform": platform, "mode": mode, "kind": "sales",
                           "source_message_id": source_message_id, "scheduled_at": at.isoformat(),
                           "updated_at": at.isoformat(), "next_due_at": _allowed_time(at + delay).isoformat()})
    except Exception:
        logger.warning("Follow-up scheduling unavailable company_id=%s conversation_id=%s",
                       company_id, scope["conversation_id"])


def stop_for_customer_reply(conversation, company_id):
    if not company_id or conversation.get("source_channel") not in FOLLOWUP_CHANNELS:
        return
    with conversation_delivery_lock(conversation["id"]):
        try:
            repo.stop_on_reply(_scope(conversation, company_id), datetime.now(timezone.utc).isoformat())
        except APIError as exc:
            # While the scheduler is off a rolling release can precede migration 086.
            if _enabled() or exc.code not in {"42P01", "PGRST205"}:
                raise RuntimeError("Follow-up cancellation unavailable") from None


_TOUCHES = (
    "Ask one helpful question about the need the customer described.",
    "Explain one benefit linked to that need and give one clear next step.",
    "Make one clear offer supported by the retrieved knowledge.",
)
_GENTLE = "Give one friendly, helpful reminder with no pressure."
_CHECK_IN = "Ask how the purchase went and mention one related item from the knowledge."
_STYLE = (" Write one message of at most three short sentences in the customer's language. "
          "Use the conversation and business knowledge. Never invent urgency or stock, "
          "repeat an offer the customer declined, or add buttons or hidden notes.")


def _enabled():
    return os.getenv("FOLLOWUP_SCHEDULER_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def _limit(row):
    return 3 if row["mode"] == "sales" and row["kind"] == "sales" else 1


def _stop(row, reason, at):
    repo.settle(row, {"status": "finished" if reason == "no_reply" else "stopped",
                      "stop_reason": reason, "updated_at": at.isoformat()})


def _prepare(row, at, *, before_send=False):
    reason, chat, customer = _eligibility(row, row["platform"], row["source_message_id"], at, before_send=before_send)
    if reason:
        _stop(row, reason, at)
        return
    if follow_up_mode(chat["chatbots"].get("industry_template_published")) != row["mode"]:
        _stop(row, "mode_changed", at)
        return
    lead = repo.latest_lead(row) or {}
    if lead.get("status") == "lost":
        _stop(row, "lead_lost", at)
        return
    if row.get("won_lead_id") and lead.get("status") != "won":
        _stop(row, "lead_changed", at)
        return
    if row["kind"] == "check_in":
        if lead.get("status") != "won" or lead.get("id") != row.get("won_lead_id"):
            _stop(row, "lead_changed", at)
            return
    elif lead.get("status") == "won":
        won_at = parse_iso_datetime(row.get("won_at") or lead.get("follow_up_won_at"))
        if row["mode"] == "sales" and won_at:
            due = won_at + timedelta(days=7)
            repo.finish_won(row, lead["id"], _allowed_time(due).isoformat())
        else:
            _stop(row, "lead_won", at)
        return
    if row["touch_count"] >= _limit(row):
        _stop(row, "no_reply", at)
        return
    allowed = _allowed_time(at)
    if allowed != at:
        repo.settle(row, {"next_due_at": allowed.isoformat(), "updated_at": at.isoformat()})
        return
    return chat, customer


def _send(row, chat, customer, draft, clock):
    at = clock()
    allowed = _allowed_time(at)
    if allowed != at:
        repo.settle(row, {"next_due_at": allowed.isoformat(), "updated_at": at.isoformat()})
        return
    if not repo.reserve_send(row, at):
        return
    receipt_id = None
    template = None
    try:
        result, template = deliver_follow_up(chat, draft, last_customer_at=customer.get("created_at"), clock=clock)
        accepted = delivery_accepted(row["platform"], result) if result is not None else None
        if accepted and row["platform"] == "whatsapp":
            receipt_id = whatsapp_receipt_id(result)
    except ChannelDeliveryError as error:
        if error.code == "template_missing":
            repo.settle(row, {"status": "stopped", "stop_reason": error.code, "updated_at": clock().isoformat()},
                        reserved=True)
            return
        accepted = False
    except Exception:
        accepted = None
    at = clock()
    fields = {"status": "stopped", "stop_reason": "delivery_failed" if accepted is False else "needs_review",
              "updated_at": at.isoformat()}
    if accepted is True:
        count = row["touch_count"] + 1
        final = count >= _limit(row)
        due = at + timedelta(days=3 if final else count)
        fields.update(status="active", stop_reason=None, touch_count=count, last_touch_at=at.isoformat(),
                      next_due_at=(due if final else _allowed_time(due)).isoformat())
    if template is None and draft is None:
        # Original channel or template lookup failed before a message was available.
        repo.settle(row, fields, reserved=True)
        return
    # A failed transcript write leaves the pre-dispatch review fence in place.
    saved = save_message(conversation_id=chat["id"], sender_type="bot", message_type="template" if template else "text",
                         message_text=f"{template['name']} ({template['language']})" if template else draft,
                         ai_generated=template is None,
                         delivery_status="sent" if accepted is True else "permanent_failed",
                         platform_message_id=receipt_id,
                         follow_up_sent_at=at.isoformat() if accepted is True else None,
                         last_error=fields["stop_reason"])
    if not saved:
        raise RuntimeError("Follow-up transcript unavailable")
    repo.settle(row, fields, reserved=True)


def _execute(row, clock):
    prepared = _prepare(row, clock())
    if not prepared:
        return
    chat, customer = prepared
    draft = None
    if row["platform"] != "whatsapp" or whatsapp_window_open(customer.get("created_at"), clock()):
        try:
            draft = _draft(row, chat, customer)
        except BillingLimitError:
            _stop(row, "billing_blocked", clock())
            return
        except Exception:
            _stop(row, "generation_failed", clock())
            return
        if not draft:
            _stop(row, "held_by_check", clock())
            return
    with conversation_delivery_lock(row["conversation_id"]):
        if not _enabled():
            return
        prepared = _prepare(row, clock(), before_send=True)
        if prepared:
            _send(row, *prepared, draft, clock)


def _draft(row, chat, customer):
    if row["kind"] == "check_in":
        instruction = _CHECK_IN
    elif row["mode"] == "gentle":
        instruction = _GENTLE
    else:
        instruction = _TOUCHES[row["touch_count"]]
    return generate_follow_up_draft(chat, customer, instruction + _STYLE,
                                    require_knowledge=row["kind"] == "check_in" or row["touch_count"] == 2)


def run_due_follow_ups(limit=1, *, now=None):
    if not _enabled():
        return 0
    rows = repo.claim_due(limit)
    for row in rows:
        try:
            _execute(row, lambda: now or datetime.now(timezone.utc))
        except Exception:
            logger.warning("Follow-up unavailable company_id=%s conversation_id=%s mode=%s touch=%s",
                           row["company_id"], row["conversation_id"], row["mode"], row["touch_count"] + 1)
    return len(rows)


def _scheduler_loop():
    time.sleep(120)
    while True:
        try:
            run_due_follow_ups()
        except Exception:
            logger.warning("Follow-up scheduler unavailable")
        time.sleep(60)


_scheduler_thread = None
_scheduler_lock = threading.Lock()


def start_follow_up_scheduler():
    global _scheduler_thread
    with _scheduler_lock:
        if _enabled() and (_scheduler_thread is None or not _scheduler_thread.is_alive()):
            _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="follow-up-scheduler")
            _scheduler_thread.start()
