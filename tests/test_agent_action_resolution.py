"""Focused repository tests for exact, idempotent escalation resolution."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.database.agent_action_repository import (
    get_pending_escalations,
    resolve_escalation,
)


class _Query:
    def __init__(self, response_data):
        self.response_data = response_data
        self.operation = None
        self.update_payload = None
        self.filters = []

    def select(self, _fields):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.update_payload = payload
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, tuple(values)))
        return self

    def limit(self, value):
        self.filters.append(("limit", value))
        return self

    def order(self, field, desc=False):
        self.filters.append(("order", field, desc))
        return self

    def execute(self):
        return SimpleNamespace(data=self.response_data)


class _Supabase:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def table(self, table_name):
        assert table_name == "agent_actions"
        query = _Query(self.responses.pop(0))
        self.queries.append(query)
        return query


class _MultiTableSupabase:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def table(self, table_name):
        expected_table, response_data = self.responses.pop(0)
        assert table_name == expected_table
        query = _Query(response_data)
        query.table_name = table_name
        self.queries.append(query)
        return query


DETECTED_ACTION = {
    "id": 10,
    "company_id": 42,
    "chatbot_id": 29,
    "conversation_id": 101,
    "intent": "handoff_request",
    "status": "detected",
}
RESOLVED_ACTION = {**DETECTED_ACTION, "status": "resolved"}


def test_pending_escalation_never_attaches_cross_chatbot_conversation():
    action = {**DETECTED_ACTION}
    cross_chatbot_conversation = {
        "id": 101,
        "chatbot_id": 30,
        "customer_phone": "+60123456789",
    }
    supabase = _MultiTableSupabase([
        ("agent_actions", [action]),
        ("conversations", [cross_chatbot_conversation]),
    ])

    with patch("app.database.agent_action_repository.supabase", supabase):
        actions = get_pending_escalations(29, 42)

    assert actions[0]["conversation"] is None
    conversation_query = supabase.queries[1]
    assert ("eq", "chatbot_id", 29) in conversation_query.filters


def test_first_resolution_updates_only_the_exact_detected_action():
    supabase = _Supabase([[DETECTED_ACTION], [RESOLVED_ACTION]])

    with patch("app.database.agent_action_repository.supabase", supabase):
        action, changed = resolve_escalation(10, 29, 42)

    assert action == RESOLVED_ACTION
    assert changed is True
    assert len(supabase.queries) == 2

    update = supabase.queries[1]
    assert update.operation == "update"
    assert update.update_payload == {"status": "resolved"}
    assert ("eq", "id", 10) in update.filters
    assert ("eq", "chatbot_id", 29) in update.filters
    assert ("eq", "company_id", 42) in update.filters
    assert ("eq", "status", "detected") in update.filters
    assert not any(
        item[:2] == ("eq", "conversation_id")
        for item in update.filters
    )


def test_already_resolved_action_is_idempotent_without_an_update():
    supabase = _Supabase([[RESOLVED_ACTION]])

    with patch("app.database.agent_action_repository.supabase", supabase):
        action, changed = resolve_escalation(10, 29, 42)

    assert action == RESOLVED_ACTION
    assert changed is False
    assert [query.operation for query in supabase.queries] == ["select"]


def test_concurrent_resolution_reloads_the_winning_resolved_row():
    supabase = _Supabase([[DETECTED_ACTION], [], [RESOLVED_ACTION]])

    with patch("app.database.agent_action_repository.supabase", supabase):
        action, changed = resolve_escalation(10, 29, 42)

    assert action == RESOLVED_ACTION
    assert changed is False
    assert [query.operation for query in supabase.queries] == [
        "select",
        "update",
        "select",
    ]


@pytest.mark.parametrize(
    ("chatbot_id", "company_id"),
    [
        (29, 42),  # missing action
        (30, 42),  # wrong chatbot
        (29, 99),  # wrong tenant
    ],
)
def test_missing_wrong_chatbot_and_cross_tenant_actions_do_not_update(
    chatbot_id,
    company_id,
):
    supabase = _Supabase([[]])

    with patch("app.database.agent_action_repository.supabase", supabase):
        action, changed = resolve_escalation(10, chatbot_id, company_id)

    assert action is None
    assert changed is False
    assert [query.operation for query in supabase.queries] == ["select"]
    assert ("eq", "chatbot_id", chatbot_id) in supabase.queries[0].filters
    assert ("eq", "company_id", company_id) in supabase.queries[0].filters
