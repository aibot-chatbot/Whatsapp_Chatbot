"""WaSender turns the AI's [BUTTONS: ...] tag into a tappable WhatsApp poll.

WhatsApp does not deliver reply buttons to WaSender (linked-device) sessions, so
the tag used to reach customers as literal text. Seam: process_wasender_webhook
in, WaSender HTTP calls out (requests.post), with the AI and storage mocked.
"""

from unittest.mock import MagicMock

import pytest

from app.services import wasender_service as ws

CHANNEL = {"id": 7, "chatbot_id": 55, "company_id": 3, "api_key": "test-session-key"}
CUSTOMER = "+60123456789"
TAGGED_REPLY = (
    "Here is our programme overview.\n\n"
    "[BUTTONS: Programme info | Competition rules | Event schedule]"
)


def _accepted():
    response = MagicMock(status_code=200)
    response.json.return_value = {"success": True, "data": {"msgId": 1, "status": "in_progress"}}
    return response


@pytest.fixture
def wasender(monkeypatch):
    """Mock storage, channel guards and the AI; record every WaSender request."""
    sent, saved = [], []
    monkeypatch.setattr(ws, "get_wasender_channel_by_secret", lambda secret: dict(CHANNEL))
    monkeypatch.setattr("app.services.company_status_service.ensure_company_operational", lambda company_id: None)
    monkeypatch.setattr(ws, "validate_channel", lambda *a, **k: None)
    monkeypatch.setattr(ws, "claim_wasender_message", lambda channel_id, message_id: True)
    monkeypatch.setattr(ws, "channel_identity", lambda *a, **k: {})
    monkeypatch.setattr(ws, "get_or_create_conversation", lambda **k: {"id": 100, "customer_phone": CUSTOMER})
    monkeypatch.setattr(ws, "is_conversation_escalated", lambda *a, **k: False)
    monkeypatch.setattr(ws, "get_bound_channel", lambda conversation: dict(CHANNEL))
    monkeypatch.setattr(ws, "automatic_reply_allowed", lambda *a, **k: True)
    monkeypatch.setattr(ws, "dispatch_media_after_reply", lambda *a, **k: None)
    monkeypatch.setattr(ws, "save_message", lambda **row: saved.append(row))
    monkeypatch.setattr(ws, "generate_response", MagicMock(return_value=TAGGED_REPLY))
    monkeypatch.setattr(ws.requests, "post", lambda url, json, headers, timeout: sent.append(json) or _accepted())
    return {"sent": sent, "saved": saved, "ai": ws.generate_response}


def _incoming(text="Tell me about the programme", message_id="wamid-1"):
    return {
        "event": "messages.received",
        "data": {"messages": {
            "key": {"id": message_id, "fromMe": False, "cleanedSenderPn": "60123456789"},
            "messageBody": text,
        }},
    }


def _vote(option, voter="60123456789@s.whatsapp.net", poll_id="POLL1"):
    """poll.results as WaSender documents it: every option, with who voted for it."""
    labels = ["Programme info", "Competition rules", "Event schedule"]
    return {
        "event": "poll.results",
        "data": {
            "key": {"remoteJid": voter, "fromMe": True, "id": poll_id},
            "pollResult": [{"name": name, "voters": [voter] if name == option else []} for name in labels],
        },
    }


@pytest.fixture
def offered(monkeypatch, wasender):
    """The customer has an open chat whose latest bot message offered the three options."""
    monkeypatch.setattr(ws, "find_open_conversation", lambda **k: {"id": 100, "customer_phone": CUSTOMER})
    monkeypatch.setattr(ws, "get_latest_bot_message_text", lambda conversation_id: TAGGED_REPLY)
    wasender["ai"].return_value = "The competition rules are on page 2."
    return wasender


def test_tapping_a_poll_option_answers_it_like_a_typed_message(offered):
    ws.process_wasender_webhook(_vote("Competition rules"), "secret")

    assert offered["ai"].call_args.args[0] == "Competition rules"
    assert offered["sent"] == [{"to": CUSTOMER, "text": "The competition rules are on page 2."}]


