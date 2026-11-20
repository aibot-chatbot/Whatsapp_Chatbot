"""Web staff replies keep tenant authority, persistence and the human pause."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import create_app
from app.routes import agent_routes, widget_routes
from app.services import ai_router


COMPANY_ID = 42
CHATBOT_ID = 7
CONVERSATION_ID = 100
STAFF_ID = 11
SESSION_ID = "web_abcdefghijklmnopqrstuvwx"
PATH = f"/api/conversations/{CONVERSATION_ID}/agent-reply"
HEADERS = {"Authorization": "Bearer synthetic-staff-token"}


@pytest.fixture
def web_staff(monkeypatch, handed_over_staff_chat):
    from app.services import web_staff_reply_service

    monkeypatch.setenv("HANDOFF_CONTROL_ENABLED", "false")
    user = {"id": STAFF_ID, "company_id": COMPANY_ID, "role": "member", "status": "active"}
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode",
                        lambda *a, **k: {"user_id": STAFF_ID, "company_id": 999, "role": "owner"})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: user)
    conversation = {
        "id": CONVERSATION_ID, "chatbot_id": CHATBOT_ID, "source_channel": "web",
        "platform_user_id": SESSION_ID, "customer_phone": SESSION_ID,
        "conversation_status": "open",
    }
    widget = {"id": 9, "chatbot_id": CHATBOT_ID, "company_id": COMPANY_ID, "is_enabled": True}
    access = Mock(return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID})
    lookup = Mock(return_value=conversation)
    widget_lookup = Mock(return_value=widget)
    bot_lookup = Mock(return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID, "is_active": True})
    paused = Mock(return_value=True)
    dispatch = Mock(side_effect=AssertionError("Web replies must not use an external provider"))
    resolve = Mock(side_effect=AssertionError("A staff reply must not resume AI"))
    stored = {"id": 501, "conversation_id": CONVERSATION_ID, "sender_type": "human",
              "message_text": "A staff reply", "created_at": "2026-09-22T08:00:00Z"}
    save = Mock(return_value=stored)
    lock_state = {"held": False, "entries": 0}

    @contextmanager
    def locked(conversation_id):
        assert conversation_id == CONVERSATION_ID
        lock_state["entries"] += 1
        lock_state["held"] = True
        try:
            yield
        finally:
            lock_state["held"] = False

    for name, value in {
        "verify_chatbot_access": access,
        "get_conversation_by_id_and_chatbot": lookup,
        "_dispatch_conversation_reply": dispatch,
        "resolve_escalation": resolve,
    }.items():
        monkeypatch.setattr(agent_routes, name, value)
    for name, value in {
        "get_widget_by_chatbot_id": widget_lookup,
        "get_bot_by_id": bot_lookup,
        "is_conversation_escalated": paused,
        "save_message": save,
        "conversation_delivery_lock": locked,
    }.items():
        monkeypatch.setattr(web_staff_reply_service, name, value)
    app = create_app()
    app.config["TESTING"] = True
    return SimpleNamespace(client=app.test_client(), user=user, conversation=conversation,
                           widget=widget, access=access, lookup=lookup, widget_lookup=widget_lookup, bot_lookup=bot_lookup,
                           paused=paused, dispatch=dispatch, resolve=resolve, save=save,
                           stored=stored, lock_state=lock_state)


def reply(world, **overrides):
    return world.client.post(PATH, headers=HEADERS,
                             json={"chatbot_id": CHATBOT_ID, "text": "A staff reply", **overrides})


@pytest.mark.parametrize("role", ["member", "admin", "owner"])
def test_web_staff_reply_is_saved_as_human_without_resuming_ai(web_staff, role):
    world = web_staff
    world.user["role"] = role

    def save_while_locked(**values):
        assert world.lock_state["held"] is True
        return world.stored

    world.save.side_effect = save_while_locked
    response = reply(world)

    assert response.status_code == 200
    assert response.json["data"]["delivery_status"] == "accepted"
    assert response.json["data"]["message_id"] == 501
    assert "read" not in response.json["data"].values()
    world.access.assert_called_once_with(CHATBOT_ID)
    world.widget_lookup.assert_called_with(CHATBOT_ID, COMPANY_ID)
    assert world.lock_state["entries"] == 1
    values = world.save.call_args.kwargs
    assert values["conversation_id"] == CONVERSATION_ID
    assert values["sender_type"] == "human"
    assert values["actor_user_id"] == STAFF_ID
    assert values["ai_generated"] is False
    assert values["message_text"] == "A staff reply"
    world.dispatch.assert_not_called()
    world.resolve.assert_not_called()


def test_web_staff_reply_cannot_override_author_identity_or_tenant(web_staff):
    response = reply(web_staff, actor_user_id=99, user_id=99, company_id=999,
                     sender_type="bot", ai_generated=True)
    assert response.status_code == 200
    assert web_staff.save.call_args.kwargs["actor_user_id"] == STAFF_ID
    assert web_staff.save.call_args.kwargs["sender_type"] == "human"
    assert web_staff.save.call_args.kwargs["ai_generated"] is False
    web_staff.widget_lookup.assert_called_with(CHATBOT_ID, COMPANY_ID)


def test_web_staff_reply_requires_authentication(web_staff):
    response = web_staff.client.post(PATH, json={"chatbot_id": CHATBOT_ID, "text": "Private reply"})
    assert response.status_code == 401
    web_staff.lookup.assert_not_called()
    web_staff.save.assert_not_called()


def test_foreign_tenant_is_refused_before_conversation_lookup(web_staff):
    web_staff.access.side_effect = PermissionError("Not your chatbot")
    assert reply(web_staff).status_code == 403
    web_staff.lookup.assert_not_called()
    web_staff.save.assert_not_called()


def test_conversation_must_belong_to_the_verified_chatbot(web_staff):
    web_staff.lookup.return_value = None
    assert reply(web_staff).status_code == 404
    web_staff.lookup.assert_called_once_with(CONVERSATION_ID, CHATBOT_ID)
    web_staff.save.assert_not_called()


def test_web_staff_reply_requires_an_existing_human_pause(web_staff):
    web_staff.paused.return_value = False
    assert reply(web_staff).status_code == 409
    web_staff.save.assert_not_called()
    web_staff.dispatch.assert_not_called()


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_web_supervisor_still_needs_a_handoff(web_staff, role):
    # Website chat always required a human pause; the member rule must not loosen it for supervisors.
    web_staff.user["role"] = role
    web_staff.paused.return_value = False

    response = reply(web_staff)
    assert response.status_code == 409
    assert response.get_json()["code"] == "HUMAN_HANDOFF_REQUIRED"
    web_staff.save.assert_not_called()


@pytest.mark.parametrize("session", [None, "", "test_user", "test_user_11", "web_short", "+60123456789"])
def test_test_lab_or_invalid_web_visitors_never_receive_staff_replies(web_staff, session):
    web_staff.conversation.update(platform_user_id=session, customer_phone=session)
    assert reply(web_staff).status_code == 409
    web_staff.save.assert_not_called()
    web_staff.dispatch.assert_not_called()


@pytest.mark.parametrize("widget", [None, {"is_enabled": False}])
def test_web_staff_reply_needs_an_enabled_widget(web_staff, widget):
    web_staff.widget_lookup.return_value = widget
    assert reply(web_staff).status_code == 409
    web_staff.save.assert_not_called()


@pytest.mark.parametrize("stored", [None, {}, {"id": None}])
def test_missing_persistence_acknowledgement_never_claims_accepted(web_staff, stored):
    web_staff.save.return_value = stored
    response = reply(web_staff)
    assert response.status_code >= 500
    assert response.json["status"] == "error"
    assert response.json.get("data", {}).get("delivery_status") not in {"sent", "accepted", "read"}
    web_staff.resolve.assert_not_called()


@pytest.mark.parametrize("seam", ["access", "lookup", "paused", "widget_lookup", "save"])
def test_unreadable_state_or_storage_failure_fails_closed(web_staff, seam):
    getattr(web_staff, seam).side_effect = RuntimeError("synthetic-private-database-detail")
    response = reply(web_staff)
    assert response.status_code >= 500
    assert response.json["status"] == "error"
    assert "synthetic-private-database-detail" not in response.get_data(as_text=True)
    web_staff.resolve.assert_not_called()


@pytest.mark.parametrize("bot", [None, {"company_id": COMPANY_ID, "is_active": False},
                                 {"company_id": 999, "is_active": True}])
def test_staff_reply_requires_an_active_bot_in_the_authenticated_company(web_staff, bot):
    web_staff.bot_lookup.return_value = bot
    assert reply(web_staff).status_code in {403, 409}
    web_staff.save.assert_not_called()


@pytest.mark.parametrize("channel_id", [0, 9])
def test_web_staff_reply_refuses_a_bound_external_channel_origin(web_staff, channel_id):
    web_staff.conversation["source_channel_id"] = channel_id
    assert reply(web_staff).status_code == 409
    web_staff.save.assert_not_called()


@pytest.mark.parametrize("text", ["", "   ", 123, ["hello"], {"text": "hello"}])
def test_web_staff_reply_rejects_non_text_and_empty_messages(web_staff, text):
    response = reply(web_staff, text=text)
    assert response.status_code == 400
    web_staff.save.assert_not_called()


@pytest.mark.parametrize("length,status", [(2000, 200), (2001, 400)])
def test_web_staff_reply_enforces_the_text_length_boundary(web_staff, length, status):
    assert reply(web_staff, text="x" * length).status_code == status
    assert web_staff.save.call_count == (1 if status == 200 else 0)


@pytest.mark.parametrize("payload", [[], ["reply"], "reply"])
def test_web_staff_reply_requires_a_json_object(web_staff, payload):
    response = web_staff.client.post(PATH, headers=HEADERS, json=payload)
    assert response.status_code == 400
    web_staff.access.assert_not_called()
    web_staff.save.assert_not_called()


def test_paused_widget_followup_reaches_neither_flow_nor_model(web_staff, monkeypatch):
    monkeypatch.setattr(widget_routes, "_load_widget_or_error", lambda: (web_staff.widget, {}))
    monkeypatch.setattr(widget_routes, "open_conversation", lambda *a: web_staff.conversation)
    monkeypatch.setattr(widget_routes, "assert_session_quota", lambda *a: 10)
    customer = Mock()
    bot_message = Mock()
    monkeypatch.setattr(widget_routes, "record_customer_message", customer)
    monkeypatch.setattr(widget_routes, "record_bot_message", bot_message)
    monkeypatch.setattr(widget_routes, "generate_response", ai_router.generate_response)
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda _: {"id": CHATBOT_ID, "company_id": COMPANY_ID})
    monkeypatch.setattr("app.database.conversation_repository.get_conversation_by_id_and_chatbot",
                        lambda *a: web_staff.conversation)
    monkeypatch.setattr("app.database.agent_action_repository.is_conversation_escalated",
                        lambda *a, **k: True)
    monkeypatch.setattr(widget_routes, "is_conversation_escalated", lambda *a, **k: True,
                        raising=False)
    flow = Mock(side_effect=AssertionError("Human-paused visitor reached Flow"))
    provider = Mock(side_effect=AssertionError("Human-paused visitor reached a model"))
    monkeypatch.setattr(ai_router, "_try_process_flow_message", flow)
    monkeypatch.setattr(ai_router, "call_provider", provider)

    response = web_staff.client.post("/api/widget/synthetic/message",
                                    json={"session_id": SESSION_ID, "message": "More detail for staff"})

    assert response.status_code == 200
    assert response.json["data"]["handled_by"] == "human"
    customer.assert_called_once_with(CONVERSATION_ID, "More detail for staff")
    bot_message.assert_not_called()
    flow.assert_not_called()
    provider.assert_not_called()


def test_backend_web_handoff_roundtrip_uses_real_routes_services_and_repositories(monkeypatch):
    """Only PostgREST, authenticated identity and model output are simulated."""
    from app.database import (agent_action_repository, bot_repository, conversation_repository,
                              db, message_repository, web_widget_repository)
    from app.services.channel_delivery_service import HandoffAcknowledgement

    rows = {
        "chatbots": [{"id": CHATBOT_ID, "company_id": COMPANY_ID, "bot_name": "Support",
                      "status": "active", "is_active": True}],
        "chatbot_web_widgets": [{"id": 9, "chatbot_id": CHATBOT_ID, "company_id": COMPANY_ID,
                                 "public_key": "public-key", "is_enabled": True}],
        "conversations": [{"id": CONVERSATION_ID, "chatbot_id": CHATBOT_ID,
                           "source_channel": "web", "platform_user_id": SESSION_ID,
                           "source_channel_id": None, "conversation_status": "open"}],
        "messages": [], "agent_actions": [],
    }

    class Query:
        def __init__(self, table):
            self.table, self.filters, self.fields = table, [], "*"
            self.maximum, self.sort, self.inserted, self.updated = None, None, None, None

        def select(self, fields, **kwargs):
            self.fields = fields
            return self

        def eq(self, field, value):
            self.filters.append(lambda row: row.get(field) == value)
            return self

        def neq(self, field, value):
            self.filters.append(lambda row: row.get(field) != value)
            return self

        def is_(self, field, value):
            assert value == "null"
            return self.eq(field, None)

        def in_(self, field, values):
            self.filters.append(lambda row: row.get(field) in values)
            return self

        def gt(self, field, value):
            self.filters.append(lambda row: row[field] > value)
            return self

        def order(self, field, desc=False):
            self.sort = (field, desc)
            return self

        def limit(self, maximum):
            self.maximum = maximum
            return self

        def insert(self, value):
            self.inserted = dict(value)
            return self

        def update(self, value):
            self.updated = value
            return self

        def execute(self):
            if self.inserted is not None:
                self.inserted.setdefault("id", max([row["id"] for row in rows[self.table]], default=0) + 1)
                self.inserted.setdefault("created_at", "2026-09-22T08:00:00Z")
                rows[self.table].append(self.inserted)
                return SimpleNamespace(data=[dict(self.inserted)])
            selected = [row for row in rows[self.table] if all(check(row) for check in self.filters)]
            for row in selected:
                if self.updated is not None:
                    row.update(self.updated)
            count = len(selected)
            if self.sort:
                selected.sort(key=lambda row: row[self.sort[0]], reverse=self.sort[1])
            selected = selected[:self.maximum]
            data = [dict(row) if self.fields == "*" else
                    {key.strip(): row.get(key.strip()) for key in self.fields.split(",")} for row in selected]
            return SimpleNamespace(data=data, count=count)

    def rpc(name, params):
        assert name == "resolve_conversation_escalation"
        action = next(row for row in rows["agent_actions"]
                      if row["id"] == params["p_action_id"]
                      and row["chatbot_id"] == params["p_chatbot_id"]
                      and row["company_id"] == params["p_company_id"])
        changed = action["status"] != "resolved"
        action["status"] = "resolved"
        data = {"resolved_action": dict(action), "changed": changed, "ai_resumed": True}
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))

    storage = SimpleNamespace(table=Query, rpc=rpc)
    for module in (db, agent_action_repository, bot_repository, conversation_repository,
                   message_repository, web_widget_repository):
        monkeypatch.setattr(module, "supabase", storage)
    monkeypatch.setenv("HANDOFF_CONTROL_ENABLED", "false")
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **k: {"user_id": STAFF_ID})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: {
        "id": STAFF_ID, "company_id": COMPANY_ID, "role": "owner", "status": "active"})

    def generated_reply(message, *args, **kwargs):
        if message == "Please connect me to a person":
            action = agent_action_repository.save_agent_action(
                CHATBOT_ID, company_id=COMPANY_ID, conversation_id=CONVERSATION_ID,
                intent="handoff_request", action_type="notify_human")
            return HandoffAcknowledgement("Our team will reply here.", action_id=action["id"],
                                          conversation_id=CONVERSATION_ID, chatbot_id=CHATBOT_ID,
                                          company_id=COMPANY_ID)
        return "AI is back."

    provider = Mock(side_effect=generated_reply)
    monkeypatch.setattr(widget_routes, "generate_response", provider)
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    def send(text):
        return client.post("/api/widget/public-key/message", json={"session_id": SESSION_ID, "message": text})

    def poll(session=SESSION_ID):
        return client.post("/api/widget/public-key/messages", json={"session_id": session, "after_id": 0})

    requested = send("Please connect me to a person")
    assert requested.status_code == 200
    assert requested.json["data"]["reply"] == "Our team will reply here."
    assert poll().json["data"]["awaiting_human"] is True

    accepted = client.post(PATH, headers=HEADERS, json={"chatbot_id": CHATBOT_ID, "text": "A real staff reply"})
    assert accepted.status_code == 200
    assert accepted.json["data"]["delivery_status"] == "accepted"
    staff_row = next(row for row in rows["messages"] if row["sender_type"] == "human")
    assert staff_row["actor_user_id"] == STAFF_ID and staff_row["ai_generated"] is False
    rows["messages"].append({**staff_row, "id": 900, "sender_type": "internal_note", "message_text": "Private note"})
    visible = poll().json["data"]
    assert [message["message_text"] for message in visible["messages"]] == ["A real staff reply"]
    assert "actor_user_id" not in visible["messages"][0]
    assert poll("web_another_session_token").json["data"]["messages"] == []

    followup = send("More details for staff")
    assert followup.status_code == 200 and followup.json["data"]["handled_by"] == "human"
    assert provider.call_count == 1
    assert [row["message_text"] for row in rows["messages"] if row["sender_type"] == "customer"] == [
        "Please connect me to a person", "More details for staff"]

    resolved = client.post(f"/api/agent/escalations/{rows['agent_actions'][0]['id']}/resolve",
                           headers=HEADERS, json={"chatbot_id": CHATBOT_ID})
    assert resolved.status_code == 200 and resolved.json["data"]["ai_resumed"] is True
    assert poll().json["data"]["awaiting_human"] is False
    resumed = send("Thanks, the bot can help now")
    assert resumed.status_code == 200 and resumed.json["data"]["reply"] == "AI is back."
    assert provider.call_count == 2
    assert [message["message_text"] for message in poll().json["data"]["messages"]] == ["A real staff reply"]
