"""Linked-device HTTP boundaries, identity, consent and duplicate deliveries."""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask, g


@pytest.fixture
def setup(monkeypatch):
    from app.routes import channel_server_routes as routes
    from app.services import channel_server_service as server

    app = Flask(__name__)
    app.register_blueprint(routes.channel_server_blueprint)
    role = ["owner"]
    @app.before_request
    def identity():
        g.role, g.company_id, g.user_id = role[0], 2, 9

    # Inject an authenticated session while keeping the real role and company guards.
    for name, view in list(app.view_functions.items()):
        if name.startswith("channel_server.") and hasattr(view, "__wrapped__"):
            app.view_functions[name] = view.__wrapped__
    row = dict(id=8, company_id=2, chatbot_id=4, session_name="omx-test",
               phone_number="60123456789", is_active=True, connection_status="connected",
               risk_consent_at="now", risk_consent_by=9, verified_at="now")
    repo = Mock()
    repo.create.side_effect = lambda values: {**row, **values}
    repo.get.return_value = repo.active_session.return_value = row
    repo.update.return_value = row
    monkeypatch.setattr(routes, "repo", repo)
    monkeypatch.setattr(routes, "verify_chatbot_access", Mock(return_value={"company_id": 2}))
    monkeypatch.setattr(routes, "publish_test_block", Mock(return_value=None))
    monkeypatch.setattr(routes, "ensure_channel_slot", Mock())
    monkeypatch.setattr(routes, "activate_channel", Mock(return_value=row))
    for name in ["CHANNEL_SERVER_URL", "PUBLIC_BASE_URL"]:
        monkeypatch.setenv(name, "https://example.invalid")
    for name in ["CHANNEL_SERVER_API_KEY", "CHANNEL_SERVER_HMAC_KEY"]:
        monkeypatch.setenv(name, "synthetic")
    http = Mock()
    http.return_value.status_code = 200
    http.return_value.json.return_value = {"code": "1234ABCD", "id": "accepted", "status": "SCAN_QR_CODE"}
    monkeypatch.setattr(server.requests, "request", http)
    monkeypatch.setattr(server.channel_server_repository, "set_reply_chat_id", Mock())
    return app.test_client(), routes, server, row, repo, role, http


BODY = {"chatbot_id": 4, "phone_number": "0123456789", "risk_consent": True}
BASE = "/api/channel-server"


@pytest.mark.parametrize("role,expected", [("owner", 200), ("admin", 200), ("member", 403)])
def test_connect(setup, role, expected):
    client, routes, _, _, repo, roles, http = setup
    roles[0] = role
    response = client.post(BASE + "/connect", json=BODY)
    assert response.status_code == expected
    if expected == 403:
        http.assert_not_called()
        return
    values = repo.create.call_args.args[0]
    assert values["phone_number"] == "60123456789"
    assert values["risk_consent_by"] == 9 and values["risk_consent_at"]
    assert response.json["pairing_code"] == "1234ABCD"
    assert response.json["channel_id"] == 8 and response.json["instructions"]
    assert http.call_args_list[0].kwargs["json"] == {
        "name": values["session_name"], "start": True, "config": {"webhooks": [{
            "url": "https://example.invalid/api/channel-server/webhook",
            "events": ["message", "session.status", "poll.vote"], "hmac": {"key": "synthetic"}}]}}
    assert http.call_args.kwargs["json"] == {"phoneNumber": "60123456789"}


def test_connect_shows_whatsapps_real_dashed_pairing_code(setup):
    # whatsmeow PairPhone (GOWS engine) returns the code as XXXX-XXXX.
    client, _, _, _, _, _, http = setup
    http.return_value.json.return_value = {"code": "ABCD-1234"}
    response = client.post(BASE + "/connect", json=BODY)
    assert response.status_code == 200
    assert response.json["pairing_code"] == "ABCD-1234"


