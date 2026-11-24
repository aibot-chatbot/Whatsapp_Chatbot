import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import broadcast_repository, company_repository, message_repository
from app.services import channel_delivery_service as delivery
from app.services import channel_server_service as linked
from app.utils import telegram_utils as tg, whatsapp_utils as wa


def test_marketing_consent_migration_and_rollback():
    data = Path(__file__).resolve().parents[1] / "data"
    sql = (data / "085_marketing_consents.sql").read_text().lower()
    undo = (data / "085_marketing_consents_rollback.sql").read_text().lower()
    for phrase in (
        "unique (company_id, platform, platform_user_id)", "enable row level security",
        "where phone_digits is not null", "grant select, insert, update",
        "grant usage, select on sequence", "to service_role",
        "followups_enabled boolean not null default false", "broadcast_logs_status_check",
        "'skipped'", "evidence_message_id", "asked_at", "granted_at", "withdrawn_at",
    ):
        assert phrase in sql
    for column in ("followups_enabled", "consent_confirmed_by", "consent_confirmed_at"):
        assert f"drop column if exists {column}" in undo
    assert "drop table if exists public.marketing_consents" in undo
    assert "check (status in ('pending', 'sending', 'sent', 'failed', 'cancelled'))" in undo


CHANNELS = ("telegram", "whatsapp", "whatsapp_link")
CONFIRMATIONS = [
    ("  🛑 StOp ALL!!! ", "Done. You won't get updates from Acme any more. You can still message us any time."),
    ("Berhenti langganan!", "Baik. Anda tidak akan menerima maklumat terkini daripada Acme lagi. Anda masih boleh menghubungi kami bila-bila masa."),
    ("「退订」", "好的，您将不会再收到Acme的更新。您仍可随时联系我们。"),
]


@pytest.fixture
def inbound(monkeypatch):
    def setup(platform, *, address=None, paused=False):
        address = address or {"telegram": "123", "whatsapp": "MY.BSUID.12345",
                              "whatsapp_link": "60123456789@c.us"}[platform]
        key = {"telegram": "telegram_bot_id", "whatsapp": "phone_number_id",
               "whatsapp_link": "phone_number"}[platform]
        channel = {"id": 4, "chatbot_id": 6, "company_id": 11, key: "200", "verified_at": "today",
                   "is_active": True, "connection_status": "connected", "session_name": "demo", "bot_token": "demo"}
        chat = {"id": 8, "source_channel": platform, "source_channel_id": 4, "source_provider_id": "200",
                "chatbot_id": 6, "platform_user_id": address, "customer_phone": "+60123456789"}
        bot = {"id": 6, "company_id": 11, "followups_enabled": False}
        messages, sent = [], []
        monkeypatch.setattr(message_repository, "find_consent_evidence", lambda *args: None)
        def save(**row):
            messages.append(row)
            return {"id": len(messages)}
        module = {"telegram": tg, "whatsapp": wa, "whatsapp_link": linked}[platform]
        generate = Mock(return_value="Normal reply")
        resume = Mock(return_value=False)
        pause = Mock(return_value=paused)
        for target, name, val in [
            (module, "save_message", save), (message_repository, "save_message", save),
            (module, "is_conversation_escalated", pause), (module, "resume_ai_after_staff_idle", resume),
            (module, "generate_response", generate), (company_repository, "get_company_by_id",
             lambda company: {"id": company, "company_name": "Acme"}),
        ]:
            monkeypatch.setattr(target, name, val)
        monkeypatch.setattr(delivery, {"telegram": "get_telegram_channel_by_id", "whatsapp": "get_whatsapp_channel_by_id",
                            "whatsapp_link": "get_linked_channel"}[platform], lambda *_: channel)
        if platform == "telegram":
            monkeypatch.setattr(tg, "get_telegram_channel_by_secret", lambda *_: channel)
            monkeypatch.setattr(tg, "claim_telegram_update", lambda *_: True)
            monkeypatch.setattr(tg, "get_or_create_platform_conversation", lambda **_: chat)
            monkeypatch.setattr(tg, "get_bot_by_id", lambda *_: bot)
            monkeypatch.setattr(tg, "dispatch_media_after_reply", Mock())
            def send(token, recipient, text, **kwargs):
                sent.append((recipient, text))
                return {"ok": True}
            monkeypatch.setattr(tg, "send_telegram_message", send)
            def run(text):
                return tg.process_telegram_update({"update_id": 5, "message": {
                    "text": text, "chat": {"type": "private", "id": int(address)},
                    "from": {"id": int(address)}, "message_id": 7}}, "test")
        elif platform == "whatsapp":
            monkeypatch.setattr(wa, "get_whatsapp_channel_by_phone_number_id", lambda *_: channel)
            monkeypatch.setattr(wa, "claim_processed_message", lambda *_: True)
            monkeypatch.setattr(wa, "get_or_create_conversation", lambda **_: chat)
            monkeypatch.setattr(wa, "get_bot_by_id", lambda *_: bot)
            monkeypatch.setattr(wa, "dispatch_media_after_reply", Mock())
            monkeypatch.setattr(wa, "update_workflow_state", Mock())
            def send(data, channel):
                data = json.loads(data)
                sent.append((data["to"], data["text"]["body"]))
                return SimpleNamespace(status_code=200, json=lambda: {"messages": [{}]})
            monkeypatch.setattr(wa, "send_message", send)
            def run(text, *, timestamp=None):
                from time import time
                return wa.process_whatsapp_message({"entry": [{"changes": [{"value": {
                    "metadata": {"phone_number_id": "200"}, "contacts": [{"wa_id": address}],
                    "messages": [{"id": "msg", "type": "text", "timestamp": str(int(time())) if timestamp is None else timestamp,
                                  "text": {"body": text}}]}}]}]})
        else:
            monkeypatch.setattr(linked, "get_or_create_conversation", lambda **_: chat)
            monkeypatch.setattr(linked, "send_text", lambda _, recipient, text: sent.append((recipient, text)) or True)
            def run(text):
                return linked.process_message(channel, {"from": address, "id": "msg", "fromMe": False, "body": text,
                    "_data": {"Info": {"SenderAlt": "60123456789@s.whatsapp.net"}}}, lambda _: True)
        return SimpleNamespace(run=run, messages=messages, sent=sent, resume=resume, generate=generate,
                               address=address, chat=chat, channel=channel, bot=bot, pause=pause)
    return setup