@pytest.mark.parametrize("case", ["stale option", "no open chat", "hidden-number chat", "vote withdrawn"])
def test_a_vote_that_does_not_match_the_latest_offer_is_ignored(offered, monkeypatch, case):
    payload = _vote("Competition rules")
    if case == "stale option":
        monkeypatch.setattr(ws, "get_latest_bot_message_text", lambda conversation_id: "[BUTTONS: Fees | Venue]")
    elif case == "no open chat":
        monkeypatch.setattr(ws, "find_open_conversation", lambda **k: None)
    elif case == "hidden-number chat":
        payload = _vote("Competition rules", voter="208113201299457@lid")
    else:
        payload = _vote(option=None)

    ws.process_wasender_webhook(payload, "secret")

    offered["ai"].assert_not_called()
    assert offered["sent"] == []


def test_a_retried_reply_also_sends_buttons_as_a_poll_not_text(wasender, monkeypatch):
    from app.services import wasender_retry_service as retry

    failed = {"id": 9, "message_text": TAGGED_REPLY, "retry_count": 0,
              "conversation": {"id": 100, "chatbot_id": 55, "customer_phone": CUSTOMER}}
    monkeypatch.setattr(retry, "get_retryable_failed_wasender_messages", lambda **k: [failed])
    monkeypatch.setattr(retry, "mark_message_retrying", lambda message_id: True)
    monkeypatch.setattr(retry, "mark_message_sent_after_retry", lambda **k: None)
    monkeypatch.setattr(retry, "get_bound_channel", lambda conversation: dict(CHANNEL))
    monkeypatch.setattr(retry, "is_conversation_escalated", lambda *a, **k: False)

    retry.retry_failed_wasender_messages_once()

    assert [list(body)[1] for body in wasender["sent"]] == ["text", "poll"]
    assert wasender["sent"][0]["text"] == "Here is our programme overview."


@pytest.mark.parametrize("reply, expected_text", [
    ("[BUTTONS: Back]", "Back"),
    ("Want to book?\n\n[BUTTONS: Book now]", "Want to book?\n\nBook now"),
    ("[BUTTONS: Fees | Venue]", "Fees | Venue"),
])
def test_options_that_cannot_be_a_poll_stay_readable_in_the_text(wasender, reply, expected_text):
    wasender["ai"].return_value = reply

    ws.process_wasender_webhook(_incoming(), "secret")

    assert wasender["sent"] == [{"to": CUSTOMER, "text": expected_text}]


def test_no_poll_when_staff_take_over_after_the_text_was_sent(wasender, monkeypatch):
    allowed = iter([True, False])  # the text goes out, then handoff starts
    monkeypatch.setattr(ws, "automatic_reply_allowed", lambda *a, **k: next(allowed))

    ws.process_wasender_webhook(_incoming(), "secret")

    assert [list(body)[1] for body in wasender["sent"]] == ["text"]


def test_a_failing_poll_never_loses_the_saved_reply(wasender, monkeypatch):
    calls = []

    def bound(conversation):  # 1st lookup sends the text, 2nd sends the poll
        calls.append(conversation)
        if len(calls) == 2:
            raise RuntimeError("channel replaced")
        return dict(CHANNEL)

    monkeypatch.setattr(ws, "get_bound_channel", bound)

    ws.process_wasender_webhook(_incoming(), "secret")

    assert [row["message_text"] for row in wasender["saved"] if row["sender_type"] == "bot"] == [TAGGED_REPLY]


def test_the_same_vote_delivered_twice_is_answered_once(offered, monkeypatch):
    claimed = set()
    monkeypatch.setattr(ws, "claim_wasender_message",
                        lambda channel_id, message_id: not (message_id in claimed or claimed.add(message_id)))

    ws.process_wasender_webhook(_vote("Competition rules"), "secret")
    ws.process_wasender_webhook(_vote("Competition rules"), "secret")

    assert offered["ai"].call_count == 1


def test_the_vote_echo_as_a_text_less_message_gets_no_reply(wasender):
    payload = {"event": "messages.received", "data": {"messages": {
        "key": {"id": "wamid-vote", "fromMe": False, "cleanedSenderPn": "60123456789"},
        "message": {"pollUpdateMessage": {"pollCreationMessageKey": {"id": "POLL1"}}},
    }}}

    ws.process_wasender_webhook(payload, "secret")

    assert wasender["sent"] == []
    wasender["ai"].assert_not_called()


def test_reply_buttons_go_out_as_a_poll_after_the_text_without_the_tag(wasender):
    ws.process_wasender_webhook(_incoming(), "secret")

    assert wasender["sent"] == [
        {"to": CUSTOMER, "text": "Here is our programme overview."},
        {"to": CUSTOMER, "poll": {
            "question": "Choose an option",
            "options": ["Programme info", "Competition rules", "Event schedule"],
            "multiSelect": False,
        }},
    ]
