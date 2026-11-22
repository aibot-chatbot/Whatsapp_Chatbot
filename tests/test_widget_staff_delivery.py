"""Public share-link staff replies use only the visitor's opaque web session."""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.database import conversation_repository, message_repository
from app.routes import widget_routes as routes
from app.services import web_widget_service as service
from app.services.channel_delivery_service import HandoffAcknowledgement
from app.services.conversation_delivery_lock import conversation_delivery_lock


SESSION = "web_abcdefghijklmnopqrstuvwx"
WIDGET = {"chatbot_id": 7, "company_id": 42, "max_messages_per_session": 50}
CONVERSATION = {"id": 100, "chatbot_id": 7, "source_channel": "web",
                "platform_user_id": SESSION, "source_channel_id": None}


class Query:
    def __init__(self, database, table):
        self.database, self.table = database, table
        self.filters, self.fields, self.maximum = [], None, None
        self.sort = None

    def select(self, fields):
        self.fields = fields.split(",")
        return self

    def eq(self, field, value):
        self.filters.append(lambda row: row.get(field) == value)
        return self

    def is_(self, field, value):
        assert value == "null"
        self.filters.append(lambda row: row.get(field) is None)
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

    def execute(self):
        if self.database.error:
            raise RuntimeError("database unavailable")
        rows = [row for row in self.database.rows[self.table]
                if all(test(row) for test in self.filters)]
        if self.sort:
            rows = sorted(rows, key=lambda row: row[self.sort[0]], reverse=self.sort[1])
        rows = rows[:self.maximum]
        if self.fields and self.fields != ["*"]:
            rows = [{key: row[key] for key in self.fields} for row in rows]
        return SimpleNamespace(data=rows)


def human(message_id, **extra):
    return {"id": message_id, "conversation_id": 100, "sender_type": "human",
            "message_type": "text", "message_text": f"Staff reply {message_id}",
            "ai_generated": False, "delivery_status": "sent", "created_at": "2026-09-22T00:00:00Z",
            "actor_user_id": 12, "platform_message_id": "provider-secret", **extra}


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    app.register_blueprint(routes.widget_blueprint)
    monkeypatch.setattr(routes, "_load_widget_or_error", lambda: (WIDGET, {"company_id": 42}))
    return app.test_client()


@pytest.fixture
def database(monkeypatch):
    db = SimpleNamespace(rows={"conversations": [CONVERSATION], "messages": []}, error=False)
    db.table = lambda name: Query(db, name)
    monkeypatch.setattr(conversation_repository, "supabase", db)
    monkeypatch.setattr(message_repository, "supabase", db)
    monkeypatch.setattr(service, "is_conversation_escalated", lambda *a, **k: True, raising=False)
    return db


def poll(client, **payload):
    return client.post("/api/widget/public-key/messages", json={"session_id": SESSION, **payload})


def test_poll_exposes_only_sent_human_text_from_exact_widget_session(client, database):
    database.rows["conversations"] += [
        {**CONVERSATION, "id": 101, "chatbot_id": 8},
        {**CONVERSATION, "id": 102, "source_channel": "telegram"},
        {**CONVERSATION, "id": 103, "platform_user_id": "web_anothercustomer12"},
        {**CONVERSATION, "id": 104, "source_channel_id": 9},
    ]
    database.rows["messages"] = [human(1), human(2, sender_type="bot"),
        human(3, ai_generated=True), human(4, message_type="image"),
        human(5, delivery_status="failed"), human(6, sender_type="internal_note")]
    database.rows["messages"] += [human(i, conversation_id=i) for i in range(101, 105)]
    response = poll(client, chatbot_id=8, company_id=999, conversation_id=101)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["data"] == {
        "messages": [{"id": 1, "message_text": "Staff reply 1", "created_at": "2026-09-22T00:00:00Z", "sender_type": "human"}],
        "last_message_id": 1, "has_more": False, "awaiting_human": True}


def test_poll_pages_in_id_order_without_skipping_the_51st_reply(client, database):
    database.rows["messages"] = [human(i) for i in reversed(range(1, 52))]
    first = poll(client).json["data"]
    assert [row["id"] for row in first["messages"]] == list(range(1, 51))
    assert first["last_message_id"] == 50 and first["has_more"]
    second = poll(client, after_id=50).json["data"]
    assert [row["id"] for row in second["messages"]] == [51]
    assert not second["has_more"]


def test_unknown_session_is_empty_but_database_errors_are_503(client, database):
    database.rows["conversations"] = []
    response = poll(client, after_id=33)
    assert response.status_code == 200
    assert response.json["data"] == {"messages": [], "last_message_id": 33,
                                     "has_more": False, "awaiting_human": False}
    database.error = True
    response = poll(client)
    assert response.status_code == 503
    assert response.json["status"] == "error"


def test_pause_read_failure_is_503_without_logging_the_capability(client, database, monkeypatch, caplog):
    monkeypatch.setattr(service, "is_conversation_escalated", Mock(side_effect=RuntimeError(SESSION)))
    response = poll(client)
    assert response.status_code == 503
    assert SESSION not in response.get_data(as_text=True)
    assert SESSION not in caplog.text