@pytest.mark.parametrize("platform", CHANNELS)
@pytest.mark.parametrize("text,confirmation", CONFIRMATIONS)
def test_stop_while_handed_off(inbound, monkeypatch, platform, text, confirmation):
    h = inbound(platform, paused=True)
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    h.run(text)
    assert h.sent == [(h.address, confirmation)]
    payload = db.table.return_value.upsert.call_args.args[0]
    assert (payload["company_id"], payload["platform"], payload["platform_user_id"]) == (11, platform, h.address)
    assert payload["status"] == "withdrawn" and payload["withdrawn_at"]
    assert payload["evidence_message_id"] == 1 and payload["source"] == "stop_word"
    # The chat's known number is recorded on every channel so phone broadcasts skip it.
    assert payload["phone_digits"] == "60123456789"
    assert [(m["sender_type"], m["ai_generated"]) for m in h.messages] == [("customer", False), ("bot", False)]
    assert h.messages[-1]["message_text"] == confirmation
    h.resume.assert_not_called()
    h.generate.assert_not_called()


@pytest.mark.parametrize("platform", CHANNELS)
@pytest.mark.parametrize("text", ["don't stop", "stop by tomorrow", "停止营业吗"])
def test_non_stop_messages_reach_ai(inbound, platform, text):
    h = inbound(platform)
    h.run(text)
    h.generate.assert_called_once()


@pytest.fixture
def ask_conditions(monkeypatch):
    from app.database import conversation_repository, agent_action_repository
    from app.services import billing_guard
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    feature = Mock(return_value=True)
    stage = {"customer_needs": {"stage": "recommend"}}
    paused = Mock(return_value=False)
    monkeypatch.setattr(billing_guard, "can_use_plan_feature", feature)
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda *_: stage)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", paused)
    return SimpleNamespace(db=db, feature=feature, stage=stage, paused=paused)


