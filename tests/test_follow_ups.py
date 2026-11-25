from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("industry, expected", [
    *[(name, "sales") for name in ("retail_shop", "car_workshop", "property_agent",
                                   "travel_agency", "restaurant", "beauty_salon", "tuition_center")],
    ("general", "gentle"), ("unknown", "gentle"), (None, "gentle"), ("clinic", "service_only"),
])
def test_follow_up_mode(industry, expected):
    from app.services.follow_up_service import follow_up_mode

    assert follow_up_mode({"template_id": industry} if industry else None) == expected


NOW = datetime(2026, 11, 22, 2, tzinfo=timezone.utc)  # 10:00 in Kuala Lumpur
SCOPE = {"company_id": 1, "chatbot_id": 2, "conversation_id": 3}


@pytest.fixture
def engine(monkeypatch):
    from app.services import follow_up_service as service

    repo = Mock()
    repo.receipts.return_value = []
    monkeypatch.setattr(service, "repo", repo)
    monkeypatch.setattr(service, "ensure_company_operational", Mock())
    monkeypatch.setattr(service, "can_use_plan_feature", Mock(return_value=True))
    monkeypatch.setattr(service, "is_conversation_escalated", Mock(return_value=False))
    conversation = {"id": 3, "chatbot_id": 2, "source_channel": "telegram", "platform_user_id": "123",
                    "customer_needs": {"stage": "recommend"}}
    bot = {"id": 2, "company_id": 1, "followups_enabled": True,
           "industry_template_published": {"template_id": "retail_shop"}}
    repo.conversation.return_value = {**conversation, "chatbots": bot}
    repo.latest_customer.return_value = {"id": 8, "created_at": NOW.isoformat(), "message_text": "A small bag"}
    repo.consent_status.return_value = "granted"
    repo.latest_lead.return_value = None
    monkeypatch.setenv("FOLLOWUP_SCHEDULER_ENABLED", "true")
    return service, repo, conversation, bot


@pytest.mark.parametrize("industry, hours", [("retail_shop", 4), ("general", 24), ("clinic", None)])
def test_schedule_by_industry(engine, industry, hours):
    service, repo, conversation, bot = engine
    bot["industry_template_published"]["template_id"] = industry
    service.schedule_after_reply(conversation, 1, 8, now=NOW)
    if hours is None:
        repo.schedule.assert_not_called()
    else:
        payload = repo.schedule.call_args.args[0]
        assert payload["next_due_at"] == (NOW + timedelta(hours=hours)).isoformat()
        assert payload["source_message_id"] == 8
        assert {key: payload[key] for key in SCOPE} == SCOPE


@pytest.mark.parametrize("platform", ["telegram", "whatsapp_link"])
@pytest.mark.parametrize("condition", ["unsupported", "non_pro", "disabled", "asked", "won", "lost", "clinic",
                                       "withdrawn", "absent", "staff", "understand", "newer_message", "inactive"])
def test_schedule_requires_eligible_conversation(engine, platform, condition):
    service, repo, conversation, bot = engine
    conversation["source_channel"] = repo.conversation.return_value["source_channel"] = platform
    if condition == "unsupported":
        conversation["source_channel"] = repo.conversation.return_value["source_channel"] = "web"
    elif condition in {"won", "lost"}:
        repo.latest_lead.return_value = {"status": condition}
    elif condition == "clinic":
        bot["industry_template_published"]["template_id"] = "clinic"
    elif condition == "non_pro":
        service.can_use_plan_feature.return_value = False
    elif condition == "inactive":
        service.ensure_company_operational.side_effect = service.CompanyOperationalStatusError("inactive", "inactive")
    elif condition == "disabled":
        bot["followups_enabled"] = False
    elif condition == "staff":
        service.is_conversation_escalated.return_value = True
    elif condition == "understand":
        conversation["customer_needs"]["stage"] = "understand"
    elif condition == "newer_message":
        repo.latest_customer.return_value["id"] = 9
    else:
        repo.consent_status.return_value = None if condition == "absent" else condition
    service.schedule_after_reply(conversation, 1, 8, now=NOW)
    repo.schedule.assert_not_called()