def test_poll_waits_for_the_staff_writer_to_release_the_conversation_lock(monkeypatch):
    entered = Event()
    def lookup(*args):
        entered.set()
        return CONVERSATION
    monkeypatch.setattr(service, "find_widget_conversation", lookup)
    reader = Mock(return_value=[human(10)])
    monkeypatch.setattr(service, "get_widget_human_messages", reader)
    monkeypatch.setattr(service, "is_conversation_escalated", lambda *a, **k: True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with conversation_delivery_lock(100):
            pending = pool.submit(service.read_staff_messages, WIDGET, SESSION)
            assert entered.wait(timeout=2)
            reader.assert_not_called()
            assert not pending.done()
        assert pending.result(timeout=2)["last_message_id"] == 10


@pytest.mark.parametrize("payload", [{"after_id": -1}, {"after_id": True}, {"after_id": "3"},
                                     {"session_id": 12}, {"session_id": []}, {"session_id": "invalid"}])
def test_poll_rejects_invalid_capability_and_cursor(client, database, payload):
    assert poll(client, **payload).status_code == 400


def test_poll_rejects_non_object_json_and_query_only_capability(client, database):
    assert client.post("/api/widget/public-key/messages", json=["bad"]).status_code == 400
    assert client.post(f"/api/widget/public-key/messages?session_id={SESSION}", json={}).status_code == 400


@pytest.fixture
def inbound(monkeypatch):
    mocks = SimpleNamespace(paused=False, held=False)
    monkeypatch.setattr(routes, "open_conversation", lambda *a: CONVERSATION)
    monkeypatch.setattr(routes, "is_conversation_escalated", lambda *a, **k: mocks.paused, raising=False)
    @contextmanager
    def lock(conversation_id):
        assert conversation_id == 100
        mocks.held = True
        try:
            yield
        finally:
            mocks.held = False
    monkeypatch.setattr(routes, "conversation_delivery_lock", lock, raising=False)
    mocks.customer = Mock(side_effect=lambda *a: {"id": 1} if mocks.held else pytest.fail("customer write without lock"))
    mocks.bot = Mock(side_effect=lambda *a: {"id": 2} if mocks.held else pytest.fail("bot write without lock"))
    mocks.quota = Mock(return_value=10)
    mocks.generate = Mock(return_value="AI reply")
    monkeypatch.setattr(routes, "record_customer_message", mocks.customer)
    monkeypatch.setattr(routes, "record_bot_message", mocks.bot)
    monkeypatch.setattr(routes, "assert_session_quota", mocks.quota)
    monkeypatch.setattr(routes, "generate_response", mocks.generate)
    return mocks


def send(client):
    return client.post("/api/widget/public-key/message", json={"session_id": SESSION, "message": "Can you help?"})


def test_paused_customer_text_is_saved_without_quota_or_model_call(client, inbound):
    inbound.paused = True
    response = send(client)
    assert response.status_code == 200
    assert response.json["data"]["handled_by"] == "human"
    assert response.json["data"]["reply"] == ""
    inbound.customer.assert_called_once_with(100, "Can you help?")
    inbound.quota.assert_not_called()
    inbound.generate.assert_not_called()
    inbound.bot.assert_not_called()


def test_customer_message_resuming_idle_handoff_gets_widget_ai_reply(client, inbound, monkeypatch):
    inbound.paused = True
    def resume(conversation, chatbot_id):
        assert conversation == CONVERSATION and chatbot_id == 7
        inbound.paused = False
        return True
    check = Mock(side_effect=resume)
    monkeypatch.setattr(routes, "resume_ai_after_staff_idle", check, raising=False)
    response = send(client)
    assert response.json["data"]["handled_by"] == "bot"
    assert response.json["data"]["reply"] == "AI reply"
    check.assert_called_once()
    inbound.generate.assert_called_once()


def test_handoff_during_ai_generation_suppresses_final_bot_reply(client, inbound):
    def generate(*args, **kwargs):
        assert not inbound.held, "model must not hold delivery lock"
        inbound.paused = True
        return "Stale AI reply"
    inbound.generate.side_effect = generate
    response = send(client)
    assert response.status_code == 200
    assert response.json["data"]["handled_by"] == "human"
    assert response.json["data"]["reply"] == ""
    inbound.bot.assert_not_called()


def test_ai_reply_and_controlled_handoff_ack_follow_the_final_gate(client, inbound, monkeypatch):
    response = send(client)
    assert response.status_code == 200 and response.json["data"]["reply"] == "AI reply"
    inbound.bot.assert_called_once_with(100, "AI reply")
    monkeypatch.setattr("app.services.channel_delivery_service.is_pending_handoff_action", lambda *a: True)
    acknowledgement = HandoffAcknowledgement("Our team will reply here.", action_id=9,
        conversation_id=100, chatbot_id=7, company_id=42)
    def generate(*args, **kwargs):
        inbound.paused = True
        return acknowledgement
    inbound.generate.side_effect = generate
    response = send(client)
    assert response.status_code == 200 and response.json["data"]["reply"] == acknowledgement
    assert inbound.bot.call_count == 2


def test_save_message_only_adds_actor_column_for_explicit_staff_author(monkeypatch):
    query = Mock()
    query.insert.return_value.execute.return_value.data = [{"id": 1}]
    monkeypatch.setattr(message_repository, "supabase", SimpleNamespace(table=lambda _: query))
    message_repository.save_message(100, "bot", "old caller")
    assert "actor_user_id" not in query.insert.call_args.args[0]
    message_repository.save_message(100, "human", "staff reply", actor_user_id=12)
    assert query.insert.call_args.args[0]["actor_user_id"] == 12