@pytest.mark.parametrize("text,lang,expected", [
    ("How much?", "en", "Can we send you updates from Acme here? Reply YES to agree, or STOP any time to stop."),
    ("Berapa harga?", "ms", "Boleh kami hantar maklumat terkini daripada Acme di sini? Balas YA untuk setuju, atau BERHENTI bila-bila masa untuk berhenti."),
    ("多少钱？", "zh", "我们可以在这里向您发送Acme的最新消息吗？回复「是」表示同意，随时回复「停止」即可取消。"),
])
@pytest.mark.parametrize("platform", ["telegram", "whatsapp"])
def test_consent_question_once_after_ai(inbound, ask_conditions, text, lang, expected, platform):
    h = inbound(platform)
    h.bot["followups_enabled"] = True
    table = ask_conditions.db.table.return_value
    claim = table.upsert.return_value.execute
    claim.side_effect = [SimpleNamespace(data=[{"id": 99}]), SimpleNamespace(data=[])]
    h.run(text)
    h.run(text)
    assert [body for _, body in h.sent] == ["Normal reply", expected, "Normal reply"]
    question = h.messages[2]
    assert (question["message_text"], question["ai_generated"], question["delivery_status"]) == (expected, False, "sent")
    fields = table.upsert.call_args.args[0]
    assert (fields["language"], fields["business_name"], fields["status"]) == (lang, "Acme", "asked")
    assert (fields["platform"], fields["platform_user_id"]) == (platform, h.address)
    assert table.upsert.call_args.kwargs == {"on_conflict": "company_id,platform,platform_user_id",
                                           "ignore_duplicates": True}
    ask_conditions.feature.assert_called_with(11, "automation_workflows")


@pytest.mark.parametrize("reason", ["whatsapp_link", "disabled", "non_pro", "staff", "understand", "existing"])
def test_consent_question_gates(inbound, ask_conditions, reason):
    from app.services.billing_guard import BillingLimitError
    h = inbound(reason if reason in CHANNELS else "telegram")
    h.bot["followups_enabled"] = reason != "disabled"
    if reason == "non_pro":
        ask_conditions.feature.side_effect = BillingLimitError("denied")
    if reason == "staff":
        ask_conditions.paused.return_value = True
    if reason == "understand":
        ask_conditions.stage["customer_needs"]["stage"] = "understand"
    ask_conditions.db.table.return_value.upsert.return_value.execute.return_value.data = []
    delivery.maybe_ask_marketing_consent(h.chat, h.channel["company_id"], h.bot, "price?")
    assert h.sent == []
    if reason != "existing":
        ask_conditions.db.table.return_value.upsert.assert_not_called()


@pytest.mark.parametrize("previous,result", [(None, None), ("asked", "granted"), ("withdrawn", "withdrawn")])
@pytest.mark.parametrize("reply", [" YES! ", "ya", "「是」"])
def test_yes_only_grants_pending_and_continues_to_ai(inbound, monkeypatch, previous, result, reply):
    h = inbound("telegram")
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    state = {"status": previous, "company_id": 11, "platform": "telegram", "platform_user_id": h.address}
    query = db.table.return_value.update.return_value
    filters = {}
    query.eq.side_effect = lambda key, value: (filters.update({key: value}) or query)
    def execute():
        assert filters == {"company_id": 11, "platform": "telegram", "platform_user_id": h.address, "status": "asked"}
        if all(state.get(k) == v for k, v in filters.items()):
            state.update(db.table.return_value.update.call_args.args[0])
        return SimpleNamespace(data=[])
    query.not_.is_.return_value = query
    query.execute.side_effect = execute
    h.run(reply)
    assert state["status"] == result
    query.not_.is_.assert_called_once_with("asked_at", "null")
    if result == "granted":
        assert state["evidence_message_id"] == 1 and state["granted_at"] and state["source"] == "chat_reply"
    assert len(h.sent) == 1
    h.generate.assert_called_once()


