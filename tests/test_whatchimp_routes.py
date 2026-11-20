"""Publish page WhatChimp routes: paste a key, pick a number, connect.

Seam: the Flask test client in, the route module's collaborators (WhatChimp
client, repositories, slot/activation) mocked. Auth is the real token_required
with jwt.decode and the user/company lookups patched, as in the suspension tests.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.database.channel_lifecycle_repository import ChannelActivationError
from app.routes import whatchimp_routes as wr

AUTH_USER = {"id": 1, "company_id": 42, "email": "owner@example.test", "full_name": "Owner", "role": "owner",
             "status": "active"}
TOKEN = "whatchimp-secret-key"
NUMBER = {"phone_number_id": "1190600", "display_phone_number": "+60 12-345 6789", "business_name": "Ali Bakery"}
ROW = {"id": 5, "company_id": 42, "chatbot_id": 7, "api_token": TOKEN, "phone_number_id": "1190600",
       "display_phone_number": "+60 12-345 6789", "webhook_secret": "hook-secret",
       "webhook_url": "https://omnexa.io/whatchimp/webhook/hook-secret", "connection_status": "pending",
       "is_active": True, "connection_attempted_at": "2026-10-14T12:00:00+00:00"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://omnexa.io")
    patches = [
        patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 1, "company_id": 42, "role": "owner"}),
        patch("app.database.user_repository.get_user_by_id", return_value=AUTH_USER),
        patch("app.services.company_status_service.get_company_status_by_id", return_value={"id": 42, "status": "active"}),
    ]
    for p in patches:
        p.start()
    monkeypatch.setattr(wr, "verify_chatbot_access", lambda chatbot_id: {"company_id": 42})
    monkeypatch.setattr(wr, "get_bot_by_id", lambda chatbot_id, company_id: {"id": chatbot_id, "company_id": 42})
    monkeypatch.setattr(wr, "list_whatsapp_numbers", MagicMock(return_value={"success": True, "data": [NUMBER], "error": None}))
    monkeypatch.setattr(wr, "ensure_channel_slot", MagicMock())
    monkeypatch.setattr(wr, "create_whatchimp_channel", MagicMock(return_value=dict(ROW)))
    monkeypatch.setattr(wr, "update_whatchimp_channel", MagicMock(side_effect=lambda channel_id, changes, **k: {**ROW, **changes}))
    monkeypatch.setattr(wr, "activate_channel", MagicMock(return_value={**ROW, "connection_status": "connected",
                                                                       "verified_at": "2026-10-14T12:00:01+00:00"}))
    app = create_app()
    app.config["TESTING"] = True
    yield app.test_client()
    for p in patches:
        p.stop()


def _post(client, path, body):
    return client.post(f"{path}?chatbot_id=7", json=body, headers={"Authorization": "Bearer test"})


def test_pasted_key_lists_the_accounts_numbers(client):
    response = _post(client, "/api/whatchimp/numbers", {"api_token": f"  {TOKEN}  "})

    assert response.status_code == 200
    assert response.get_json()["data"] == [NUMBER]
    wr.list_whatsapp_numbers.assert_called_once_with(TOKEN)


@pytest.mark.parametrize("answer, status, code", [
    ({"success": False, "data": {"status": "0", "message": "No user found"}, "error": "No user found"}, 400, "whatchimp_key_rejected"),
    ({"success": False, "data": None, "error": "Could not reach WhatChimp"}, 502, "whatchimp_unreachable"),
    ({"success": True, "data": [], "error": None}, 400, "whatchimp_no_numbers"),
])
def test_lookup_failures_explain_what_to_do(client, answer, status, code):
    wr.list_whatsapp_numbers.return_value = answer

    response = _post(client, "/api/whatchimp/numbers", {"api_token": TOKEN})

    assert response.status_code == status and response.get_json()["code"] == code
    assert TOKEN not in response.get_data(as_text=True)


def test_connect_activates_the_chosen_number_without_returning_the_key(client):
    response = _post(client, "/api/whatchimp/connect", {"api_token": TOKEN, "phone_number_id": "1190600"})

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert TOKEN not in body
    data = response.get_json()["data"]
    assert data["connection_status"] == "connected" and data["display_phone_number"] == "+60 12-345 6789"
    created = wr.create_whatchimp_channel.call_args.kwargs
    assert created["phone_number_id"] == "1190600" and created["business_name"] == "Ali Bakery"
    assert created["webhook_url"] == f"https://omnexa.io/whatchimp/webhook/{created['webhook_secret']}"
    assert len(created["webhook_secret"]) >= 40
    wr.ensure_channel_slot.assert_called_once_with("whatchimp", 7, 42)
    wr.activate_channel.assert_called_once_with("whatchimp", 5, 7, 42, expected_attempt_at=ROW["connection_attempted_at"])


def test_connect_refuses_a_number_the_key_does_not_own(client):
    response = _post(client, "/api/whatchimp/connect", {"api_token": TOKEN, "phone_number_id": "someone-elses-number"})

    assert response.status_code == 400 and response.get_json()["code"] == "whatchimp_number_not_on_account"
    wr.create_whatchimp_channel.assert_not_called()


def test_full_channel_slots_retire_the_pending_row(client):
    wr.activate_channel.side_effect = ChannelActivationError("channel_limit_reached", "Your plan's channel slots are full.")

    response = _post(client, "/api/whatchimp/connect", {"api_token": TOKEN, "phone_number_id": "1190600"})

    assert response.status_code == 409 and response.get_json()["code"] == "channel_limit_reached"
    retired = wr.update_whatchimp_channel.call_args_list[-1]
    assert retired.args[1]["connection_status"] == "failed" and retired.args[1]["is_active"] is False


def test_another_companys_bot_is_refused(client, monkeypatch):
    def deny(chatbot_id):
        raise PermissionError("You do not have access to this chatbot.")
    monkeypatch.setattr(wr, "verify_chatbot_access", deny)

    response = _post(client, "/api/whatchimp/connect", {"api_token": TOKEN, "phone_number_id": "1190600"})

    assert response.status_code == 403
    wr.list_whatsapp_numbers.assert_not_called()


@pytest.mark.parametrize("last_inbound_at, status", [(None, "unknown"), ("2026-10-14T12:05:00+00:00", "ok")])
def test_delivery_tells_the_owner_whether_messages_are_arriving(client, monkeypatch, last_inbound_at, status):
    monkeypatch.setattr(wr, "get_whatchimp_channel_by_id", lambda channel_id: {
        **ROW, "connection_status": "connected", "last_inbound_at": last_inbound_at})

    response = client.get("/api/whatchimp/channels/5/delivery?chatbot_id=7", headers={"Authorization": "Bearer test"})

    assert response.status_code == 200 and TOKEN not in response.get_data(as_text=True)
    assert response.get_json()["data"]["delivery_status"] == status


def test_disconnecting_another_bots_channel_is_not_found(client, monkeypatch):
    monkeypatch.setattr(wr, "get_whatchimp_channel_by_id", lambda channel_id: {**ROW, "chatbot_id": 99})
    monkeypatch.setattr(wr, "disconnect_whatchimp_channel", MagicMock())

    response = client.put("/api/whatchimp/channels/5/disconnect?chatbot_id=7", headers={"Authorization": "Bearer test"})

    assert response.status_code == 404
    wr.disconnect_whatchimp_channel.assert_not_called()


def test_staff_reply_goes_out_through_whatchimp_not_meta(monkeypatch):
    from app.routes import agent_routes
    channel = {"api_token": TOKEN, "phone_number_id": "1190600"}
    monkeypatch.setattr(agent_routes, "get_bound_channel", lambda conversation: channel)
    sent = MagicMock(return_value={"success": True, "data": {"status": "1"}, "error": None})
    monkeypatch.setattr(agent_routes, "send_whatchimp_text", sent)
    monkeypatch.setattr(agent_routes, "send_whatsapp_message", MagicMock(side_effect=AssertionError("sent via Meta")))

    agent_routes._dispatch_conversation_reply(
        {"source_channel": "whatchimp", "customer_phone": "+60123456789"}, "A person is here to help.")

    sent.assert_called_once_with(TOKEN, "1190600", "+60123456789", "A person is here to help.")


LINK = "A" * 43  # shaped like secrets.token_urlsafe(32)


@pytest.fixture
def queued(monkeypatch):
    jobs = []
    monkeypatch.setattr(wr, "submit", lambda label, job, company_id: jobs.append(label) or True)
    monkeypatch.setattr(wr, "get_whatchimp_channel_by_secret", lambda secret: dict(ROW) if secret == LINK else None)
    return jobs


def test_webhook_answers_at_once_and_queues_the_message(client, queued):
    response = client.post(f"/whatchimp/webhook/{LINK}", json={"entry": []})

    assert response.status_code == 200 and queued == ["WhatChimp webhook"]
    assert client.get(f"/whatchimp/webhook/{LINK}").status_code == 200


@pytest.mark.parametrize("link", ["hook-secret", "B" * 43])  # malformed, and well formed but unknown
def test_junk_links_answer_ok_without_taking_a_queue_slot(client, queued, link):
    response = client.post(f"/whatchimp/webhook/{link}", json={"entry": []})

    assert response.status_code == 200 and queued == []


def test_oversized_webhook_body_is_refused_before_queueing(client, queued):
    response = client.post(f"/whatchimp/webhook/{LINK}", data=b"{" + b" " * (wr.MAX_WEBHOOK_BYTES + 1) + b"}",
                           content_type="application/json")

    assert response.status_code == 413 and queued == []


def test_failed_activation_erases_the_saved_key(client):
    wr.activate_channel.side_effect = ChannelActivationError("channel_limit_reached", "Your plan's channel slots are full.")

    _post(client, "/api/whatchimp/connect", {"api_token": TOKEN, "phone_number_id": "1190600"})

    assert wr.update_whatchimp_channel.call_args_list[-1].args[1]["api_token"] is None