@pytest.mark.parametrize("typed", ["+60123456789", "+60 12-345 6789", "012-345 6789"])
def test_connect_accepts_numbers_as_people_type_them(setup, typed):
    client, _, _, _, repo, _, http = setup
    assert client.post(BASE + "/connect", json={**BODY, "phone_number": typed}).status_code == 200
    assert repo.create.call_args.args[0]["phone_number"] == "60123456789"
    assert http.call_args.kwargs["json"] == {"phoneNumber": "60123456789"}


def test_connect_with_qr_starts_the_session_without_a_pairing_code(setup):
    client, _, _, _, _, _, http = setup
    response = client.post(BASE + "/connect", json={**BODY, "method": "qr"})
    assert response.status_code == 200
    assert response.json["method"] == "qr" and response.json["channel_id"] == 8
    assert "pairing_code" not in response.json
    assert [call.args for call in http.call_args_list] == [("POST", "https://example.invalid/api/sessions")]


PNG = "iVBORw0KGgo="


def test_qr_returns_whatsapps_qr_as_a_png_data_url(setup):
    client, _, _, row, repo, _, http = setup
    repo.get.return_value = {**row, "connection_status": "pending"}
    http.return_value.json.return_value = {"mimetype": "image/png", "data": PNG}
    response = client.get(BASE + "/channels/8/qr")
    assert response.status_code == 200
    assert response.json["qr"] == "data:image/png;base64," + PNG
    assert response.headers["Cache-Control"] == "no-store"
    assert http.call_args.args == ("GET", "https://example.invalid/api/omx-test/auth/qr?format=image")
    assert http.call_args.kwargs["headers"]["Accept"] == "application/json"


@pytest.mark.parametrize("status,body,expected", [
    ("connected", {"mimetype": "image/png", "data": PNG}, 409),
    ("pending", {"mimetype": "text/html", "data": PNG}, 503),
    ("pending", {"mimetype": "image/png", "data": "<svg onload=x>"}, 503),
])
def test_qr_refuses_finished_channels_and_unexpected_images(setup, status, body, expected):
    client, _, _, row, repo, _, http = setup
    repo.get.return_value = {**row, "connection_status": status}
    http.return_value.json.return_value = body
    assert client.get(BASE + "/channels/8/qr").status_code == expected


@pytest.mark.parametrize("change", [{"risk_consent": False}, {"risk_consent": "true"},
                                    {"phone_number": "12x3"}, {"phone_number": "1234567"},
                                    {"phone_number": "1"*16}])
def test_invalid_input(setup, change):
    client, _, _, _, repo, _, http = setup
    assert client.post(BASE + "/connect", json={**BODY, **change}).status_code == 400
    repo.create.assert_not_called()
    http.assert_not_called()


def test_consent_must_be_present(setup):
    client, _, _, _, repo, _, http = setup
    response = client.post(BASE + "/connect", json={k: v for k, v in BODY.items() if k != "risk_consent"})
    assert response.status_code == 400
    repo.create.assert_not_called()
    http.assert_not_called()


@pytest.mark.parametrize("action", ["connect", "reconnect"])
def test_publish_gate_and_slot_before_http(setup, action):
    from app.services.billing_guard import BillingLimitError
    client, routes, _, _, _, _, http = setup
    url = BASE + ("/connect" if action == "connect" else "/channels/8/reconnect")
    call = client.post if action == "connect" else client.put
    routes.publish_test_block.return_value = ({"code": "PUBLISH_TEST_REQUIRED"}, 409)
    assert call(url, json=BODY).status_code == 409
    routes.publish_test_block.return_value = None
    routes.ensure_channel_slot.side_effect = BillingLimitError("No slots")
    assert call(url, json=BODY).status_code == 403
    http.assert_not_called()


def test_foreign_bot_and_channel(setup):
    client, routes, _, row, _, _, http = setup
    row["company_id"] = 3
    assert client.put(BASE + "/channels/8/disconnect", json=BODY).status_code in (403, 404)
    routes.verify_chatbot_access.side_effect = PermissionError()
    assert client.post(BASE + "/connect", json=BODY).status_code in (403, 404)
    http.assert_not_called()