@pytest.fixture
def due(engine, monkeypatch):
    service, repo, conversation, bot = engine
    row = {**SCOPE, "id": 5, "platform": "telegram", "mode": "sales", "kind": "sales",
           "source_message_id": 8, "lease_token": "lease-a", "touch_count": 0,
           "next_due_at": NOW.isoformat(), "scheduled_at": (NOW - timedelta(hours=4)).isoformat()}
    repo.claim_due.return_value = [row]
    repo.reserve_send.return_value = True
    repo.settle.return_value = True
    draft = Mock(return_value="Would a small bag work?")
    send = Mock(return_value=({"ok": True}, None))
    save = Mock(return_value={"id": 14})
    monkeypatch.setattr(service, "generate_follow_up_draft", draft)
    monkeypatch.setattr(service, "deliver_follow_up", send)
    monkeypatch.setattr(service, "save_message", save)
    return service, repo, row, draft, send, save


@pytest.mark.parametrize("mode,count,next_days", [("sales", 0, 1), ("sales", 1, 2), ("sales", 2, 3),
                                                  ("gentle", 0, 3)])
def test_follow_up_delivered_touch(due, mode, count, next_days):
    service, repo, row, draft, send, save = due
    row.update(mode=mode, touch_count=count)
    if mode == "gentle":
        repo.conversation.return_value["chatbots"]["industry_template_published"] = {}
    assert service.run_due_follow_ups(now=NOW) == 1
    draft.assert_called_once()
    assert send.call_args.args[0]["platform_user_id"] == "123"
    assert send.call_args.args[1] == draft.return_value
    assert save.call_args.kwargs["ai_generated"] and save.call_args.kwargs["sender_type"] == "bot"
    assert save.call_args.kwargs["delivery_status"] == "sent"
    fields = repo.settle.call_args.args[1]
    assert fields["touch_count"] == count + 1
    assert save.call_args.kwargs["follow_up_sent_at"] == NOW.isoformat()
    assert fields["next_due_at"] == (NOW + timedelta(days=next_days)).isoformat()


def test_linked_whatsapp_schedules_one_gentle_reminder_even_for_sales_bots(due):
    service, repo, row, draft, send, save = due
    chat = repo.conversation.return_value
    chat["source_channel"] = "whatsapp_link"
    service.schedule_after_reply(chat, 1, 8, now=NOW)
    repo.schedule.assert_called_once()
    row.update(repo.schedule.call_args.args[0])
    due_at = NOW + timedelta(days=1)
    assert row["next_due_at"] == due_at.isoformat()
    assert (row["platform"], row["source_message_id"]) == ("whatsapp_link", 8)
    repo.consent_status.assert_called_once_with(1, "whatsapp_link", chat["platform_user_id"])
    send.return_value = (True, None)
    service.run_due_follow_ups(now=due_at)
    draft.assert_called_once_with(chat, repo.latest_customer.return_value,
                                  service._GENTLE + service._STYLE, require_knowledge=False)
    assert save.call_args.kwargs["delivery_status"] == "sent"
    row.update(repo.settle.call_args.args[1])
    assert row["touch_count"] == 1
    service.run_due_follow_ups(now=due_at + timedelta(days=3))
    assert repo.settle.call_args.args[1]["stop_reason"] == "no_reply"
    send.assert_called_once()
    draft.assert_called_once()


def test_linked_whatsapp_win_never_schedules_check_in(due):
    service, repo, row, draft, send, _ = due
    repo.conversation.return_value["source_channel"] = "whatsapp_link"
    row.update(platform="whatsapp_link", mode="gentle")
    repo.latest_lead.return_value = {"id": 9, "status": "won", "follow_up_won_at": NOW.isoformat()}
    service.run_due_follow_ups(now=NOW)
    assert repo.settle.call_args.args[1]["stop_reason"] == "lead_won"
    repo.finish_won.assert_not_called()
    draft.assert_not_called()
    send.assert_not_called()


