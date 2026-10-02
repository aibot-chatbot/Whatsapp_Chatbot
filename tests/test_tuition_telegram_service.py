"""Real webhook/adapter flow; storage, policy and Telegram transport are mocked."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.services import tuition_telegram_service as adapter
from app.utils import telegram_utils as telegram

PARTICIPANT = str(UUID(int=1))
SESSION = str(UUID(int=2))
OTHER_SESSION = str(UUID(int=3))
BOOKING = str(UUID(int=4))
TOKEN = str(UUID(int=5)) + str(UUID(int=6))
CHANNEL = {"id": 9, "company_id": 10, "chatbot_id": 7, "telegram_bot_id": "900",
    "bot_token": "dummy-token", "is_active": True, "connection_status": "connected", "verified_at": "2026-01-01"}
CONVERSATION = {"id": 11, "chatbot_id": 7, "source_channel": "telegram", "source_channel_id": 9,
    "source_provider_id": "900", "platform_user_id": "501", "conversation_status": "open", "customer_phone": None}


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setenv("TUITION_REMINDERS_ENABLED", "true")
    participants, bookings, transcript, claimed = [], [], [], set()
    session = {"id": SESSION, "class_name": "Math trial", "starts_at": "2099-01-03T00:00:00Z", "available_trial_seats": 2}
    other = {**session, "id": OTHER_SESSION, "starts_at": "2099-01-04T00:00:00Z"}
    prepared = {}
    paused = Mock(return_value=False)
    policy = Mock(return_value=True)
    context = Mock(return_value={"bot": {"company_id": 10, "id": 7}})
    send = Mock(return_value={"ok": True, "result": {"message_id": 100, "chat": {"id": 501}}})
    model = Mock(side_effect=AssertionError("Trial controls must not call AI or bill AI credit"))
    save = Mock(side_effect=lambda **kw: transcript.append(kw) or {"id": len(transcript)})

    def create(**kw):
        assert kw["company_id"] == 10 and kw["chatbot_id"] == 7 and kw["conversation_id"] == 11
        row = {"id": PARTICIPANT, "label": kw["label"], "version": 1}
        participants.append(row)
        return row

    def prepare(**kw):
        assert kw["conversation_id"] == 11 and kw["participant_id"] == PARTICIPANT
        prepared.update(kw)
        return {"confirmation_token": TOKEN, "expires_at": "2099-01-01T00:10:00Z", "participant": participants[0],
            "session": session if kw["session_id"] == SESSION else other, "reminder_supported": True,
            "reminder_consent": kw["reminder_consent"], "reserved": False}

    def confirm(**kw):
        if kw["conversation_id"] != 11 or kw["confirmation_token"] != TOKEN:
            raise adapter.trials.TuitionError("Unavailable", "tuition_scope_denied", 404)
        row = {"id": BOOKING, "participant_id": PARTICIPANT, "session_id": prepared["session_id"], "status": "confirmed",
            "version": (bookings[0]["version"] + 1 if bookings else 1), "participant_label": participants[0]["label"],
            "reminder_enabled": prepared["reminder_consent"]}
        bookings[:] = [row]
        return {"booking": row, "session": session if row["session_id"] == SESSION else other}

    def cancel(**kw):
        assert kw["booking_id"] == BOOKING and kw["conversation_id"] == 11
        assert kw["expected_version"] == bookings[0]["version"]
        bookings[0].update(status="cancelled", version=bookings[0]["version"] + 1)
        return bookings[0]

    mocks = {}
    for name, value in {"create_participant": create, "list_participants": lambda **kw: deepcopy(participants),
            "list_sessions": lambda **kw: [session, other], "list_bookings": lambda **kw: deepcopy(bookings),
            "prepare_trial": prepare, "confirm_trial": confirm, "cancel_trial": cancel}.items():
        mocks[name] = Mock(side_effect=value)
        monkeypatch.setattr(adapter.trials, name, mocks[name])
    monkeypatch.setattr(adapter.trials, "require_trial_context", context)
    monkeypatch.setattr(adapter, "get_conversation_by_id_and_chatbot", Mock(return_value=CONVERSATION))
    monkeypatch.setattr(adapter, "get_bound_channel", Mock(return_value=CHANNEL))
    monkeypatch.setattr(adapter, "ensure_company_operational", Mock())
    monkeypatch.setattr(adapter, "can_use_plan_feature", policy)
    monkeypatch.setattr(adapter, "is_conversation_escalated", paused)
    monkeypatch.setattr(adapter, "handoff_control_enabled", lambda: False)
    monkeypatch.setattr(adapter, "save_message", save)
    monkeypatch.setattr(telegram, "save_message", save)
    monkeypatch.setattr(telegram, "get_telegram_channel_by_secret", Mock(return_value=CHANNEL))
    monkeypatch.setattr(telegram, "get_or_create_platform_conversation", Mock(return_value=CONVERSATION))
    monkeypatch.setattr(telegram, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(telegram, "generate_response", model)
    monkeypatch.setattr(telegram, "send_telegram_message", send)
    contact = Mock(side_effect=AssertionError("Trial booking must bypass phone capture"))
    monkeypatch.setattr(telegram, "send_telegram_contact_request", contact)
    monkeypatch.setattr(telegram.requests, "post", Mock(return_value=Mock(json=Mock(return_value={"ok": True}))))
    release = Mock()
    monkeypatch.setattr(telegram, "release_telegram_update_claim", release)
    def claim(channel_id, update_id):
        if update_id in claimed:
            return False
        claimed.add(update_id)
        return True
    monkeypatch.setattr(telegram, "claim_telegram_update", claim)
    counter = [0]

    def update(text, callback=False, update_id=None):
        counter[0] += 1
        uid = update_id or counter[0]
        message = {"message_id": uid + 100, "chat": {"id": 501, "type": "private"},
            "from": {"id": 501}, "text": text}
        if callback:
            message["from"] = {"id": 900, "is_bot": True}
            message["reply_markup"] = {"inline_keyboard": [[{"text": "Choose", "callback_data": text}]]}
            return {"update_id": uid, "callback_query": {"id": "query-" + str(uid), "from": {"id": 501},
                "message": message, "data": text}}
        return {"update_id": uid, "message": message}

    def run(text, callback=False):
        value = update(text, callback)
        telegram.process_telegram_update(value, "dummy-secret")
        return value

    def button(label):
        return next(b["callback_data"] for row in send.call_args.kwargs["reply_markup"]["inline_keyboard"]
            for b in row if label in b["text"])
    return SimpleNamespace(run=run, update=update, button=button, send=send, model=model, contact=contact,
        policy=policy, context=context, paused=paused, mocks=mocks, transcript=transcript, bookings=bookings,
        participants=participants, release=release)


def start_review(flow, consent=True):
    flow.run("/trial Alice")
    flow.run(flow.button("Math trial"), True)
    assert not flow.bookings
    flow.run(flow.button("Yes, remind" if consent else "No reminder"), True)
    assert not flow.bookings
    return flow.button("Confirm trial")


def test_webhook_full_consent_review_confirmation_without_phone_or_model(flow):
    confirm = start_review(flow)
    assert len(confirm.encode()) <= 64
    assert "No place is reserved until confirmation" in flow.send.call_args.args[2]
    flow.run(confirm, True)
    assert flow.bookings[0]["reminder_enabled"] is True
    assert "Trial confirmed" in flow.send.call_args.args[2]
    assert flow.mocks["prepare_trial"].call_args.kwargs["reminder_consent"] is True
    assert flow.mocks["confirm_trial"].call_args.kwargs["confirmation_token"] == TOKEN
    assert all(call.kwargs["parse_mode"] is None for call in flow.send.call_args_list)
    assert all(not row["ai_generated"] for row in flow.transcript)
    assert all(row["sender_type"] == "bot" for row in flow.transcript)
    assert all(TOKEN not in row["message_text"] and confirm not in row["message_text"] for row in flow.transcript)
    flow.model.assert_not_called()
    flow.contact.assert_not_called()
    assert flow.policy.call_count >= flow.send.call_count * 2


def test_no_consent_reschedule_and_explicit_cancel(flow):
    flow.run(start_review(flow, False), True)
    assert flow.bookings[0]["reminder_enabled"] is False
    flow.run("/trial list")
    flow.run(flow.button("Alice"), True)
    flow.run(flow.button("Change session"), True)
    flow.run(flow.button("Math trial"), True)
    flow.run(flow.button("No reminder"), True)
    assert flow.mocks["prepare_trial"].call_args.kwargs["booking_id"] == BOOKING
    flow.run(flow.button("Confirm session change"), True)
    assert flow.bookings[0]["session_id"] == OTHER_SESSION
    flow.run("/trial list")
    flow.run(flow.button("Alice"), True)
    flow.run(flow.button("Cancel trial"), True)
    flow.mocks["cancel_trial"].assert_not_called()
    flow.run(flow.button("Confirm cancellation"), True)
    assert flow.bookings[0]["status"] == "cancelled"
    flow.model.assert_not_called()


def test_disabled_reminder_service_does_not_claim_active_delivery(flow, monkeypatch):
    monkeypatch.delenv("TUITION_REMINDERS_ENABLED", raising=False)
    code = start_review(flow)
    assert "automated reminders are currently unavailable" in flow.send.call_args.args[2]
    flow.run(code, True)
    assert "Trial confirmed" in flow.send.call_args.args[2]
    assert "automated reminders are currently unavailable" in flow.send.call_args.args[2]
    assert "reminder enabled" not in flow.send.call_args.args[2]


def test_typed_callback_code_never_confirms_or_enters_model(flow):
    code = start_review(flow)
    flow.run(code)
    flow.mocks["confirm_trial"].assert_not_called()
    assert "Typed button codes cannot change" in flow.send.call_args.args[2]
    assert code not in str(flow.transcript)
    flow.model.assert_not_called()


@pytest.mark.parametrize("malformed", ["wrong_bot", "not_a_button", "oversized"])
def test_callback_must_originate_from_actual_bot_button(flow, malformed):
    code = "tt:c:" + adapter._pack(TOKEN[:36], TOKEN[36:])
    update = flow.update(code, True)
    if malformed == "wrong_bot":
        update["callback_query"]["message"]["from"]["id"] = 901
    elif malformed == "not_a_button":
        update["callback_query"]["message"].pop("reply_markup")
    else:
        update["callback_query"]["data"] = "tt:c:" + "x" * 65
    telegram.process_telegram_update(update, "dummy-secret")
    flow.mocks["confirm_trial"].assert_not_called()
    flow.model.assert_not_called()


def test_other_contact_cannot_operate_conversation(flow, monkeypatch):
    monkeypatch.setattr(adapter, "get_conversation_by_id_and_chatbot", lambda *args: {**CONVERSATION, "platform_user_id": "502"})
    flow.run("/trial Alice")
    flow.mocks["create_participant"].assert_not_called()
    flow.send.assert_not_called()


def test_wrong_token_scope_denial_never_claims_confirmation(flow):
    flow.run("tt:c:" + adapter._pack(str(UUID(int=90)), str(UUID(int=91))), True)
    assert not flow.bookings
    assert "Trial confirmed" not in flow.send.call_args.args[2]
    assert flow.mocks["confirm_trial"].call_args.kwargs["conversation_id"] == 11


def test_conflict_is_truthful_and_can_be_reselected(flow):
    code = start_review(flow)
    flow.mocks["confirm_trial"].side_effect = adapter.trials.TuitionError("Full", "tuition_conflict", 409)
    flow.run(code, True)
    assert not flow.bookings
    assert "expired or changed" in flow.send.call_args.args[2]
    flow.run("/trial")
    assert "Choose a participant" in flow.send.call_args.args[2]


def test_handoff_blocks_action_and_send(flow):
    flow.paused.return_value = True
    flow.run("/trial Alice")
    flow.mocks["create_participant"].assert_not_called()
    flow.send.assert_not_called()


def test_handoff_after_confirm_blocks_late_reply(flow):
    code = start_review(flow)
    flow.send.reset_mock()
    flow.paused.side_effect = [False, True, True]
    flow.run(code, True)
    assert flow.bookings[0]["status"] == "confirmed"
    flow.send.assert_not_called()


@pytest.mark.parametrize("code,status", [("tuition_disabled", 503), ("tuition_industry_required", 403)])
def test_disabled_or_other_industry_never_creates_participant(flow, code, status):
    flow.context.side_effect = adapter.trials.TuitionError("unavailable", code, status)
    flow.run("/trial Alice")
    flow.mocks["create_participant"].assert_not_called()
    flow.model.assert_not_called()
    assert "confirmed" not in flow.send.call_args.args[2].lower()


def test_lost_confirmation_reply_is_not_retried_on_webhook_redelivery(flow):
    code = start_review(flow)
    flow.send.reset_mock()
    flow.send.side_effect = TimeoutError("provider outcome unknown")
    update = flow.run(code, True)
    telegram.process_telegram_update(update, "dummy-secret")
    assert flow.bookings[0]["status"] == "confirmed"
    assert flow.send.call_count == 1
    assert flow.mocks["confirm_trial"].call_count == 1
    flow.release.assert_not_called()


@pytest.mark.parametrize("result", [None, {"ok": True, "result": "malformed"},
    {"ok": True, "result": {"message_id": 1, "chat": {"id": 502}}}])
def test_ambiguous_provider_receipt_does_not_trigger_second_send(flow, result):
    flow.send.return_value = result
    flow.run("/trial")
    assert flow.send.call_count == 1
    assert flow.transcript[-1]["delivery_status"] == "failed"


def test_changed_cancellation_button_does_not_cancel_new_booking_version(flow):
    flow.run(start_review(flow), True)
    flow.run("/trial list")
    flow.run(flow.button("Alice"), True)
    flow.run(flow.button("Cancel trial"), True)
    stale = flow.button("Confirm cancellation")
    flow.bookings[0]["version"] += 1
    flow.run(stale, True)
    flow.mocks["cancel_trial"].assert_not_called()
    assert flow.bookings[0]["status"] == "confirmed"


def test_paused_webhook_never_records_confirmation_token(flow, monkeypatch):
    monkeypatch.setattr(telegram, "is_conversation_escalated", lambda *a, **kw: True)
    code = "tt:c:" + adapter._pack(TOKEN[:36], TOKEN[36:])
    flow.run(code, True)
    assert code not in str(flow.transcript)
    flow.mocks["confirm_trial"].assert_not_called()
    flow.send.assert_not_called()


def test_private_only_and_ordinary_text_untouched(flow):
    update = flow.update("/trial Alice")
    update["message"]["chat"] = {"id": -100, "type": "group"}
    assert adapter.handle_tuition_update(update, conversation=CONVERSATION, channel=CHANNEL)
    flow.mocks["create_participant"].assert_not_called()
    assert not adapter.handle_tuition_update(flow.update("hello"), conversation=CONVERSATION, channel=CHANNEL)


def test_ordinary_customer_text_keeps_observation_eligibility(flow, monkeypatch):
    monkeypatch.setattr(telegram, "is_conversation_escalated", lambda *a, **kw: True)
    flow.run("Please book a trial for next week")
    assert flow.transcript == [{"conversation_id": 11, "sender_type": "customer",
        "message_text": "Please book a trial for next week", "message_type": "text",
        "platform_message_id": "101", "delivery_status": "received", "ai_generated": False}]


def test_callback_encoding_is_reversible_and_noncanonical_input_rejected():
    assert adapter._unpack(adapter._pack(PARTICIPANT, SESSION), 2) == [PARTICIPANT, SESSION]
    with pytest.raises(ValueError):
        adapter._unpack("bad padding==")