def test_disconnect(setup):
    client, _, _, _, _, _, http = setup
    assert client.put(BASE + "/channels/8/disconnect", json=BODY).status_code == 200
    assert [(c.args[0], c.args[1].split("/api/")[1]) for c in http.call_args_list] == [
        ("POST", "sessions/omx-test/logout"), ("DELETE", "sessions/omx-test")]


def test_reconnect_creates_fresh_session_for_original_number(setup):
    client, _, _, row, repo, _, http = setup
    row.update(connection_status="disconnected", is_active=False)
    repo.update.side_effect = lambda current, values: {**current, **values}
    result = client.put(BASE + "/channels/8/reconnect", json=BODY)
    assert result.status_code == 200 and result.json["pairing_code"] == "1234ABCD"
    config = http.call_args_list[0].kwargs["json"]
    assert config["name"].startswith("omx-") and config["name"] != row["session_name"]
    assert result.headers["Cache-Control"] == "no-store"
    row.update(connection_status="pending", is_active=True, session_name=config["name"])
    assert client.post(BASE + "/channels/8/code").status_code == 200
    assert http.call_args.args[1].endswith(f"/api/{row['session_name']}/auth/request-code")
    assert http.call_args.kwargs["json"] == {"phoneNumber": row["phone_number"]}


def hook(client, payload, event="message", signature=True, algo="sha512"):
    body = json.dumps({"session": "omx-test", "event": event, "payload": payload}).encode()
    headers = {"X-Webhook-Hmac-Algorithm": algo} if algo is not None else {}
    if signature is not None:
        headers["X-Webhook-Hmac"] = hmac.new(b"synthetic", body, hashlib.sha512).hexdigest() if signature else "0" * 128
    return client.post(BASE + "/webhook", data=body, content_type="application/json", headers=headers)


@pytest.mark.parametrize("sig,algo", [(False, "sha512"), (None, "sha512"), (True, "sha256"), (True, None)])
def test_signature(setup, sig, algo):
    client, _, _, _, repo, _, _ = setup
    assert hook(client, {}, signature=sig, algo=algo).status_code == 401
    repo.active_session.assert_not_called()


@pytest.mark.parametrize("raw,status", [("WORKING","connected"), ("FAILED","failed"), ("STOPPED","disconnected"),
                                        ("SCAN_QR_CODE","pending"), ("STARTING","pending")])
def test_status(setup, raw, status):
    client, routes, _, row, repo, _, _ = setup
    row["connection_status"] = "pending"
    assert hook(client, {"status": raw}, "session.status").status_code == 200
    if status == "connected":
        routes.activate_channel.assert_called_once()
    else:
        assert repo.update.call_args.args[1]["connection_status"] == status


MESSAGE = {"id": "synthetic-id", "from": "60123456789@c.us", "body": "hello", "fromMe": False}
LID = "987654321@lid"
CHOICE_REPLY = "How can I help?\n[BUTTONS: Sales | Help | SALES]"