def test_broadcast_skips_only_this_companys_withdrawn_phones(monkeypatch):
    from flask import Flask
    from app.routes import broadcast_routes as routes
    from app.database import whatsapp_channel_repository

    rows = [{"company_id": 1, "phone_digits": "60100000001", "status": "withdrawn"},
            {"company_id": 2, "phone_digits": "60100000002", "status": "withdrawn"}]
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    def select(fields):
        query = Mock()
        filters = {}
        query.eq.side_effect = lambda k, v: (filters.update({k: v}) or query)
        query.limit.return_value = query
        query.execute.side_effect = lambda: SimpleNamespace(data=[
            row for row in rows if all(row.get(k) == v for k, v in filters.items())])
        return query
    db.table.return_value.select.side_effect = select
    campaign = {"id": 14, "chatbot_id": 6, "company_id": 1, "channel_type": "whatsapp", "message_template": "Hello"}
    monkeypatch.setattr(routes, "get_campaign_by_id", lambda *_: campaign)
    monkeypatch.setattr(whatsapp_channel_repository, "get_whatsapp_channels_by_chatbot", lambda *_: [{"is_active": True}])
    updates = Mock()
    monkeypatch.setattr(routes, "update_broadcast_log_status", updates)
    monkeypatch.setattr(routes, "update_campaign_status", Mock())
    monkeypatch.setattr(routes.time, "sleep", Mock())
    send = Mock(return_value=SimpleNamespace(status_code=200))
    monkeypatch.setattr(wa, "send_message", send)
    logs = [{"id": i, "recipient_phone": phone} for i, phone in enumerate(["+60 10-000-0001", "+60100000002"], 1)]
    routes.process_broadcast_dispatch(Flask(__name__), campaign, logs)
    assert [call.args[:2] for call in updates.call_args_list] == [(1, "skipped"), (2, "sending"), (2, "sent")]
    send.assert_called_once()
    assert json.loads(send.call_args.args[0])["to"] == "+60100000002"


def test_stop_from_unresolved_linked_lid_uses_lid_only(inbound, monkeypatch):
    h = inbound("whatsapp_link", address="9876543210@lid", paused=True)
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    monkeypatch.setattr(linked, "_request", lambda *args, **kwargs: {})
    from app.database import conversation_repository
    find = Mock(return_value={**h.chat, "customer_phone": None})
    monkeypatch.setattr(conversation_repository, "get_or_create_platform_conversation", find)
    linked.process_message(h.channel, {"from": h.address, "fromMe": False, "id": "9", "body": "STOP"}, lambda _: True)
    assert h.sent == [(h.address, CONFIRMATIONS[0][1])]
    assert find.call_args.kwargs["platform_user_id"] == h.address
    assert db.table.return_value.upsert.call_args.args[0]["phone_digits"] is None
    h.generate.assert_not_called()


def test_linked_vote_stop_preserves_original_reply_chat(inbound, monkeypatch):
    h = inbound("whatsapp_link", address="999999999@lid", paused=True)
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    monkeypatch.setattr(linked, "find_open_conversation", lambda **_: h.chat)
    monkeypatch.setattr(linked, "get_latest_bot_message_text", lambda *_: "Choose [BUTTONS: STOP | Back]")
    linked.process_poll_vote(h.channel, {"vote": {"fromMe": False, "from": "60123456789@c.us",
                              "id": "123", "selectedOptions": ["STOP"]}}, lambda _: True)
    assert h.sent == [(h.address, CONFIRMATIONS[0][1])]
    assert db.table.return_value.upsert.call_args.args[0]["phone_digits"] == "60123456789"
    h.generate.assert_not_called()


def test_stop_storage_failure_does_not_expose_recipient_or_confirm(inbound, monkeypatch):
    h = inbound("whatsapp")
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    monkeypatch.setattr(wa, "release_processed_message_claim", Mock())
    db.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("private data " + h.address)
    with pytest.raises(RuntimeError, match="Could not record marketing consent") as error:
        h.run("STOP")
    assert h.address not in str(error.value)
    assert h.sent == []
    h.generate.assert_not_called()


def test_meta_stop_redelivery_reuses_evidence_and_sends_once(inbound, monkeypatch):
    h = inbound("whatsapp")
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    monkeypatch.setattr(message_repository, "find_consent_evidence",
                        lambda *_: {"id": 1} if h.messages else None)
    db.table.return_value.upsert.return_value.execute.side_effect = [OSError("transient DB error"), None]
    release = Mock()
    monkeypatch.setattr(wa, "release_processed_message_claim", release)
    with pytest.raises(RuntimeError, match="Could not record marketing consent"):
        h.run("STOP")
    release.assert_called_once_with(6, "msg")
    h.run("STOP")
    assert [row["sender_type"] for row in h.messages] == ["customer", "bot"]
    assert h.sent == [(h.address, CONFIRMATIONS[0][1])]
    assert db.table.return_value.upsert.call_args.args[0]["evidence_message_id"] == 1


