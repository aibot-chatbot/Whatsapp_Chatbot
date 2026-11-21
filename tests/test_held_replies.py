import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from postgrest import SyncPostgrestClient

from app import create_app
from app.routes import agent_routes, bot_routes


ROOT = Path(__file__).resolve().parents[1]
BASE = "/api/conversations/101/held-replies"
AUTH = {"Authorization": "Bearer test"}
DRAFT = "Private synthetic draft"


_dispatch_to_original_channel = agent_routes._dispatch_conversation_reply


@pytest.fixture
def staff(monkeypatch):
    user = {"id": 3, "role": "owner", "company_id": 42, "status": "active"}
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **kw: {"user_id": 3})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: user)
    conversation = {"id": 101, "chatbot_id": 7, "source_channel": "telegram"}
    row = {"id": 8, "draft": DRAFT, "category": "facts", "subtype": "price",
           "created_at": "2026-11-21T00:00:00Z"}
    repo = Mock()
    repo.get_conversation.side_effect = lambda cid, company: conversation if (cid, company) == (101, 42) else None
    repo.list_pending.return_value = [row]
    repo.claim.side_effect = [row, None]
    repo.discard.side_effect = [True, False]
    repo.finish.return_value = True
    monkeypatch.setattr(agent_routes, "held_replies", repo, raising=False)
    verify = Mock(return_value={"id": 7, "company_id": 42})
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", verify)
    escalated = Mock(return_value=False)
    monkeypatch.setattr(agent_routes, "is_conversation_escalated", escalated)
    monkeypatch.setattr(agent_routes.content_filter, "check_bot_text", Mock(return_value=None))
    dispatch, save, web = Mock(), Mock(), Mock(return_value={"delivery_status": "accepted"})
    monkeypatch.setattr(agent_routes, "_dispatch_conversation_reply", dispatch)
    monkeypatch.setattr(agent_routes, "save_message", save)
    monkeypatch.setattr(agent_routes, "send_web_staff_reply", web)
    edit = Mock(return_value={"id": 7})
    monkeypatch.setattr(bot_routes, "edit_bot", edit)
    return SimpleNamespace(user=user, repo=repo, row=row, conversation=conversation, verify=verify,
                           escalated=escalated, dispatch=dispatch, save=save, web=web, edit=edit,
                           client=create_app().test_client())


def resolve(staff, **body):
    return staff.client.post(BASE + "/8/resolve", json=body, headers=AUTH)


def test_held_linked_reply_delivers_once_to_original_device(staff, monkeypatch):
    staff.conversation.update(source_channel="whatsapp_link", source_channel_id=5,
                              source_provider_id="60111111111", customer_phone="60123456789")
    monkeypatch.setattr(agent_routes, "_dispatch_conversation_reply", _dispatch_to_original_channel)
    channel = {"id": 5, "chatbot_id": 7, "session_name": "omx-device", "phone_number": "60111111111", "verified_at": "now",
               "connection_status": "connected", "is_active": True}
    monkeypatch.setattr("app.services.channel_delivery_service.get_linked_channel", lambda _: channel)
    send = Mock(return_value=True)
    monkeypatch.setattr("app.services.channel_server_service.send_text", send)
    assert resolve(staff, action="send").status_code == 200
    assert resolve(staff, action="send").status_code == 409
    send.assert_called_once_with("omx-device", "60123456789", DRAFT)
    staff.repo.finish.assert_called_once_with(42, 7, 101, 8, 3, "sent")


@pytest.mark.parametrize("role,handoff,status", [
    ("owner", False, 200), ("admin", False, 200), ("member", True, 200), ("member", False, 403),
])
def test_read_and_resolve_follow_staff_reply_access(staff, role, handoff, status):
    staff.user["role"] = role
    staff.escalated.return_value = handoff
    response = staff.client.get(BASE, headers=AUTH)
    assert response.status_code == status
    assert resolve(staff, action="discard").status_code == status
    assert staff.verify.call_count == 2
    if status == 200:
        assert response.json["held_replies"] == [
            dict(staff.row, reason_label="A price that is not in your knowledge.", delivery_pending=False)]
        assert "no-store" in response.headers["Cache-Control"]
        staff.repo.list_pending.assert_called_once_with(42, 7, 101)
    else:
        assert DRAFT not in response.get_data(as_text=True)
        staff.repo.list_pending.assert_not_called()
        staff.repo.claim.assert_not_called()
        staff.repo.discard.assert_not_called()