@pytest.fixture
def choice_chat(setup, monkeypatch):
    _, _, server, row, _, _, _ = setup
    chat = dict(id=11, chatbot_id=4, source_channel="whatsapp_link", source_channel_id=8,
                source_provider_id=row["phone_number"], customer_phone="+60123456789", platform_user_id=LID)
    monkeypatch.setattr("app.services.channel_delivery_service.get_linked_channel", Mock(return_value=row))
    monkeypatch.setattr(server, "get_or_create_conversation", Mock(return_value=chat))
    monkeypatch.setattr(server, "save_message", Mock(return_value={"id": 17}))
    monkeypatch.setattr(server, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(server, "generate_response", Mock(return_value=CHOICE_REPLY))
    return chat


def test_linked_choice_reply_sends_body_and_poll_to_stored_lid(setup, choice_chat):
    from app.services.channel_delivery_service import send_linked_reply

    http = setup[-1]
    assert send_linked_reply(choice_chat, CHOICE_REPLY) is True
    assert [(c.args, c.kwargs["json"]) for c in http.call_args_list] == [
        (("POST", "https://example.invalid/api/sendText"),
         {"session": "omx-test", "chatId": LID, "text": "How can I help?"}),
        (("POST", "https://example.invalid/api/sendPoll"),
         {"session": "omx-test", "chatId": LID,
          "poll": {"name": "Choose an option", "options": ["Sales", "Help"], "multipleAnswers": False}}),
    ]


@pytest.mark.parametrize("reply,expected", [
    ("Plain text", "Plain text"), ("Hi [BUTTONS: Sales]", "Hi\nSales"),
    ("Hi [BUTTONS: Sales | sales]", "Hi\nSales"), ("[BUTTONS: A | B]", "A\nB"),
])
def test_linked_choice_reply_single_text(setup, choice_chat, reply, expected):
    from app.services.channel_delivery_service import send_linked_reply

    http = setup[-1]
    assert send_linked_reply(choice_chat, reply) is True
    http.assert_called_once()
    assert http.call_args.args[1].endswith("/api/sendText")
    assert http.call_args.kwargs["json"]["text"] == expected


@pytest.mark.parametrize("poll_result,fallback_result", [
    ({}, {"id": "fallback"}), (ValueError("provider data"), {}),
])
def test_linked_choice_reply_fallback_preserves_sent_tag(setup, choice_chat, poll_result, fallback_result, caplog):
    _, _, server, row, repo, _, http = setup
    http.return_value.json.side_effect = [{"id": "body"}, poll_result, fallback_result]
    server.process_message(row, MESSAGE, repo.claim)
    assert [c.args[1].split("/")[-1] for c in http.call_args_list] == ["sendText", "sendPoll", "sendText"]
    assert http.call_args.kwargs["json"]["text"] == "Sales\nHelp"
    assert server.save_message.call_args.kwargs["message_text"] == CHOICE_REPLY
    assert server.save_message.call_args.kwargs["delivery_status"] == "sent"
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= 30]
    assert len(warnings) == (1 if fallback_result else 2)
    assert all(all(s not in w for s in ("Sales", "Help", "provider data", MESSAGE["from"])) for w in warnings)


def test_linked_choice_reply_body_refused_fails_without_poll(setup, choice_chat):
    from app.services.channel_delivery_service import ChannelDeliveryError

    _, _, server, row, repo, _, http = setup
    http.return_value.json.return_value = {}
    with pytest.raises(ChannelDeliveryError) as error:
        server.process_message(row, MESSAGE, repo.claim)
    assert error.value.code == "DELIVERY_FAILED"
    http.assert_called_once()
    assert http.call_args.kwargs["json"]["text"] == "How can I help?"
    assert server.save_message.call_args.kwargs["delivery_status"] == "failed"
    assert server.save_message.call_args.kwargs["message_text"] == CHOICE_REPLY


def test_ensure_session_webhooks_uses_poll_vote_config(setup):
    _, _, server, _, _, _, http = setup
    server.ensure_session_webhooks("omx-test")
    http.assert_called_once()
    assert http.call_args.args == ("PUT", "https://example.invalid/api/sessions/omx-test")
    assert http.call_args.kwargs["json"] == {"config": {"webhooks": [{
        "url": "https://example.invalid/api/channel-server/webhook",
        "events": ["message", "session.status", "poll.vote"], "hmac": {"key": "synthetic"},
    }]}}


VOTE = {"from": MESSAGE["from"], "fromMe": False, "id": "tap-1", "selectedOptions": [" Sales "]}


@pytest.mark.parametrize("status", ["connected", "pending", "disconnected"])
def test_poll_vote_route_requires_connected_session(setup, monkeypatch, status):
    client, _, server, row, repo, _, _ = setup
    row["connection_status"] = status
    process = Mock()
    monkeypatch.setattr(server, "process_poll_vote", process, raising=False)
    assert hook(client, {"vote": VOTE}, "poll.vote").status_code == 200
    if status == "connected":
        process.assert_called_once_with(row, {"vote": VOTE}, repo.claim)
    else:
        process.assert_not_called()


