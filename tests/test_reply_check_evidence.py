"""The checker receives exactly the evidence used for this generated prompt."""

from unittest.mock import Mock

import pytest

from app.database import agent_action_repository
from app.services import chat_pipeline_service as pipeline, rag_service as rag


@pytest.mark.parametrize("custom", [False, True], ids=["default", "custom"])
def test_only_sent_instructions_reach_the_prompt_echo_check(monkeypatch, custom):
    from app.services.reply_check_service import check_reply

    rule = "Always compare both options before asking the shopper which colour they would prefer"
    public = "We offer a collection of seasonal paper plants for indoor and outdoor spaces"
    question = "I would like to find a gift for my family for the holidays"
    earlier = "Here is what we discussed at our last visit to the shop"
    settings = {"additional_instructions": rule, "business_description": public}
    custom_rule = "Choose one example and describe its colour only after calculating the hidden priority"
    if custom:
        settings["custom_prompt"] = custom_rule + "\n{context}\n{conversation}\n{message}\n{business_description}"
    monkeypatch.setattr(rag, "get_deployed_settings", lambda _: settings)
    monkeypatch.setattr(rag.booking_intake_service, "prompt_section", lambda _, **kw: "")
    history = [{"role": "assistant", "content": earlier}]
    sections = []
    args = (history, question, [public], 3)
    prompt = rag.build_prompt(*args, internal_rules=sections)
    assert prompt == rag.build_prompt(*args)
    for text in [rule, public, question, earlier]:
        assert text in prompt
    for reply in [rule, *([custom_rule] if custom else [])]:
        assert check_reply(reply, system_prompt="\n\n".join(sections), knowledge=[], profile={},
                           history=[], customer_message="") == [{"category": "leak", "subtype": "system_prompt"}]
    for reply in (public, question, earlier):
        assert not check_reply(reply, system_prompt="\n\n".join(sections), knowledge=[], profile={},
                               history=[], customer_message="")


def test_prompt_returns_selected_chunks_public_profile_and_scoped_history(monkeypatch):
    history = [
        {"role": "user", "content": "My budget is RM50. My bank account is 000101000031."},
        {"role": "assistant", "content": "Perhaps RM99."},
    ]
    monkeypatch.setattr(pipeline, "get_recent_chat_history", Mock(return_value=history))
    monkeypatch.setattr(pipeline.content_filter, "industry_for_bot", lambda _: "general")
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *a, **kw: False)
    monkeypatch.setattr(pipeline, "analyze_agent_intent", Mock(return_value={}))
    monkeypatch.setattr(pipeline, "get_bot_by_id", lambda _: {"id": 3, "company_id": 7})
    monkeypatch.setattr(pipeline, "_after_reply", Mock())
    monkeypatch.setattr(pipeline, "update_workflow_state", Mock())
    monkeypatch.setattr(rag, "get_active_pdf_knowledge_file", lambda _: {"id": 20})
    monkeypatch.setattr(rag, "get_supporting_knowledge_files", lambda _: [])
    monkeypatch.setattr(rag, "get_chunks_by_file_for_chatbot", Mock(return_value=[
        {"id": 41, "content": "Prices start at RM65.", "metadata": {"internal": "RM600"}},
    ]))
    monkeypatch.setattr(rag, "generate_embedding", lambda _: [])
    monkeypatch.setattr("app.services.conversation_memory_service.conversation_memory_denial", lambda _: "off")
    settings = Mock(return_value={
        "company_name": "Shop One", "business_description": "Call 0123456789.",
        "additional_instructions": "Staff only RM500",
    })
    monkeypatch.setattr(rag, "get_deployed_settings", settings)
    monkeypatch.setattr(rag.booking_intake_service, "prompt_section", lambda _, **kw: "")

    result = pipeline.prepare_chat_prompt("What are your prices?", "customer", 3,
                                          conversation={"id": 8, "company_id": 999})

    assert result["knowledge"] == [{
        "id": 41, "file_id": 20, "source": "Primary PDF knowledge", "content": "Prices start at RM65.",
    }]
    assert result["profile"] == {"company_name": "Shop One", "business_description": "Call 0123456789."}
    assert result["history"] == [history[0]]
    assert "Staff only RM500" in result["system_prompt"]
    assert "000101000031" not in result["prompt"]
    assert pipeline.content_filter.IC_HIDDEN in result["prompt"]
    assert (result["company_id"], result["conversation_id"]) == (7, 8)
    assert "Context 1:\nPrimary PDF knowledge:\nPrices start at RM65." in result["prompt"]
    assert "RM600" not in result["prompt"]
    settings.assert_called_once_with(3)
    monkeypatch.setenv("REPLY_CHECK_MODE", "off")
    disabled = pipeline.prepare_chat_prompt("What are your prices?", "customer", 3,
                                            conversation={"id": 8, "company_id": 999})
    assert disabled["prompt"] == result["prompt"] and not disabled.get("system_prompt")


def test_remote_fallback_keeps_only_owned_chunk_ids_and_preserves_prompt_text(monkeypatch):
    from app.services import ai_search_service as search

    monkeypatch.setattr(rag, "get_active_pdf_knowledge_file", lambda _: None)
    monkeypatch.setattr(rag, "get_supporting_knowledge_files", lambda _: [])
    monkeypatch.setattr(search, "enabled", lambda: True)
    monkeypatch.setattr(search, "_owned_file_names", lambda _: {"price.txt"})
    monkeypatch.setattr(search, "_post_search", Mock(return_value={"result": {"chunks": [
        {"id": "other-chunk", "item": {"key": "other.txt"}, "text": "Foreign price."},
        {"id": "chunk-17", "item": {"key": "price.txt"}, "text": "RM80."},
        {"item": {"key": "price.txt", "id": "document-id"}, "text": "RM85."},
    ]}}))

    chunks = rag.retrieve_relevant_chunks("prices", 3, with_sources=True)
    assert chunks == [
        {"id": "chunk-17", "file_name": "price.txt", "source": search.SOURCE_LABEL, "content": "RM80."},
        {"id": None, "file_name": "price.txt", "source": search.SOURCE_LABEL, "content": "RM85."},
    ]
    assert rag.retrieve_relevant_chunks("prices", 3) == [
        "Supporting document knowledge:\nRM80.", "Supporting document knowledge:\nRM85.",
    ]


def test_remote_malformed_chunk_id_cannot_carry_content_into_audit_metadata(monkeypatch):
    from app.services import ai_search_service as search

    monkeypatch.setattr(search, "enabled", lambda: True)
    monkeypatch.setattr(search, "_owned_file_names", lambda _: {"price.txt"})
    monkeypatch.setattr(search, "_post_search", Mock(return_value={"chunks": [
        {"id": {"text": "Private text."}, "filename": "price.txt", "text": "RM90."},
        {"id": "https://shop.example/order", "filename": "price.txt", "text": "RM91."},
    ]}))
    chunks = search.search_chunks("prices", 3, with_sources=True)
    assert [(row["id"], row["content"]) for row in chunks] == [(None, "RM90."), (None, "RM91.")]