@pytest.mark.parametrize("condition,reason", [
    ("held", "held_by_check"), ("replied", "customer_replied"), ("withdraw_during_draft", "consent_missing"),
    ("handoff_during_draft", "staff_handling"), ("lost", "lead_lost"), ("sales_limit", "no_reply"),
    ("gentle_limit", "no_reply"), ("won_gentle", "lead_won"),
])
def test_follow_up_stops_without_sending(due, condition, reason):
    service, repo, row, draft, send, _ = due
    if condition == "held":
        draft.return_value = None
    elif condition == "replied":
        repo.latest_customer.return_value["id"] = 9
    elif condition == "withdraw_during_draft":
        repo.consent_status.side_effect = ["granted", "withdrawn"]
    elif condition == "handoff_during_draft":
        service.is_conversation_escalated.side_effect = [False, True]
    elif condition == "lost":
        repo.latest_lead.return_value = {"id": 99, "status": "lost"}
    elif condition == "sales_limit":
        row["touch_count"] = 3
    else:
        row.update(mode="gentle", touch_count=1)
        repo.conversation.return_value["chatbots"]["industry_template_published"] = {}
        if condition == "won_gentle":
            repo.latest_lead.return_value = {"id": 99, "status": "won"}
    service.run_due_follow_ups(now=NOW)
    send.assert_not_called()
    assert repo.settle.call_args.args[1]["stop_reason"] == reason
    assert repo.settle.call_args.args[1]["status"] == ("finished" if reason == "no_reply" else "stopped")


@pytest.mark.parametrize("hour,expected_day", [(13, 23), (0, 22)])
def test_follow_up_quiet_hours(due, hour, expected_day):
    service, repo, _, draft, send, _ = due
    service.run_due_follow_ups(now=NOW.replace(hour=hour))
    assert repo.settle.call_args.args[1]["next_due_at"] == NOW.replace(day=expected_day, hour=1).isoformat()
    draft.assert_not_called()
    send.assert_not_called()


def test_follow_up_won_uses_time_of_win(due):
    service, repo, row, draft, send, _ = due
    won = NOW - timedelta(days=2)
    row.update(won_at=won.isoformat(), won_lead_id=7)
    repo.latest_lead.return_value = {"id": 7, "status": "won", "updated_at": NOW.isoformat()}
    service.run_due_follow_ups(now=NOW)
    repo.finish_won.assert_called_once_with(row, 7, (won + timedelta(days=7)).isoformat())
    draft.assert_not_called()
    send.assert_not_called()


def test_follow_up_win_concurrent_with_scheduling_ignores_later_crm_note(due):
    service, repo, row, _, send, _ = due
    won = NOW - timedelta(days=2)
    repo.latest_lead.return_value = {"id": 7, "status": "won", "updated_at": NOW.isoformat(),
                                     "follow_up_won_at": won.isoformat()}
    service.run_due_follow_ups(now=NOW)
    repo.finish_won.assert_called_once_with(row, 7, (won + timedelta(days=7)).isoformat())
    send.assert_not_called()


@pytest.mark.parametrize("outcome,reason", [({"ok": False}, "delivery_failed"), (None, "needs_review")])
def test_follow_up_provider_outcome(due, outcome, reason):
    service, repo, _, _, send, save = due
    send.return_value = (outcome, None)
    service.run_due_follow_ups(now=NOW)
    assert repo.settle.call_args.args[1]["stop_reason"] == reason
    assert save.call_args.kwargs["delivery_status"] == "permanent_failed"
    assert send.call_count == 1


def test_follow_up_stale_lease_never_dispatches(due):
    service, repo, _, _, send, save = due
    repo.reserve_send.return_value = False
    service.run_due_follow_ups(now=NOW)
    send.assert_not_called()
    save.assert_not_called()
    repo.settle.assert_not_called()