@pytest.mark.parametrize("platform", CHANNELS)
@pytest.mark.parametrize("reply", ["ok", "YES", "好"])
def test_everyday_yes_is_answered_when_consent_storage_fails(inbound, monkeypatch, platform, reply):
    # "ok"/"yes" are common replies; a consent-store outage must cost the consent, never the answer.
    h = inbound(platform)
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    monkeypatch.setattr(message_repository, "find_consent_evidence", Mock(side_effect=OSError("db down")))
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value \
        .not_.is_.return_value.execute.side_effect = OSError("db down")
    h.run(reply)
    h.generate.assert_called_once()
    assert [row["sender_type"] for row in h.messages][:1] == ["customer"]


def test_lid_stop_records_the_chats_known_phone_for_broadcast_matching(inbound, monkeypatch):
    # Live 2026-11-22: a STOP arrived on a LID; without the chat's phone, phone broadcasts would not skip it.
    h = inbound("whatsapp_link", address="555123@lid")
    db = Mock()
    monkeypatch.setattr(broadcast_repository, "supabase", db)
    monkeypatch.setattr(linked, "find_open_conversation", lambda **_: h.chat)
    h.run("STOP")
    assert db.table.return_value.upsert.call_args.args[0]["phone_digits"] == "60123456789"
    assert h.sent == [(h.address, CONFIRMATIONS[0][1])]


@pytest.mark.parametrize("platform", CHANNELS)
def test_follow_up_cancellation_precedes_inbound_processing(inbound, monkeypatch, platform):
    from app.services import follow_up_service

    h = inbound(platform)
    observed = []
    def cancel(chat, company_id):
        assert chat["id"] == 8 and company_id == 11
        observed.append((len(h.messages), len(h.sent)))
    monkeypatch.setattr(follow_up_service, "stop_for_customer_reply", cancel)
    h.run("Please send more information")
    assert observed == [(0, 0)]


@pytest.mark.parametrize("accepted", [True, False])
def test_follow_up_schedule_hook_only_after_telegram_delivery(inbound, monkeypatch, accepted):
    from app.services import follow_up_service

    h = inbound("telegram")
    h.bot["followups_enabled"] = True
    hook = Mock()
    monkeypatch.setattr(follow_up_service, "schedule_after_reply", hook)
    monkeypatch.setattr(tg, "maybe_ask_marketing_consent", Mock())
    monkeypatch.setattr(tg, "send_telegram_message", lambda *a, **kw: {"ok": accepted})
    h.run("Can you tell me more?")
    if accepted:
        hook.assert_called_once_with(h.chat, 11, 1)
    else:
        hook.assert_not_called()


@pytest.mark.parametrize("case", ["ai_accepted", "delivery_failed", "staff", "disabled", "invalid_time", "old_inbound"])
def test_whatsapp_follow_up_hooks_only_after_delivered_ai_reply(inbound, monkeypatch, case):
    from app.services import follow_up_service
    h = inbound("whatsapp", paused=case == "staff")
    h.bot["followups_enabled"] = case != "disabled"
    hook, ask = Mock(), Mock()
    monkeypatch.setattr(follow_up_service, "schedule_after_reply", hook)
    monkeypatch.setattr(wa, "maybe_ask_marketing_consent", ask, raising=False)
    if case == "delivery_failed":
        monkeypatch.setattr(wa, "send_message", lambda *a, **kw: SimpleNamespace(status_code=400))
    timestamp = {"invalid_time": "invalid", "old_inbound": "1609459200"}.get(case)
    h.run("Can you tell me more?", timestamp=timestamp)
    if case in ("ai_accepted", "old_inbound"):
        hook.assert_called_once_with(h.chat, 11, 1)
    else:
        hook.assert_not_called()
    if case == "ai_accepted":
        ask.assert_called_once_with(h.chat, 11, h.bot, "Can you tell me more?")
    else:
        ask.assert_not_called()
    if case == "old_inbound":
        assert h.messages[0]["created_at"] == "2021-01-01T00:00:00+00:00"