@pytest.fixture
def offered_chat(setup, choice_chat, monkeypatch):
    server = setup[2]
    lookup = Mock(return_value=choice_chat)
    monkeypatch.setattr(server, "find_open_conversation", lookup, raising=False)
    monkeypatch.setattr(server, "get_latest_bot_message_text", Mock(return_value=CHOICE_REPLY), raising=False)
    return lookup


@pytest.mark.parametrize("sender", [MESSAGE["from"], LID])
def test_poll_vote_runs_one_customer_turn_and_next_poll(setup, offered_chat, sender):
    client, _, server, row, repo, _, http = setup
    repo.claim.side_effect = [True, False]
    payload = {"vote": {**VOTE, "from": sender}, "_data": {"Info": {"SenderAlt": "60123456789@s.whatsapp.net"}}}
    for _ in range(2):
        assert hook(client, payload, "poll.vote").status_code == 200
    offered_chat.assert_called_with(chatbot_id=4, customer_phone="+60123456789", source_channel="whatsapp_link",
                                    source_channel_id=8, source_provider_id=row["phone_number"])
    server.get_or_create_conversation.assert_not_called()
    server.get_latest_bot_message_text.assert_called_with(11)
    repo.claim.assert_called_with("poll:tap-1")
    server.generate_response.assert_called_once_with("Sales", "+60123456789", 4, source_channel="whatsapp_link",
                                                     conversation_id=11, message_id=17)
    customer, bot = [c.kwargs for c in server.save_message.call_args_list]
    assert (customer["sender_type"], customer["message_text"], customer["platform_message_id"]) == (
        "customer", "Sales", "poll:tap-1")
    assert (bot["message_text"], bot["delivery_status"]) == (CHOICE_REPLY, "sent")
    assert [c.args for c in http.call_args_list] == [("POST", "https://example.invalid/api/sendText"),
                                                      ("POST", "https://example.invalid/api/sendPoll")]
    # A tap never moves the reply chat: replies stay in the chat the customer last wrote from.
    assert http.call_args.kwargs["json"]["chatId"] == LID
    server.channel_server_repository.set_reply_chat_id.assert_not_called()


@pytest.mark.parametrize("change", [
    {"fromMe": True}, {"fromMe": 0}, {"from": 17}, {"from": "123@g.us"}, {"id": " "}, {"id": "v" * 508},
    {"selectedOptions": []}, {"selectedOptions": ["Sales", "Help"]}, {"selectedOptions": [" "]},
    {"selectedOptions": "Sales"}, {"selectedOptions": [17]}, {"selectedOptions": ["Other"]},
])
def test_poll_vote_ignores_invalid_or_unoffered_input(setup, offered_chat, change, caplog):
    _, _, server, row, repo, _, http = setup
    with caplog.at_level("INFO", logger=server.__name__):
        server.process_poll_vote(row, {"vote": {**VOTE, **change}}, repo.claim)
    records = [r for r in caplog.records if r.name == server.__name__]
    assert len(records) == 1 and records[0].levelname == "INFO"
    assert all(s not in records[0].getMessage() for s in (VOTE["from"], "tap-1", "Sales", "Other"))
    repo.claim.assert_not_called()
    server.get_or_create_conversation.assert_not_called()
    server.generate_response.assert_not_called()
    server.save_message.assert_not_called()
    http.assert_not_called()


def test_poll_vote_never_creates_a_conversation(setup, offered_chat):
    _, _, server, row, repo, _, http = setup
    offered_chat.return_value = None
    server.process_poll_vote(row, {"vote": VOTE}, repo.claim)
    server.get_or_create_conversation.assert_not_called()
    server.get_latest_bot_message_text.assert_not_called()
    repo.claim.assert_not_called()
    server.save_message.assert_not_called()
    server.generate_response.assert_not_called()
    http.assert_not_called()


def test_poll_vote_during_handoff_only_records_customer_choice(setup, offered_chat):
    _, _, server, row, repo, _, http = setup
    server.is_conversation_escalated.return_value = True
    server.process_poll_vote(row, {"vote": VOTE}, repo.claim)
    server.save_message.assert_called_once()
    assert server.save_message.call_args.kwargs["message_text"] == "Sales"
    server.generate_response.assert_not_called()
    http.assert_not_called()