@pytest.mark.parametrize("denial", ["foreign company", "archived chatbot"])
def test_foreign_or_inaccessible_conversation_never_reaches_draft_storage(staff, denial):
    if denial == "foreign company":
        staff.user["company_id"] = 43
    else:
        staff.verify.side_effect = PermissionError("No access")
    assert staff.client.get(BASE, headers=AUTH).status_code in (403, 404)
    assert resolve(staff, action="send").status_code in (403, 404)
    assert staff.repo.get_conversation.call_count == 2
    staff.repo.list_pending.assert_not_called()
    staff.repo.claim.assert_not_called()
    staff.dispatch.assert_not_called()


@pytest.mark.parametrize("channel", ["telegram", "web"])
@pytest.mark.parametrize("action,status", [("send", "sent"), ("edit", "edited"), ("discard", "discarded")])
def test_resolve_once_through_staff_delivery(staff, channel, action, status, caplog):
    staff.conversation["source_channel"] = channel
    response = resolve(staff, action=action, text="Staff correction")
    assert response.status_code == 200
    assert DRAFT not in response.get_data(as_text=True)
    assert resolve(staff, action=action, text="Second attempt").status_code == 409
    if action == "discard":
        staff.repo.discard.assert_called_with(42, 7, 101, 8, 3)
        staff.repo.claim.assert_not_called()
        staff.repo.finish.assert_not_called()
        staff.web.assert_not_called()
        staff.dispatch.assert_not_called()
        staff.save.assert_not_called()
    else:
        staff.repo.finish.assert_called_once_with(42, 7, 101, 8, 3, status)
        text = "Staff correction" if action == "edit" else DRAFT
        if channel == "web":
            staff.web.assert_called_once_with(staff.conversation, company_id=42, actor_user_id=3, text=text)
        else:
            staff.dispatch.assert_called_once_with(staff.conversation, text)
            assert staff.save.call_args.kwargs["message_text"] == text
    assert DRAFT not in caplog.text


@pytest.mark.parametrize("body", [{"action": "edit", "text": " "}, {"action": "edit", "text": "x" * 2001},
                                  {"action": "edit", "text": 123}, {"action": "other"}])
def test_invalid_resolution_has_no_effect(staff, body):
    assert resolve(staff, **body).status_code == 400
    staff.repo.claim.assert_not_called()
    staff.dispatch.assert_not_called()


def test_ambiguous_provider_failure_never_sends_twice(staff, caplog):
    staff.dispatch.side_effect = RuntimeError(DRAFT)
    assert resolve(staff, action="send").status_code == 502
    assert resolve(staff, action="send").status_code == 409
    staff.repo.finish.assert_not_called()
    staff.repo.release.assert_not_called()
    staff.dispatch.assert_called_once()
    assert DRAFT not in caplog.text


def test_pending_review_shows_a_send_awaiting_confirmation_without_staff_ids(staff):
    staff.repo.list_pending.return_value = [dict(staff.row, resolved_by=3)]
    response = staff.client.get(BASE, headers=AUTH)
    assert response.status_code == 200
    row, = response.json["held_replies"]
    assert row["delivery_pending"] is True
    assert "resolved_by" not in row


def test_other_conversations_draft_cannot_be_resolved(staff):
    staff.repo.claim.side_effect = [None]
    staff.repo.exists.return_value = False
    assert resolve(staff, action="send").status_code == 404
    staff.repo.exists.assert_called_once_with(42, 7, 101, 8)
    staff.dispatch.assert_not_called()


def test_content_refusal_leaves_draft_for_correction(staff, monkeypatch):
    monkeypatch.setattr(agent_routes.content_filter, "check_bot_text", Mock(side_effect=[Mock(), None]))
    monkeypatch.setattr(agent_routes, "record_content_flag", Mock())
    staff.repo.claim.side_effect = [staff.row, staff.row]
    assert resolve(staff, action="send").status_code == 422
    staff.repo.release.assert_called_once_with(42, 7, 101, 8, 3)
    staff.repo.finish.assert_not_called()
    staff.dispatch.assert_not_called()
    assert resolve(staff, action="edit", text="Staff correction").status_code == 200
    staff.dispatch.assert_called_once_with(staff.conversation, "Staff correction")


@pytest.mark.parametrize("role,status", [("owner", 200), ("admin", 200), ("member", 403)])
def test_setting_uses_existing_behaviour_save_permissions(staff, role, status):
    staff.user["role"] = role
    for value in (True, False):
        response = staff.client.put("/api/bots/7", json={"hold_risky_replies": value}, headers=AUTH)
        assert response.status_code == status
        if status == 200:
            staff.edit.assert_called_with(7, {"hold_risky_replies": value}, 42)
        else:
            staff.edit.assert_not_called()


