"""Stateful regression: a cleared handoff cannot pause the next Test Lab chat."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.database import agent_action_repository, conversation_repository
from app.services import chat_pipeline_service


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.payload = None
        self.creating = False

    def select(self, *_args):
        return self

    def eq(self, field, value):
        self.filters.append(lambda row: row.get(field) == value)
        return self

    def in_(self, field, values):
        self.filters.append(lambda row: row.get(field) in values)
        return self

    def is_(self, field, value):
        assert value == "null"
        self.filters.append(lambda row: row.get(field) is None)
        return self

    def limit(self, _limit):
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def insert(self, payload):
        self.payload = payload
        self.creating = True
        return self

    def execute(self):
        if self.creating:
            row = {**self.payload, "id": max(row["id"] for row in self.rows) + 1}
            self.rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        selected = [row for row in self.rows if all(f(row) for f in self.filters)]
        if self.payload is not None:
            for row in selected:
                row.update(self.payload)
        return SimpleNamespace(data=[dict(row) for row in selected])


class _Database:
    def __init__(self):
        self.conversations = [{
            "id": 10, "chatbot_id": 7, "source_channel": "web",
            "customer_phone": "web_testbot_session", "conversation_status": "open",
            "active_flow_id": 8, "current_node_id": "human",
        }]
        self.actions = [{
            "id": 100, "conversation_id": 10, "chatbot_id": 7,
            "company_id": 42, "intent": "handoff_request", "status": "detected",
        }]

    def table(self, name):
        assert name in {"conversations", "agent_actions"}
        return _Query(self.conversations if name == "conversations" else self.actions)


def test_reset_handoff_starts_new_ai_conversation_with_empty_history():
    database = _Database()
    with (
        patch.object(conversation_repository, "supabase", database),
        patch.object(agent_action_repository, "supabase", database),
        patch.object(chat_pipeline_service, "get_recent_chat_history", return_value=[]) as history,
        patch.object(chat_pipeline_service, "analyze_agent_intent", return_value={"intent": "greeting"}),
        patch.object(chat_pipeline_service, "get_bot_by_id", return_value={"id": 7, "company_id": 42}),
        patch.object(chat_pipeline_service, "save_agent_action"),
        patch.object(chat_pipeline_service, "create_crm_lead_from_agent_signal"),
        patch("app.services.conversation_memory_service.conversation_memory_denial", return_value="disabled"),
        patch.object(chat_pipeline_service, "detect_intent", return_value="greeting"),
        patch.object(chat_pipeline_service, "handle_greeting", return_value="Hello from AI"),
    ):
        before = chat_pipeline_service.prepare_chat_prompt("Hello", "web_testbot_session", 7, "web")
        assert before["direct_reply"] == "<SILENT_BOT_RESPONSE>"

        conversation_repository.reset_testbot_conversation(7, 42, "web_testbot_session")
        conversation_repository.reset_testbot_conversation(7, 42, "web_testbot_session")

        after = chat_pipeline_service.prepare_chat_prompt("Hello", "web_testbot_session", 7, "web")
        assert after["direct_reply"] == "Hello from AI"
        assert history.call_args.args[0] == 11

    assert database.actions[0]["status"] == "resolved"
    assert database.conversations[0]["conversation_status"] == "closed"
    assert database.conversations[0]["active_flow_id"] == 8  # Old history is retained.
    assert database.conversations[1]["conversation_status"] == "open"
    assert database.conversations[1].get("active_flow_id") is None


@pytest.mark.parametrize("other", [
    {"chatbot_id": 8}, {"source_channel": "telegram"},
    {"customer_phone": "real_web_customer"}, {"conversation_status": "closed"},
])
def test_reset_never_changes_other_bots_channels_or_customers(other):
    database = _Database()
    database.conversations.append({**database.conversations[0], "id": 20, **other})
    database.actions.append({**database.actions[0], "id": 200, "conversation_id": 20})
    with patch.object(conversation_repository, "supabase", database):
        conversation_repository.reset_testbot_conversation(7, 42, "web_testbot_session")
    assert database.actions[1]["status"] == "detected"
    assert database.conversations[1]["conversation_status"] == other.get("conversation_status", "open")


def test_reset_preserves_non_escalation_resolved_and_other_tenant_actions():
    database = _Database()
    for index, other in enumerate([
        {"intent": "lead_interest"}, {"status": "resolved"},
        {"company_id": 99}, {"chatbot_id": 8},
    ]):
        database.actions.append({**database.actions[0], "id": 200 + index, **other})
    original = [dict(row) for row in database.actions[1:]]
    with patch.object(conversation_repository, "supabase", database):
        conversation_repository.reset_testbot_conversation(7, 42, "web_testbot_session")
    assert database.actions[1:] == original