@pytest.mark.parametrize("apply,first_status", [(False, 200), (True, 200), (True, 503)])
def test_sync_poll_vote_webhooks(setup, monkeypatch, capsys, apply, first_status):
    from scripts import sync_channel_server_webhooks as sync

    http = setup[-1]
    rows = [{"id": 8, "session_name": "omx-first"}, {"id": 11, "session_name": "omx-next"}]
    monkeypatch.setattr(sync, "list_connected_sessions", lambda: rows)
    http.side_effect = [Mock(status_code=first_status, content=b""), Mock(status_code=200, content=b"")]
    result = sync.main(["--apply"] if apply else [])
    assert result == (1 if apply and first_status == 503 else 0)
    assert [c.args for c in http.call_args_list] == (
        [("PUT", "https://example.invalid/api/sessions/" + row["session_name"]) for row in rows] if apply else [])
    expected_rows = ["8 failed" if first_status == 503 else "8 ok", "11 ok"] if apply else ["8", "11"]
    assert capsys.readouterr().out.splitlines() == ["Count 2", *expected_rows]


@pytest.mark.parametrize("change", [{"fromMe": True}, {"from": "123@g.us"}, {"from": "status@broadcast"},
                                    {"fromMe": True, "from": LID}, {"from": "60123456789@s.whatsapp.net"},
                                    {"from": "wrong@lid"}])
def test_ignored(setup, change):
    client, _, _, _, repo, _, http = setup
    assert hook(client, {**MESSAGE, **change}).status_code == 200
    repo.claim.assert_not_called()
    http.assert_not_called()


