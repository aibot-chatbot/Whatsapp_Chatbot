"""WhatChimp inbound webhook: customer message in, AI reply out.

Seam: process_whatchimp_webhook in, WhatChimp client calls out, with storage,
channel guards and the AI mocked. Payloads use the WhatsApp Cloud API envelope
the parser reads (see extract_whatchimp_messages).
"""

import logging
from unittest.mock import MagicMock

import pytest

from app.services import whatchimp_service as ws

CHANNEL = {"id": 9, "chatbot_id": 55, "company_id": 3, "api_token": "test-token", "phone_number_id": "1190600"}
CUSTOMER = "+60123456789"
SECRET = "test-secret"


def _envelope(*messages, name="Ali"):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": "60123456789", "profile": {"name": name}}],
        "messages": list(messages)}}]}]}


def _text(body, message_id="wamid.T1"):
    return {"id": message_id, "from": "60123456789", "type": "text", "text": {"body": body}}


@pytest.fixture
def chimp(monkeypatch):
    """Mock storage, channel guards and the AI; record every WhatChimp send."""
    sent, saved, claims, inbound = [], [], [], []
    monkeypatch.setattr(ws, "get_whatchimp_channel_by_secret", lambda secret: dict(CHANNEL) if secret == SECRET else None)
    monkeypatch.setattr("app.services.company_status_service.ensure_company_operational", lambda company_id: None)
    monkeypatch.setattr(ws, "mark_whatchimp_inbound", lambda channel_id: inbound.append(channel_id))
    monkeypatch.setattr(ws, "validate_channel", lambda *a, **k: None)
    monkeypatch.setattr(ws, "claim_whatchimp_message", lambda channel_id, message_id: claims.append(message_id) or claims.count(message_id) == 1)
    monkeypatch.setattr(ws, "release_whatchimp_message_claim", lambda *a: None)
    monkeypatch.setattr(ws, "channel_identity", lambda *a, **k: {})
    monkeypatch.setattr(ws, "get_or_create_conversation", MagicMock(return_value={"id": 100, "customer_phone": CUSTOMER}))
    monkeypatch.setattr(ws, "is_conversation_escalated", lambda *a, **k: False)
    monkeypatch.setattr(ws, "get_bound_channel", lambda conversation: dict(CHANNEL))
    monkeypatch.setattr(ws, "automatic_reply_allowed", lambda *a, **k: True)
    monkeypatch.setattr(ws, "dispatch_media_after_reply", MagicMock())
    monkeypatch.setattr(ws, "save_message", lambda **row: saved.append(row))
    monkeypatch.setattr(ws, "generate_response", MagicMock(return_value="We open at 9am."))
    accepted = {"success": True, "data": {"status": "1"}, "error": None}
    monkeypatch.setattr(ws, "send_whatchimp_text", lambda token, number, to, text: sent.append(("text", token, number, to, text)) or accepted)
    monkeypatch.setattr(ws, "send_whatchimp_buttons",
                        lambda token, number, to, text, labels: sent.append(("buttons", token, number, to, text, labels)) or accepted)
    return {"sent": sent, "saved": saved, "inbound": inbound, "claims": claims}


def test_customer_question_gets_an_ai_reply_through_the_connected_number(chimp):
    ws.process_whatchimp_webhook(_envelope(_text("When do you open?")), SECRET)

    assert chimp["sent"] == [("text", "test-token", "1190600", CUSTOMER, "We open at 9am.")]
    assert [row["sender_type"] for row in chimp["saved"]] == ["customer", "bot"]
    assert chimp["saved"][0]["message_text"] == "When do you open?"
    assert chimp["saved"][1]["delivery_status"] == "sent"
    ws.generate_response.assert_called_once_with("When do you open?", CUSTOMER, 55, source_channel="whatchimp",
                                                 conversation_id=100)
    ws.get_or_create_conversation.assert_called_once()
    assert ws.get_or_create_conversation.call_args.kwargs["customer_name"] == "Ali"
    assert chimp["inbound"] == [9]


def test_reply_options_arrive_as_real_tappable_buttons(chimp):
    ws.generate_response.return_value = "What would you like?\n\n[BUTTONS: Menu | Opening hours | Book a table]"

    ws.process_whatchimp_webhook(_envelope(_text("hi")), SECRET)

    assert chimp["sent"] == [("buttons", "test-token", "1190600", CUSTOMER, "What would you like?",
                              ["Menu", "Opening hours", "Book a table"])]


def test_tapped_button_is_answered_like_a_typed_message(chimp):
    tap = {"id": "wamid.B1", "from": "60123456789", "type": "interactive",
           "interactive": {"type": "button_reply", "button_reply": {"id": "btn_1", "title": "Opening hours"}}}

    ws.process_whatchimp_webhook(_envelope(tap), SECRET)

    ws.generate_response.assert_called_once()
    assert ws.generate_response.call_args.args[0] == "Opening hours"


