from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.database import analytics_repository as repo


def test_pagination_anonymous_sessions_and_staff_labels(monkeypatch):
    query = MagicMock()
    for name in ("table", "select", "eq", "gte", "gt", "order", "limit"):
        getattr(query, name).return_value = query
    query.execute.side_effect = [SimpleNamespace(data=[
        {"id": 1, "conversation_id": 8, "sender_type": "customer", "message_text": "Hi", "conversations": {"customer_phone": None}},
        {"id": 2, "conversation_id": 8, "sender_type": "human", "message_text": "Hello", "conversations": {"customer_phone": None}},
    ]), SimpleNamespace(data=[
        {"id": 3, "conversation_id": 9, "sender_type": "bot", "ai_generated": False, "actor_user_id": 3, "message_text": "Staff reply", "conversations": {"customer_phone": None}},
    ]), SimpleNamespace(data=[])]
    monkeypatch.setattr(repo, "supabase", query)
    rows = repo.get_transcript_logs(7)
    assert len(rows) == 2
    assert "Customer: Hi" in rows[0]["chat"] and "Staff: Hello" in rows[0]["chat"]
    assert "Staff: Staff reply" in rows[1]["chat"]
    assert query.execute.call_count == 3


def test_source_error_is_not_empty_data(monkeypatch):
    query = MagicMock()
    for name in ("table", "select", "eq", "gte", "gt", "order", "limit"):
        getattr(query, name).return_value = query
    query.execute.return_value = SimpleNamespace(data=None)
    monkeypatch.setattr(repo, "supabase", query)
    with pytest.raises(RuntimeError):
        repo.get_transcript_logs(7)