@pytest.mark.parametrize("sender,lookup", [
    ({}, False),
    ({"from": LID, "_data": {"Info": {"SenderAlt": "60123456789@s.whatsapp.net"}}}, False),
    ({"from": LID, "_data": {"Info": {"SenderAlt": "60123456789:12@s.whatsapp.net"}}}, False),
    ({"from": LID}, True),
    ({"from": LID, "_data": {"Info": {"SenderAlt": "123@c.us"}}}, True),
    ({"from": LID, "_data": {"Info": []}}, True),
])
def test_message_replay_and_delivery(setup, monkeypatch, sender, lookup):
    client, _, server, row, repo, _, http = setup
    repo.claim.side_effect = [True, False]
    chat = {"id": 11, "chatbot_id": 4, "source_channel_id": 8, "source_channel": "whatsapp_link",
            "source_provider_id": row["phone_number"], "customer_phone": "+60123456789"}
    monkeypatch.setattr(server, "get_or_create_conversation", Mock(return_value=chat))
    monkeypatch.setattr(server, "save_message", Mock(return_value={"id": 17}))
    monkeypatch.setattr(server, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr("app.services.channel_delivery_service.get_linked_channel", Mock(return_value=row))
    generate = Mock(return_value="reply")
    monkeypatch.setattr(server, "generate_response", generate)
    remember = Mock()
    monkeypatch.setattr(server.channel_server_repository, "set_reply_chat_id", remember)
    if lookup:
        http.return_value.json.side_effect = [{"pn": "60123456789@c.us"}, {"id": "accepted"}]
    assert hook(client, {**MESSAGE, **sender}).status_code == 200
    server.get_or_create_conversation.assert_called_once_with(
        chatbot_id=4, customer_phone="+60123456789", source_channel="whatsapp_link",
        source_channel_id=8, source_provider_id=row["phone_number"])
    assert hook(client, MESSAGE).status_code == 200  # Replay the same ID with its phone JID.
    generate.assert_called_once()
    assert generate.call_args.kwargs["source_channel"] == "whatsapp_link"
    assert generate.call_args.kwargs["message_id"] == 17
    expected = [("GET", f"https://example.invalid/api/omx-test/lids/{LID}")] if lookup else []
    assert [call.args for call in http.call_args_list] == expected + [
        ("POST", "https://example.invalid/api/sendText")]
    # Reply in the chat WhatsApp used (an @lid chat may not show a reply sent to the phone JID),
    # and keep that chat id on the conversation for staff and held replies.
    chat_id = sender.get("from", MESSAGE["from"])
    remember.assert_called_once_with(11, chat_id)
    assert http.call_args.kwargs["json"] == {"session": "omx-test", "chatId": chat_id, "text": "reply"}


@pytest.mark.parametrize("recipient,chat_id", [("987654321@lid", "987654321@lid"),
                                               ("60123456789@c.us", "60123456789@c.us"),
                                               ("+60123456789", "60123456789@c.us")])
def test_send_text_uses_a_stored_chat_id_or_the_phone(setup, recipient, chat_id):
    _, _, server, _, _, _, http = setup
    http.return_value.json.return_value = {"id": "accepted"}
    assert server.send_text("omx-test", recipient, "hi") is True
    assert http.call_args.kwargs["json"] == {"session": "omx-test", "chatId": chat_id, "text": "hi"}


@pytest.mark.parametrize("status,pn", [(404, None), (200, None), (503, None),
                                      (200, "60123456789@g.us"), (200, 60123456789)])
def test_unresolved_lid_skips_message_before_claim(setup, monkeypatch, caplog, status, pn):
    client, _, server, _, repo, _, http = setup
    http.return_value.status_code = status
    http.return_value.json.return_value = {"pn": pn}
    for name in ("get_or_create_conversation", "save_message", "generate_response"):
        monkeypatch.setattr(server, name, Mock())

    assert hook(client, {**MESSAGE, "from": LID}).status_code == 200
    http.assert_called_once()
    assert http.call_args.args == ("GET", f"https://example.invalid/api/omx-test/lids/{LID}")
    repo.claim.assert_not_called()
    server.get_or_create_conversation.assert_not_called()
    server.save_message.assert_not_called()
    server.generate_response.assert_not_called()
    assert [(r.levelname, r.getMessage()) for r in caplog.records if r.levelno >= 30] == [
        ("WARNING", "[ChannelServer] linked-device message skipped: lid_unresolved")]


def test_retired_provider_sources_absent():
    root = Path(__file__).resolve().parents[1]
    forbidden = ("wa" + "sender", "what" + "chimp")
    paths = [p for folder in ("app", "web/src", "web/public", "frontend") for p in (root/folder).rglob("*")
             if p.suffix in {".py", ".js", ".astro", ".html", ".css", ".json"}]
    assert not [p for p in paths if any(word in p.read_text("utf-8-sig").lower() for word in forbidden)]


@pytest.mark.parametrize("method,path", [("post", "/channels/8/code"), ("get", "/channels/8/qr"), ("put", "/channels/8/reconnect"),
                                         ("put", "/channels/8/disconnect"), ("get", "/channels?chatbot_id=4")])
def test_management_is_restricted_to_owners_and_admins(setup, method, path):
    client, _, _, _, _, roles, http = setup
    roles[0] = "member"
    assert getattr(client, method)(BASE + path).status_code == 403
    http.assert_not_called()


def test_missing_config_and_inactive_webhook(setup, monkeypatch):
    client, _, _, _, repo, _, http = setup
    monkeypatch.delenv("CHANNEL_SERVER_API_KEY")
    assert client.post(BASE + "/connect", json=BODY).status_code == 503
    repo.create.assert_not_called()
    repo.active_session.return_value = None
    assert hook(client, MESSAGE).status_code == 404
    http.assert_not_called()


def test_readback_recovers_a_missed_status_webhook(setup):
    client, routes, _, row, repo, _, http = setup
    repo.list_channels.return_value = [{**row, "connection_status": "pending"}]
    http.return_value.json.return_value = {"status": "WORKING"}
    result = client.get(BASE + "/channels?chatbot_id=4")
    assert result.status_code == 200 and result.json["data"][0]["connection_status"] == "connected"
    assert http.call_args.args == ("GET", "https://example.invalid/api/sessions/omx-test")
    routes.activate_channel.assert_called_once()


def test_mocked_transport_never_retries_an_ambiguous_send(setup):
    _, _, server, _, _, _, http = setup
    http.side_effect = server.requests.Timeout()
    with pytest.raises(server.ChannelServerError):
        server.send_text("omx-test", "60123456789", "hello")
    http.assert_called_once()


@pytest.mark.parametrize("method,path", [("post", "/connect"), ("get", "/channels"),
                                         ("post", "/channels/8/code"), ("get", "/channels/8/qr"), ("put", "/channels/8/reconnect"),
                                         ("put", "/channels/8/disconnect")])
def test_only_webhook_accepts_requests_without_a_user_token(method, path):
    from app.routes.channel_server_routes import channel_server_blueprint
    app = Flask(__name__)
    app.register_blueprint(channel_server_blueprint)
    assert getattr(app.test_client(), method)(BASE + path).status_code == 401


def test_media_uses_text_only_reply_and_handoff_silences_it(setup, monkeypatch):
    client, _, server, row, _, _, http = setup
    chat = dict(id=12, chatbot_id=4, source_channel="whatsapp_link", source_provider_id=row["phone_number"],
                source_channel_id=8, customer_phone="+60123456789")
    monkeypatch.setattr(server, "get_or_create_conversation", lambda **_: chat)
    save = Mock(return_value={"id": 99})
    monkeypatch.setattr(server, "save_message", save)
    monkeypatch.setattr(server, "generate_response", Mock(side_effect=AssertionError("Media must skip AI")))
    monkeypatch.setattr(server, "is_conversation_escalated", Mock(side_effect=[False, False, True]))
    monkeypatch.setattr("app.services.channel_delivery_service.get_linked_channel", lambda _: row)
    for number in (1, 2):
        assert hook(client, {**MESSAGE, "id": str(number), "hasMedia": True}).status_code == 200
    http.assert_called_once()
    assert http.call_args.kwargs["json"]["text"] == server.TEXT_ONLY_REPLY
    assert save.call_args.kwargs["message_type"] == "unsupported"


def test_claim_uses_unique_constraint_and_propagates_storage_failure(monkeypatch):
    from app.database import channel_server_repository as db
    client = Mock()
    monkeypatch.setattr(db, "supabase", client)
    insert = client.table.return_value.insert
    duplicate = Exception({"code": "23505"})
    insert.return_value.execute.side_effect = [None, duplicate, RuntimeError("offline")]
    assert db.claim("event-1")
    assert not db.claim("event-1")
    with pytest.raises(RuntimeError):
        db.claim("event-1")
    insert.assert_called_with({"message_id": "event-1"})


def test_migration_secures_channel_data_and_keeps_activation_under_company_lock():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "data/084_channel_server.sql").read_text("utf-8").lower()
    for table in ("channel_server_channels", "processed_channel_server_messages"):
        assert f"alter table public.{table} enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "grant usage, select on sequence public.channel_server_channels_id_seq to service_role" in sql
    assert "risk_consent_at timestamptz not null" in sql and "risk_consent_by bigint not null" in sql
    assert "message_id text primary key" in sql
    assert "from public.companies where id = p_company_id for update" in sql
    assert "union all select c.chatbot_id from public.channel_server_channels" in sql
    assert "connection_slot_reserved=true" in sql
    rollback = (root / "data/084_channel_server_rollback.sql").read_text("utf-8").lower()
    assert "drop table if exists public.processed_channel_server_messages, public.channel_server_channels;" in rollback


def test_channel_modules_are_in_the_sorted_container_manifest():
    root = Path(__file__).resolve().parents[1]
    manifest = [line[1:] for line in (root / ".dockerignore").read_text("utf-8").splitlines() if line.startswith("!")]
    assert manifest == sorted(set(manifest))
    for path in ("app/routes/channel_server_routes.py", "app/database/channel_server_repository.py",
                 "app/services/channel_server_service.py"):
        assert path in manifest and (root / path).is_file()