def test_buttons_follow_a_reply_too_long_to_carry_them(chimp):
    long_text = "\n\n".join(["x" * 900] * 2)  # one 1802-char part: over the button body limit
    ws.generate_response.return_value = long_text + "\n\n[BUTTONS: Yes | No]"

    ws.process_whatchimp_webhook(_envelope(_text("hi")), SECRET)

    assert [kind[0] for kind in chimp["sent"]] == ["text", "buttons"]
    assert chimp["sent"][1][4:] == (ws.BUTTON_FALLBACK_BODY, ["Yes", "No"])


def test_human_handoff_saves_the_message_without_replying(chimp, monkeypatch):
    monkeypatch.setattr(ws, "is_conversation_escalated", lambda *a, **k: True)

    ws.process_whatchimp_webhook(_envelope(_text("hello?")), SECRET)

    assert chimp["sent"] == []
    assert [row["sender_type"] for row in chimp["saved"]] == ["customer"]
    ws.generate_response.assert_not_called()


def test_redelivered_message_is_answered_once(chimp):
    ws.process_whatchimp_webhook(_envelope(_text("When do you open?")), SECRET)
    ws.process_whatchimp_webhook(_envelope(_text("When do you open?")), SECRET)

    assert len(chimp["sent"]) == 1


def test_unknown_link_is_dropped_without_logging_the_secret(chimp, caplog):
    with caplog.at_level(logging.WARNING):
        ws.process_whatchimp_webhook(_envelope(_text("hi")), "someone-elses-secret")

    assert chimp["sent"] == [] and chimp["inbound"] == []
    assert "someone-elses-secret" not in caplog.text


def test_photo_gets_the_text_only_reply(chimp):
    photo = {"id": "wamid.P1", "from": "60123456789", "type": "image", "image": {"id": "media-1"}}

    ws.process_whatchimp_webhook(_envelope(photo), SECRET)

    assert chimp["sent"] == [("text", "test-token", "1190600", CUSTOMER, ws.TEXT_ONLY_REPLY)]
    assert chimp["saved"][0]["message_type"] == "unsupported"
    ws.generate_response.assert_not_called()


def test_rejected_send_is_saved_as_failed_with_whatchimps_reason(chimp, monkeypatch):
    monkeypatch.setattr(ws, "send_whatchimp_text",
                        lambda *a: {"success": False, "data": None, "error": "Subscriber limit has been exceeded."})

    ws.process_whatchimp_webhook(_envelope(_text("hi")), SECRET)

    bot = chimp["saved"][-1]
    assert bot["delivery_status"] == "failed" and bot["last_error"] == "Subscriber limit has been exceeded."
    ws.dispatch_media_after_reply.assert_not_called()


def test_delivery_without_a_customer_message_logs_field_names_not_content(chimp, caplog):
    status_update = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.S", "recipient_id": "60123456789"}]}}]}]}

    with caplog.at_level(logging.INFO):
        ws.process_whatchimp_webhook(status_update, SECRET)

    assert chimp["inbound"] == [9]  # proves the pasted link works
    assert chimp["sent"] == []
    assert "entry[].changes[].value.statuses" in caplog.text
    assert "60123456789" not in caplog.text


def test_message_for_another_number_is_not_answered(chimp):
    envelope = _envelope(_text("hi"))
    envelope["entry"][0]["changes"][0]["value"]["metadata"] = {"phone_number_id": "9999999"}

    ws.process_whatchimp_webhook(envelope, SECRET)

    assert chimp["sent"] == [] and chimp["saved"] == []


def test_message_for_this_number_is_answered(chimp):
    envelope = _envelope(_text("hi"))
    envelope["entry"][0]["changes"][0]["value"]["metadata"] = {"phone_number_id": "1190600"}

    ws.process_whatchimp_webhook(envelope, SECRET)

    assert len(chimp["sent"]) == 1


def test_field_name_log_is_capped_and_cannot_forge_lines(chimp, caplog):
    junk = {f"k{i}\nFAKE LOG LINE": i for i in range(500)}

    with caplog.at_level(logging.INFO):
        ws.process_whatchimp_webhook(junk, SECRET)

    assert "\nFAKE" not in caplog.text
    assert caplog.text.count("?FAKE") == ws.MAX_LOGGED_FIELDS


def test_parser_skips_messages_without_an_id_or_sender():
    payload = _envelope({"from": "60123456789", "type": "text", "text": {"body": "no id"}},
                        {"id": "wamid.X", "type": "text", "text": {"body": "no sender"}},
                        {"id": "wamid.Y", "from": "60123<script>", "type": "text", "text": {"body": "bad sender"}},
                        _text("  kept  ", message_id="wamid.K"))

    assert ws.extract_whatchimp_messages(payload) == [
        {"message_id": "wamid.K", "customer_phone": CUSTOMER, "customer_name": "Ali", "message_text": "kept"}]