@pytest.mark.parametrize("followed,withdrawals,stops", [(19, 2, False), (20, 1, False), (20, 2, True)])
def test_follow_up_auto_stop_at_dispatch(due, followed, withdrawals, stops):
    service, repo, row, draft, send, _ = due
    day = timedelta(days=1)
    bot = repo.conversation.return_value["chatbots"]
    bot["followups_enabled_at"] = (NOW - 12 * day).isoformat()
    rows = [{"conversation_id": i, "sent_at": touch,
             "withdrawn_at": NOW - 2 * day if i < withdrawals else None}
            for i in range(followed) for touch in (NOW - 3 * day, NOW - day)]
    rows += [{"conversation_id": 101, "sent_at": NOW - 31 * day, "withdrawn_at": NOW},
             {"conversation_id": 102, "sent_at": NOW - 13 * day, "withdrawn_at": NOW},
             {"conversation_id": 3, "sent_at": NOW - day, "withdrawn_at": NOW - 5 * day}]
    repo.receipts.return_value = rows

    def persist_stop(current, at, counts):
        assert current["id"] == 2 and current["company_id"] == 1
        assert counts == {"followed": 20, "opted_out": 2, "percent": 10.0}
        bot.update(followups_enabled=False, followups_auto_stopped_at=at.isoformat())
        return True

    repo.auto_stop.side_effect = persist_stop
    service.run_due_follow_ups(now=NOW)
    repo.receipts.assert_called_once_with(1, 2, NOW - 12 * day, NOW)
    if stops:
        service.run_due_follow_ups(now=NOW)
        repo.auto_stop.assert_called_once()
        send.assert_not_called()
        repo.reserve_send.assert_not_called()
    else:
        repo.auto_stop.assert_not_called()
        send.assert_called_once()


def test_followup_accepted_transcript_survives_unsettled_lease(due):
    service, repo, _, _, send, save = due
    repo.settle.return_value = False
    service.run_due_follow_ups(now=NOW)
    send.assert_called_once()
    assert save.call_args.kwargs["follow_up_sent_at"] == NOW.isoformat()
    assert save.call_args.kwargs["delivery_status"] == "sent"


def test_follow_up_any_inbound_stops_before_other_work(engine):
    service, repo, conversation, _ = engine
    service.stop_for_customer_reply(conversation, 1)
    assert repo.stop_on_reply.call_args.args[0] == SCOPE


@pytest.mark.parametrize("filter_flag,findings,verdict,expected", [
    (None, [], {"verdict": "pass"}, "Would that help?"),
    ("flag", [], {"verdict": "pass"}, None),
    (None, [{"category": "facts", "subtype": "price"}], {"verdict": "pass"}, None),
    (None, [], {"verdict": "hold", "category": "promise", "subtype": "discount"}, None),
    (None, [], None, None),
])
def test_follow_up_real_router_and_outbound_checks(engine, monkeypatch, filter_flag, findings, verdict, expected):
    from app.services import ai_router as ai, reply_check_service as checks, reply_review_service as reviewer
    from types import SimpleNamespace

    _, repo, _, bot = engine
    chat = repo.conversation.return_value
    bot.update(ai_provider="openrouter", model_name="test-model")
    pipeline = {"knowledge": [], "history": [], "profile": {}, "review_history": []}
    provider = Mock(return_value=SimpleNamespace(success=True, is_provider_response=True, text="Would that help?",
                                                 reply_pipeline=pipeline))
    charge = Mock()
    monkeypatch.setattr(ai, "call_provider", provider)
    monkeypatch.setattr(ai, "_make_usage_log", charge)
    monkeypatch.setattr(ai, "_route_for_enforcement", lambda *a: ("openrouter", "test-model"))
    monkeypatch.setattr(ai, "customer_on_cooldown", lambda *a: False)
    monkeypatch.setattr(ai, "review_customer_message", lambda *a, **kw: None)
    monkeypatch.setattr(ai.content_filter, "check_bot_text", lambda text, bot_id: filter_flag if text == "Would that help?" else None)
    monkeypatch.setattr(checks, "check_reply", Mock(return_value=findings))
    monkeypatch.setattr(reviewer, "needs_review", lambda *a: True)
    monkeypatch.setattr(reviewer, "review_reply", Mock(return_value=verdict))
    monkeypatch.setenv("REPLY_CHECK_MODE", "off")
    assert ai.generate_follow_up_draft(chat, repo.latest_customer.return_value, "Ask about their need.") == expected
    assert provider.call_args.args[2] == chat["platform_user_id"]
    charge.assert_called_once()
    if not filter_flag:
        checks.check_reply.assert_called_once()
    if expected:
        assert ai.generate_follow_up_draft(chat, repo.latest_customer.return_value, "Make an offer.",
                                           require_knowledge=True) is None


