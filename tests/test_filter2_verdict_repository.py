"""One scoped metadata query finds blocking verdicts, without a recent-flag cutoff."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.database import agent_action_repository as repository


pytestmark = pytest.mark.real_blocked_content_lookup


def action_query(monkeypatch, rows):
    query = MagicMock()
    query.not_ = query
    for method in ("table", "select", "eq", "is_", "or_"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)
    monkeypatch.setattr(repository, "supabase", query)
    return query


def test_block_lookup_scopes_conversation_and_filters_in_database_without_limit(monkeypatch):
    query = action_query(monkeypatch, [{"message_id": "123"}, {"message_id": 124}, {"message_id": None}])

    assert repository.get_blocked_content_message_ids(8) == {"123", "124"}

    query.table.assert_called_once_with("agent_actions")
    query.select.assert_called_once_with("message_id:payload->content_flag->>message_id")
    assert ("conversation_id", 8) in [call.args for call in query.eq.call_args_list]
    assert ("intent", "unknown") in [call.args for call in query.eq.call_args_list]
    assert ("payload->content_flag->>filter", "2") in [call.args for call in query.eq.call_args_list]
    query.is_.assert_called_once_with("payload->content_flag", "null")
    # Existing blocking flags omit mode; both absent mode and explicit block must match.
    query.or_.assert_called_once_with(
        "payload->content_flag->>mode.is.null,payload->content_flag->>mode.neq.log")
    query.execute.assert_called_once()
    query.limit.assert_not_called()
    query.gte.assert_not_called()


def test_empty_lookup_keeps_all_messages(monkeypatch):
    action_query(monkeypatch, [])

    assert repository.get_blocked_content_message_ids(8) == set()


@pytest.mark.parametrize("rows", [None, "unreadable"])
def test_unreadable_lookup_never_breaks_reply(monkeypatch, rows):
    action_query(monkeypatch, rows)

    assert repository.get_blocked_content_message_ids(8) == set()


def test_failed_lookup_drops_nothing_and_logs_no_message_text(monkeypatch, caplog):
    query = action_query(monkeypatch, [])
    query.execute.side_effect = RuntimeError("sensitive database detail")

    assert repository.get_blocked_content_message_ids(8) == set()
    assert "blocked-message lookup failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "sensitive database detail" not in caplog.text
