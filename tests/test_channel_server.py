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
            "events": ["message", "session.status"], "hmac": {"key": "synthetic"}}]}}
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
    assert http.call_args.kwargs["json"] == {"session": "omx-test", "chatId": MESSAGE["from"], "text": "reply"}


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


@pytest.mark.parametrize("method,path", [("post", "/channels/8/code"), ("put", "/channels/8/reconnect"),
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
                                         ("post", "/channels/8/code"), ("put", "/channels/8/reconnect"),
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
