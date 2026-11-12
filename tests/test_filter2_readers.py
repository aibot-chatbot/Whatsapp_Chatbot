"""Persisted Filter 2 verdicts are enforced before stored text reaches an AI."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app.database import agent_action_repository, analysis_repository, analytics_repository, chat_history_repository
from app.services import agent_decision_service, business_observation_service, content_filter, report_service

pytestmark = pytest.mark.real_blocked_content_lookup


ROWS = [
    {"id": 21, "conversation_id": 11, "sender_type": "customer", "message_type": "text",
     "message_text": "Please book a table for two", "created_at": "2026-11-12T01:00:00Z"},
    {"id": 22, "conversation_id": 11, "sender_type": "customer", "message_type": "text",
     "message_text": "What time do you open?", "created_at": "2026-11-12T01:00:01Z"},
]


def query(rows):
    fake = MagicMock()
    fake.not_ = fake
    for method in ("table", "select", "eq", "neq", "is_", "or_", "gte", "gt", "lt", "lte", "order", "limit", "range"):
        getattr(fake, method).return_value = fake
    fake.execute.return_value = SimpleNamespace(data=deepcopy(rows))
    return fake


@pytest.fixture(params=["block", "log", "lookup_error"])
def verdict(request, monkeypatch):
    flag = {"filter": 2, "mode": "block", "message_id": 21, "source": "customer",
            "category": "threat", "rule": "review.S1"}
    # A log row is excluded by the database predicate; the helper's own tests pin that predicate.
    rows = [{"message_id": 21, "payload": {"content_flag": flag}}] if request.param == "block" else []
    fake = query(rows)
    if request.param == "lookup_error":
        fake.execute.side_effect = RuntimeError("offline")
    monkeypatch.setattr(agent_action_repository, "supabase", fake)
    monkeypatch.setattr(content_filter, "industry_for_bot", lambda _: "general")
    return request.param


def test_chat_history_and_memory_input_exclude_only_blocked_messages(verdict, monkeypatch):
    fake = query(list(reversed(ROWS)))
    monkeypatch.setattr(chat_history_repository, "supabase", fake)
    history = chat_history_repository.get_recent_chat_history(11)
    expected = ROWS[1:] if verdict == "block" else ROWS
    assert [item["content"] for item in history] == [row["message_text"] for row in expected]
    assert "id" in fake.select.call_args.args[0].split(",")
    compact = Mock(wraps=agent_decision_service._compact_history)
    monkeypatch.setattr(agent_decision_service, "_compact_history", compact)
    agent_decision_service.analyze_agent_intent("What time?", conversation_history=history)
    assert compact.call_args.args[0] == history
    assert (ROWS[0]["message_text"] in repr(compact.call_args)) == (verdict != "block")


def test_weekly_report_filters_ids_before_flattening_transcripts(verdict, monkeypatch):
    fake = query([])
    fake.execute.side_effect = [SimpleNamespace(data=deepcopy(ROWS)), SimpleNamespace(data=[])]
    monkeypatch.setattr(analytics_repository, "supabase", fake)
    ai = Mock(return_value="REPORT")
    monkeypatch.setattr(report_service, "generate_system_response", ai)
    monkeypatch.setattr(report_service, "get_bot_by_id", lambda _: {"id": 7})
    report_service.generate_weekly_report(7)
    prompt = ai.call_args.kwargs["prompt"]
    assert ROWS[1]["message_text"] in prompt
    assert (ROWS[0]["message_text"] in prompt) == (verdict != "block")


def test_filtered_history_reaches_intent_analysis_and_conversation_memory(verdict, monkeypatch):
    from app.services import chat_pipeline_service as pipeline, conversation_memory_service as memory

    monkeypatch.setattr(chat_history_repository, "supabase", query(list(reversed(ROWS))))
    analyzer = Mock(wraps=agent_decision_service.analyze_agent_intent)
    remember = Mock()
    monkeypatch.setattr(pipeline, "analyze_agent_intent", analyzer)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *_, **__: False)
    monkeypatch.setattr(pipeline, "get_bot_by_id", lambda _: {"id": 7, "company_id": 10})
    monkeypatch.setattr(pipeline, "save_agent_action", Mock(return_value={"id": 1}))
    monkeypatch.setattr(pipeline, "_after_reply", lambda _label, work: work())
    monkeypatch.setattr(pipeline, "create_crm_lead_from_agent_signal", Mock())
    monkeypatch.setattr(memory, "conversation_memory_denial", lambda _: None)
    monkeypatch.setattr(memory, "remember_conversation_facts", remember)
    monkeypatch.setattr(pipeline, "detect_intent", lambda _: "question")
    monkeypatch.setattr(pipeline, "update_workflow_state", Mock())
    monkeypatch.setattr(pipeline, "retrieve_relevant_chunks", lambda *_, **__: [])
    builder = Mock(return_value="built prompt")
    monkeypatch.setattr(pipeline, "build_prompt", builder)

    pipeline.prepare_chat_prompt("my name is Alice", "customer", 7, source_channel="telegram",
                                 conversation={"id": 11, "chatbot_id": 7})

    history = analyzer.call_args.kwargs["conversation_history"]
    assert (ROWS[0]["message_text"] in repr(history)) == (verdict != "block")
    assert builder.call_args.args[0] == history
    remember.assert_called_once()
    assert remember.call_args.kwargs["extracted_fields"]["name"] == "Alice"


def test_analysis_transcripts_exclude_blocked_messages(verdict, monkeypatch):
    monkeypatch.setattr(analysis_repository, "get_report_context", lambda *_: {})
    monkeypatch.setattr(analysis_repository, "list_report_documents", lambda *_: [])
    pages = iter([[], [], deepcopy(ROWS), deepcopy(ROWS), []])
    monkeypatch.setattr(analysis_repository, "_page_source", lambda *_, **__: {
        "rows": next(pages), "available": True, "truncated": False, "error_code": None})
    sources = analysis_repository.load_report_sources(10, 7, None, None, "2026-11-12T02:00:00Z",
                                                       include_customer_questions=True)
    expected = [22] if verdict == "block" else [21, 22]
    assert [row["id"] for row in sources["messages"]["rows"]] == expected
    assert [row["id"] for row in sources["customer_questions"]["rows"]] == expected
    assert agent_action_repository.supabase.execute.call_count == 1


def test_observation_classifier_skips_only_blocked_messages(verdict, monkeypatch):
    service = business_observation_service
    monkeypatch.setattr(service, "_authorize", lambda *_: None)
    source = {"company_id": 10, "chatbot_id": 7, "message": {
        "id": 21, "conversation_id": 11, "text": ROWS[0]["message_text"]}}
    calls = []
    def apply(**kwargs):
        operation = kwargs["operation"]
        calls.append(operation)
        return deepcopy(source) if operation == "inspect" else {"started": True, "status": "completed"} if operation != "start" else {"started": True}
    monkeypatch.setattr(service.repository, "apply_observation", apply)
    monkeypatch.setattr(service.analysis_repository, "get_report_context", lambda *_: {"bot": {"id": 7, "company_id": 10}})
    monkeypatch.setattr(service, "_industry", lambda _: {"id": "restaurant"})
    monkeypatch.setattr(service, "_role", lambda _: "restaurant")
    from app.services import ai_router
    ai = Mock(return_value='{"action_type":"booking","status":"requested","evidence_quote":"book a table"}')
    monkeypatch.setattr(ai_router, "generate_system_response", ai)
    service.process_business_observation({"id": 100, "lease_token": "lease", "company_id": 10, "chatbot_id": 7,
        "event_type": "business_observation", "worker_kind": "business_observation", "payload": {"message_id": 21}})
    if verdict == "block":
        assert calls == ["inspect", "skip"]
        ai.assert_not_called()
    else:
        assert calls == ["inspect", "start", "finish"]
        ai.assert_called_once()
