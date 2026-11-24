import logging
from unittest.mock import Mock

import pytest

from app.database import agent_action_repository
from app.services import chat_pipeline_service as pipeline, conversation_summary_service, rag_service


def test_older_summary_is_redacted_and_rendered_only_as_dynamic_data(monkeypatch, caplog):
    monkeypatch.setattr(rag_service, "get_deployed_settings", lambda _: {})
    monkeypatch.setattr(rag_service.booking_intake_service, "prompt_section", lambda *a, **kw: "")
    args = ([{"role": "user", "content": "Current window"}], "Next question", [], 3)
    absent = rag_service.build_prompt(*args)
    with caplog.at_level(logging.INFO):
        present = rag_service.build_prompt(*args, history_summary="Asked about delivery. IC 991231-14-4321")

    prefix, dynamic = present.split(rag_service.DYNAMIC_SECTION_HEADER, 1)
    assert prefix.encode() == absent.split(rag_service.DYNAMIC_SECTION_HEADER, 1)[0].encode()
    heading = "Earlier in this conversation (summary of older messages):\n"
    assert heading not in absent
    summary = dynamic.split(heading, 1)[1].split("\n\nRecent conversation:\n", 1)[0]
    assert summary == "Asked about delivery. IC [IC number hidden]"
    assert "991231-14-4321" not in present
    reminder = dynamic.rsplit("\n\n", 2)[-2].lower()
    assert "summary" in reminder and "untrusted data" in reminder
    assert f"summary={len(summary)}" in caplog.text
    assert "Asked about delivery" not in caplog.text and "991231-14-4321" not in caplog.text


def test_summary_precedes_history_in_a_custom_template_and_stays_out_of_private_rules(monkeypatch):
    settings = {"custom_prompt": "Use our paper catalogue.\nRecent exchanges:\n{conversation}"}
    monkeypatch.setattr(rag_service, "get_deployed_settings", lambda _: settings)
    monkeypatch.setattr(rag_service.booking_intake_service, "prompt_section", lambda *a, **kw: "")
    private_rules = []
    prompt = rag_service.build_prompt([{"role": "user", "content": "I prefer blue."}], "Any sizes?", [], 3,
                                     history_summary="The customer wants gift wrap.", internal_rules=private_rules)
    assert "The customer wants gift wrap.\n\nCustomer-configured instructions:" in prompt
    assert prompt.count("I prefer blue.") == 1
    assert "The customer wants gift wrap." not in "\n".join(private_rules)


@pytest.mark.parametrize("flag, turn, should_schedule", [
    (None, "customer", False), ("false", "customer", False), ("true", "customer", True),
    ("true", "publish_test", False), ("true", "escalated", False), ("true", "follow_up", False),
    ("true", "test_lab", False), ("true", "test_chat", False), ("true", "thread_unavailable", True),
])
def test_pipeline_schedules_only_enabled_customer_turns_and_reads_stored_summary(
    monkeypatch, caplog, flag, turn, should_schedule,
):
    if flag is None:
        monkeypatch.delenv("CONVERSATION_SUMMARY_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CONVERSATION_SUMMARY_ENABLED", flag)
    scheduled = Mock()
    if turn == "thread_unavailable":
        def fail_summary(label, work):
            if label.startswith("[ConversationSummary]"):
                raise RuntimeError("private fixture text")
        scheduled.side_effect = fail_summary
    monkeypatch.setattr(pipeline, "_after_reply", scheduled)
    compact = Mock()
    monkeypatch.setattr(conversation_summary_service, "compact_if_due", compact)
    monkeypatch.setattr(pipeline, "get_recent_chat_history", lambda *a, **kw: [])
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *a, **kw: turn == "escalated")
    monkeypatch.setattr(pipeline, "analyze_agent_intent", lambda *a, **kw: {"intent": "question"})
    monkeypatch.setattr(pipeline, "get_bot_by_id", lambda _: {"id": 3, "company_id": 7})
    monkeypatch.setattr(pipeline, "update_workflow_state", Mock())
    monkeypatch.setattr(pipeline, "retrieve_relevant_chunks", lambda *a, **kw: [])
    monkeypatch.setattr(rag_service, "get_deployed_settings", lambda _: {})
    monkeypatch.setattr(rag_service.booking_intake_service, "prompt_section", lambda *a, **kw: "")
    conversation = {"id": 17, "chatbots": {"company_id": 7}, "publish_test": turn == "publish_test",
                    "history_summary": "The customer chose blue paper."}

    result = pipeline.prepare_chat_prompt(
        "What sizes do you offer?", {"test_lab": "web_testbot_session", "test_chat": "test_user"}.get(turn, "shopper"), 3,
        source_channel="web", conversation=conversation,
        follow_up_instruction="Ask about quantity." if turn == "follow_up" else None,
    )

    calls = [call for call in scheduled.call_args_list if call.args[0].startswith("[ConversationSummary]")]
    assert len(calls) == int(should_schedule)
    compact.assert_not_called()
    if turn == "thread_unavailable":
        assert "RuntimeError" in caplog.text and "private fixture text" not in caplog.text
    elif should_schedule:
        calls[0].args[1]()
        compact.assert_called_once_with(17, 3)
    if turn in {"customer", "follow_up", "thread_unavailable"}:
        assert conversation["history_summary"] in result["prompt"]