def test_follow_up_settle_fences_tenant_and_lease(monkeypatch):
    from app.database import follow_up_repository as repository
    from unittest.mock import MagicMock

    db = MagicMock()
    query = db.table.return_value.update.return_value
    query.eq.return_value = query
    query.execute.return_value.data = []
    monkeypatch.setattr(repository.db, "supabase", db)
    row = {**SCOPE, "id": 7, "lease_token": "stale"}
    assert not repository.settle(row, {"status": "finished"})
    for key in (*SCOPE, "id", "lease_token"):
        query.eq.assert_any_call(key, row[key])


def test_follow_up_migration_fences_work_and_limits_access():
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[1] / "data/086_follow_ups.sql").read_text().lower()
    for required in ("for update skip locked", "enable row level security", "where status = 'active'",
                     "from public, anon, authenticated", "to service_role", "lease_expires_at",
                     "on conflict", "check_in", "lead_won"):
        assert required in sql


@pytest.mark.parametrize("flag,starts", [(None, 0), ("false", 0), ("true", 1)])
def test_wsgi_follow_up_flag(monkeypatch, flag, starts):
    import runpy
    from pathlib import Path
    import app
    from app.services import follow_up_service, document_storage_migration, knowledge_ingest_queue

    start = Mock()
    monkeypatch.setattr(follow_up_service, "start_follow_up_scheduler", start)
    monkeypatch.setattr(app, "create_app", Mock())
    monkeypatch.setattr(document_storage_migration, "migrate_before_startup", Mock())
    monkeypatch.setattr(knowledge_ingest_queue, "start_consumer", Mock())
    monkeypatch.setenv("BILLING_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("GEO_MONITORING_SCHEDULER_ENABLED", "false")
    if flag is None:
        monkeypatch.delenv("FOLLOWUP_SCHEDULER_ENABLED", raising=False)
    else:
        monkeypatch.setenv("FOLLOWUP_SCHEDULER_ENABLED", flag)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "wsgi.py"))
    assert start.call_count == starts


@pytest.mark.parametrize("kind,expected", [("check_in", "purchase"), ("sales", "offer")])
def test_follow_up_last_touch_then_silent_close(due, kind, expected):
    service, repo, row, draft, send, _ = due
    row.update(kind=kind, touch_count=0 if kind == "check_in" else 2)
    if kind == "check_in":
        row["won_lead_id"] = 17
        repo.latest_lead.return_value = {"id": 17, "status": "won"}
    service.run_due_follow_ups(now=NOW)
    assert expected in draft.call_args.args[-1]
    row.update(repo.settle.call_args.args[1])
    assert row["next_due_at"] == (NOW + timedelta(days=3)).isoformat()
    service.run_due_follow_ups(now=NOW + timedelta(days=3))
    assert repo.settle.call_args.args[1]["stop_reason"] == "no_reply"
    assert send.call_count == 1


def test_official_whatsapp_schedules_with_granted_recipient_consent(engine):
    service, repo, conversation, _ = engine
    conversation["source_channel"] = repo.conversation.return_value["source_channel"] = "whatsapp"
    service.schedule_after_reply(conversation, 1, 8, now=NOW)
    assert repo.schedule.call_args.args[0]["platform"] == "whatsapp"
    repo.consent_status.assert_called_once_with(1, "whatsapp", "123")


