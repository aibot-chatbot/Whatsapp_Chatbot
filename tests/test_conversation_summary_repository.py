import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from postgrest import SyncPostgrestClient

from app.database import agent_action_repository, chat_history_repository, conversation_repository


DATA = Path(__file__).resolve().parents[1] / "data"


def test_summary_migration_and_rollback():
    migration = (DATA / "092_conversation_history_summary.sql").read_text(encoding="utf-8")
    rollback = (DATA / "092_conversation_history_summary_rollback.sql").read_text(encoding="utf-8")
    for sql in (migration, rollback):
        assert sql.startswith("BEGIN;\nSET LOCAL lock_timeout = '3s';\nSET LOCAL statement_timeout = '30s';")
        assert "ALTER TABLE public.conversations" in sql
        assert sql.rstrip().endswith("COMMIT;")
    for name, sql_type in (
        ("history_summary", "text"),
        ("history_summary_through_id", "bigint"),
        ("history_summary_updated_at", "timestamptz"),
    ):
        assert f"ADD COLUMN {name} {sql_type} NULL" in migration
        assert f"DROP COLUMN {name}" in rollback
    assert "CHECK (char_length(history_summary) <= 1500)" in migration


def test_summary_read_and_compare_and_set_share_tenant_and_watermark(monkeypatch):
    row = {"id": 8, "chatbot_id": 3, "history_summary": None, "history_summary_through_id": None}

    def database(request):
        assert request.url.path == "/conversations"
        params = request.url.params
        if params["id"] != "eq.8" or params["chatbot_id"] != "eq.3":
            return httpx.Response(200, json=[])
        if request.method == "PATCH":
            watermark = row["history_summary_through_id"]
            required = "is.null" if watermark is None else f"eq.{watermark}"
            if params["history_summary_through_id"] != required:
                return httpx.Response(200, json=[])
            row.update(json.loads(request.content))
        return httpx.Response(200, json=[row])

    with httpx.Client(base_url="https://fake.invalid", transport=httpx.MockTransport(database)) as client:
        fake = SyncPostgrestClient("https://fake.invalid", http_client=client)
        monkeypatch.setattr(conversation_repository, "supabase", fake)
        read = conversation_repository.get_conversation_by_id_and_chatbot
        save = conversation_repository.save_history_summary
        assert read(8, 3) == row
        assert read(8, 4) is None
        assert not save(8, 4, "foreign", 15, expected_through_id=None)
        assert save(8, 3, "winner", 15, expected_through_id=None)
        assert not save(8, 3, "loser", 18, expected_through_id=None)
        assert read(8, 3)["history_summary"] == "winner"
        assert save(8, 3, "next batch", 24, expected_through_id=15)
        assert not save(8, 3, "stale", 25, expected_through_id=15)
        assert row["history_summary"] == "next batch"
        assert row["history_summary_through_id"] == 24
        assert datetime.fromisoformat(row["history_summary_updated_at"]).utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    ("chronological", "limit", "expected"),
    [
        (list(range(11, 23)), 40, [11, 12, 13, 14, 15, 16]),
        (list(range(11, 101)), 40, list(range(11, 51))),
        # A delayed message 19 precedes 17 and 18 in conversation time.
        ([11, 12, 13, 14, 15, 16, 19, 17, 18, 20, 21, 22, 23, 24, 25], 8, list(range(11, 17))),
    ],
)
def test_summary_candidates_preserve_the_live_window_and_a_safe_watermark(
    monkeypatch, chronological, limit, expected
):
    def database(request):
        params = request.url.params
        if request.url.path == "/agent_actions":
            assert params["conversation_id"] == "eq.8" and params["chatbot_id"] == "eq.3"
            assert params["payload->content_flag->>filter"] == "eq.2"
            assert "payload->content_flag->>mode.neq.log" in params["or"]
            return httpx.Response(200, json=[{"message_id": "12"}])
        assert request.url.path == "/conversations"
        assert params["id"] == "eq.8" and params["chatbot_id"] == "eq.3"
        assert params["recent.order"] == "created_at.desc,id.desc"
        assert params["recent.limit"] == "6"
        assert params["oldest.order"] == "created_at.asc,id.asc" and params["by_id.order"] == "id.asc"
        assert params["oldest.limit"] == params["by_id.limit"] == str(limit)
        assert params["oldest.id"] == params["by_id.id"] == "gt.10"
        assert "recent.id" not in params
        page = {
            "recent": [{"id": n} for n in reversed(chronological[-6:])],
            "oldest": [{"id": n, "sender_type": "bot", "content": f"text {n}"} for n in chronological[:limit]],
            "by_id": [{"id": n} for n in sorted(chronological)[:limit]],
        }
        return httpx.Response(200, json=[page])

    with httpx.Client(base_url="https://fake.invalid", transport=httpx.MockTransport(database)) as client:
        fake = SyncPostgrestClient("https://fake.invalid", http_client=client)
        monkeypatch.setattr(chat_history_repository, "supabase", fake)
        monkeypatch.setattr(agent_action_repository, "supabase", fake)
        rows = chat_history_repository.get_summary_candidates(8, 3, 10, keep_recent=6, limit=limit)
    assert [row["id"] for row in rows] == expected
    assert rows[0]["sender_type"] == "bot" and rows[0]["content"] == "text 11"
    assert rows[1]["blocked"] is True and not rows[1].get("content")


def test_only_older_unblocked_messages_reach_the_billed_call(monkeypatch):
    from app.services import ai_router, conversation_summary_service

    rows = [{"id": n, "sender_type": "customer", "content": f"Fixture message {n:02d}."}
            for n in range(1, 13)]
    rows[0]["content"] = "My IC is 991231-14-4321."
    rows[2]["content"] = "online casino"
    page = {"recent": rows[-6:][::-1], "oldest": rows, "by_id": rows}
    state = {"history_summary": "Previously asked about delivery.", "history_summary_through_id": None}
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda *args: state)
    save = Mock()
    monkeypatch.setattr(conversation_repository, "save_history_summary", save)
    ai = Mock(return_value="Prefers delivery.")
    monkeypatch.setattr(ai_router, "generate_system_response", ai)

    def database(request):
        result = [{"message_id": "2"}] if request.url.path == "/agent_actions" else [page]
        return httpx.Response(200, json=result)

    with httpx.Client(base_url="https://fake.invalid", transport=httpx.MockTransport(database)) as client:
        fake = SyncPostgrestClient("https://fake.invalid", http_client=client)
        monkeypatch.setattr(chat_history_repository, "supabase", fake)
        monkeypatch.setattr(agent_action_repository, "supabase", fake)
        conversation_summary_service.compact_if_due(8, 3)

    ai.assert_called_once()
    request = ai.call_args.kwargs
    assert request["operation_type"] == "conversation_summary"
    prompt = request["prompt"]
    assert "Previously asked about delivery." in prompt and "[IC number hidden]" in prompt
    assert "Fixture message 04." in prompt and "Fixture message 06." in prompt
    assert all(row["content"] not in prompt for row in rows[:3] + rows[-6:])
    save.assert_called_once_with(8, 3, "Prefers delivery.", 6, expected_through_id=None)