def test_setting_rejects_string_boolean(staff):
    assert staff.client.put("/api/bots/7", json={"hold_risky_replies": "false"}, headers=AUTH).status_code == 400
    staff.edit.assert_not_called()


def test_migration_is_private_idempotent_and_reversible():
    sql = " ".join((ROOT / "data/083_held_replies.sql").read_text().lower().split())
    rollback = " ".join((ROOT / "data/083_held_replies_rollback.sql").read_text().lower().split())
    for statement in (
        "create table if not exists public.held_replies", "enable row level security",
        "revoke all on public.held_replies from public, anon, authenticated",
        "grant select, insert, update on public.held_replies to service_role",
        "grant usage, select on sequence public.held_replies_id_seq to service_role",
        "add column if not exists hold_risky_replies boolean not null default false",
        "create index if not exists", "(conversation_id, status)",
        "status in ('pending', 'sent', 'edited', 'discarded')",
    ):
        assert statement in sql
    for table in ("companies", "chatbots", "conversations"):
        assert f"references public.{table}(id) on delete cascade" in sql
    assert "create policy" not in sql
    assert "drop table if exists public.held_replies" in rollback
    assert "drop column if exists hold_risky_replies" in rollback


def test_repository_scopes_reads_and_atomically_reserves_before_delivery(monkeypatch):
    """Exercise the installed PostgREST client against an in-memory HTTP transport."""
    from app.database import held_replies

    writes = []
    current = {"id": 8, "status": "pending", "resolved_by": None, "draft": DRAFT}

    def handle(request):
        params = request.url.params
        if request.url.path == "/conversations":
            assert params["id"] == "eq.101" and params["chatbots.company_id"] == "eq.42"
            assert "chatbots!inner(company_id)" in params["select"]
            return httpx.Response(200, json=[{"id": 101, "chatbot_id": 7}])
        assert request.url.path == "/held_replies"
        if request.method == "POST":
            assert request.headers["prefer"] == "return=minimal"
            assert json.loads(request.content) == dict(company_id=42, chatbot_id=7, conversation_id=101,
                                                       draft=DRAFT, category="facts", subtype="price")
            return httpx.Response(201)
        assert (params["company_id"], params["chatbot_id"], params["conversation_id"]) == (
            "eq.42", "eq.7", "eq.101")
        assert params["status"] == "eq.pending"
        if request.method == "GET":
            assert params["order"] == "created_at.desc,id.desc"
            assert "resolved_by" in params["select"].split(",")
            return httpx.Response(200, json=[current])
        assert request.method == "PATCH"
        assert params["id"] == "eq.8"
        actor = params["resolved_by"]
        if actor == "is.null" and current["resolved_by"] is not None:
            return httpx.Response(200, json=[])
        assert actor == ("is.null" if current["resolved_by"] is None else "eq.3")
        changes = json.loads(request.content)
        current.update(changes)
        writes.append(changes)
        return httpx.Response(200, json=[current])

    url = "https://repository.test"
    with httpx.Client(base_url=url, transport=httpx.MockTransport(handle)) as http:
        api = SyncPostgrestClient(url, http_client=http)
        monkeypatch.setattr(held_replies, "supabase", SimpleNamespace(table=api.from_))
        held_replies.create_held_reply(company_id=42, chatbot_id=7, conversation_id=101,
                                      draft=DRAFT, category="facts", subtype="price")
        assert held_replies.get_conversation(101, 42)["chatbot_id"] == 7
        assert held_replies.list_pending(42, 7, 101)[0]["id"] == 8
        assert held_replies.claim(42, 7, 101, 8, 3)["draft"] == DRAFT
        assert held_replies.claim(42, 7, 101, 8, 4) is None
        assert held_replies.release(42, 7, 101, 8, 3)
        assert held_replies.claim(42, 7, 101, 8, 3)
        assert held_replies.finish(42, 7, 101, 8, 3, "edited")
        assert writes[:3] == [{"resolved_by": 3}, {"resolved_by": None}, {"resolved_by": 3}]
        assert current["status"] == "edited" and current["resolved_by"] == 3
        assert datetime.fromisoformat(current["resolved_at"]).tzinfo
        current.update(status="pending", resolved_by=None, resolved_at=None)
        assert held_replies.discard(42, 7, 101, 8, 3)
        assert writes[-1]["status"] == "discarded" and writes[-1]["resolved_by"] == 3
        assert datetime.fromisoformat(writes[-1]["resolved_at"]).tzinfo