def test_inbound_before_migration_still_processes(engine, monkeypatch):
    from postgrest.exceptions import APIError

    service, repo, chat, _ = engine
    monkeypatch.delenv("FOLLOWUP_SCHEDULER_ENABLED")
    repo.stop_on_reply.side_effect = APIError({"code": "PGRST205", "message": "Table missing"})
    service.stop_for_customer_reply(chat, 1)


def test_follow_up_kill_switch_prevents_claim(due, monkeypatch):
    service, repo, _, _, send, _ = due
    monkeypatch.delenv("FOLLOWUP_SCHEDULER_ENABLED")
    assert service.run_due_follow_ups(now=NOW) == 0
    repo.claim_due.assert_not_called()
    send.assert_not_called()


def test_follow_up_bound_channel_must_share_company(engine, monkeypatch):
    from app.services import channel_delivery_service as delivery
    from app.utils import telegram_utils

    _, repo, _, _ = engine
    monkeypatch.setattr(delivery, "get_bound_channel", lambda chat: {"company_id": 91, "bot_token": "test"})
    send = Mock()
    monkeypatch.setattr(telegram_utils, "send_telegram_message", send)
    with pytest.raises(delivery.ChannelDeliveryError):
        delivery.deliver_follow_up(repo.conversation.return_value, "Would that help?")
    send.assert_not_called()


def test_follow_up_moderation_uses_chat_handoff_without_customer_acknowledgement(engine, monkeypatch):
    from app.services import ai_router as ai

    _, repo, _, _ = engine
    chat = repo.conversation.return_value
    blocked = ai.openrouter_service.ModerationBlocked()
    monkeypatch.setattr(ai, "customer_on_cooldown", lambda *a: False)
    monkeypatch.setattr(ai, "review_customer_message", lambda *a, **kw: None)
    monkeypatch.setattr(ai, "_route_for_enforcement", lambda *a: ("openrouter", "test"))
    monkeypatch.setattr(ai, "call_provider", Mock(side_effect=blocked))
    handoff = Mock(return_value="Staff notified")
    monkeypatch.setattr(ai, "hand_off_after_moderation_block", handoff)
    assert ai.generate_follow_up_draft(chat, repo.latest_customer.return_value, "Ask about their need.") is None
    handoff.assert_called_once_with(2, chat, blocked)


def test_follow_up_prompt_retrieves_for_customer_without_starting_inbound_work(engine, monkeypatch):
    from app.services import chat_pipeline_service as pipeline

    _, repo, _, _ = engine
    chat = repo.conversation.return_value
    monkeypatch.setattr("app.database.agent_action_repository.is_conversation_escalated", lambda *a, **kw: False)
    history = [{"role": "user", "content": "Beg kecil"}]
    monkeypatch.setattr(pipeline, "get_recent_chat_history", lambda *a, **kw: history)
    monkeypatch.setattr(pipeline.content_filter, "clean_history", lambda turns, bot: turns)
    retrieve = Mock(return_value=[{"id": 7, "content": "Small bag"}])
    monkeypatch.setattr(pipeline, "retrieve_relevant_chunks", retrieve)
    build = Mock(return_value="Business prompt")
    monkeypatch.setattr(pipeline, "build_prompt", build)
    intent, workflow = Mock(), Mock()
    monkeypatch.setattr(pipeline, "analyze_agent_intent", intent)
    monkeypatch.setattr(pipeline, "update_workflow_state", workflow)
    prepared = pipeline.prepare_chat_prompt("Beg kecil", "123", 2, "telegram", chat,
                                            follow_up_instruction="Ask one helpful question.")
    assert retrieve.call_args.args == ("Beg kecil",)
    assert build.call_args.kwargs["customer_needs"] == {"stage": "recommend"}
    assert prepared["history"] == history and prepared["knowledge"] == retrieve.return_value
    assert "Business prompt" in prepared["prompt"] and "Ask one helpful question." in prepared["prompt"]
    intent.assert_not_called()
    workflow.assert_not_called()
