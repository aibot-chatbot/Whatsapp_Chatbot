"""Focused repository tests for exact, idempotent escalation resolution."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.database.agent_action_repository import (
    get_open_conversation_escalations,
    get_pending_escalations,
    resolve_escalation,
)
from app.database.message_repository import latest_staff_reply_at


class _Query:
    def __init__(self, response_data):
        self.response_data = response_data
        self.operation = None
        self.update_payload = None
        self.filters = []

    def select(self, fields):
        self.operation = "select"
        self.fields = fields
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

    def range(self, first, last):
        self.filters.append(("range", first, last))
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


def test_idle_handoff_pages_only_this_chatbots_open_escalations():
    rows = [{"id": n} for n in range(201)]
    db = _Supabase([rows[:200], rows[200:]])
    with patch("app.database.agent_action_repository.supabase", db):
        assert get_open_conversation_escalations(101, 29) == rows
    assert [q.filters[-1] for q in db.queries] == [("range", 0, 199), ("range", 200, 399)]
    for query in db.queries:
        assert query.fields == "id,company_id,created_at"
        assert ("eq", "conversation_id", 101) in query.filters
        assert ("eq", "chatbot_id", 29) in query.filters
        assert ("eq", "status", "detected") in query.filters
        assert ("in", "intent", ("handoff_request", "complaint", "knowledge_gap")) in query.filters


@pytest.mark.parametrize("web", [False, True])
def test_idle_clock_selects_latest_staff_timestamp_for_owned_conversation(web):
    stamp = "2026-11-22T11:45:00Z"
    db = _MultiTableSupabase([("messages", [{"created_at": stamp}])])
    with patch("app.database.message_repository.supabase", db):
        assert latest_staff_reply_at(101, 29, web=web) == stamp
    query, = db.queries
    assert query.fields == "created_at,conversations!inner(chatbot_id)"
    assert ("eq", "conversation_id", 101) in query.filters
    assert ("eq", "conversations.chatbot_id", 29) in query.filters
    assert ("eq", "ai_generated", False) in query.filters
    sender = ("in", "sender_type", ("bot", "human")) if web else ("eq", "sender_type", "bot")
    assert sender in query.filters
    assert query.filters[-2:] == [("order", "created_at", True), ("limit", 1)]


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




def test_pending_lookup_filters_conversation_before_limit():
    supabase = _Supabase([[]])
    with patch("app.database.agent_action_repository.supabase", supabase):
        assert get_pending_escalations(29, 42, conversation_id=101) == []
    filters = supabase.queries[0].filters
    assert ("eq", "chatbot_id", 29) in filters
    assert ("eq", "company_id", 42) in filters
    assert filters.index(("eq", "conversation_id", 101)) < filters.index(("limit", 50))








@pytest.mark.parametrize("changed,resumed", [(True, True), (True, False), (False, True), (False, False)])
def test_resolution_reads_lock_identity_then_uses_atomic_result(changed, resumed):
    from unittest.mock import Mock
    client = Mock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data={
        "resolved_action": RESOLVED_ACTION, "changed": changed, "ai_resumed": resumed,
    })
    with patch("app.database.agent_action_repository.supabase", client), patch(
        "app.database.agent_action_repository._get_escalation_by_id", return_value=DETECTED_ACTION,
    ) as lookup:
        action, did_change = resolve_escalation(10, 29, 42)
    assert action == {**RESOLVED_ACTION, "_ai_resumed": resumed}
    assert did_change is changed
    client.rpc.assert_called_once_with("resolve_conversation_escalation", {
        "p_action_id": 10, "p_chatbot_id": 29, "p_company_id": 42,
    })
    client.table.assert_not_called()
    lookup.assert_called_once_with(10, 29, 42)


@pytest.mark.parametrize("chatbot_id,company_id", [(29, 42), (30, 42), (29, 99)])
def test_missing_and_cross_tenant_rpc_results_do_not_resolve(chatbot_id, company_id):
    from unittest.mock import Mock
    client = Mock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=None)
    with patch("app.database.agent_action_repository.supabase", client), patch(
        "app.database.agent_action_repository._get_escalation_by_id", return_value=DETECTED_ACTION,
    ):
        assert resolve_escalation(10, chatbot_id, company_id) == (None, False)
    assert client.rpc.call_args.args[1] == {"p_action_id": 10, "p_chatbot_id": chatbot_id, "p_company_id": company_id}


def test_missing_scoped_action_never_enters_resolution_rpc():
    from unittest.mock import Mock
    client = Mock()
    with patch("app.database.agent_action_repository.supabase", client), patch(
        "app.database.agent_action_repository._get_escalation_by_id", return_value=None,
    ):
        assert resolve_escalation(10, 29, 42) == (None, False)
    client.rpc.assert_not_called()
