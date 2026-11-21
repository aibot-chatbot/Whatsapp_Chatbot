import logging
import re
from unittest.mock import Mock

import pytest

from app.database import agent_action_repository
from app.services import chat_pipeline_service, rag_service


@pytest.fixture(params=["", "Advise our shopper.\n{context}\n{conversation}\n{message}"], ids=["default", "custom"])
def template(request):
    return request.param


@pytest.fixture
def build(template, monkeypatch):
    settings = {
        "bot_name": "Aster", "company_name": "Paper Shop",
        "business_description": "We sell paper flowers.", "tone": "Cheerful",
        "additional_instructions": "Offer gift wrapping when appropriate.",
        "custom_prompt": template,
    }
    monkeypatch.setattr(rag_service, "get_deployed_settings", lambda _: settings)
    def booking(_, *, internal_rules=None):
        guidance = "Offer only a listed booking slot."
        if internal_rules is not None:
            internal_rules.append(guidance)
        return "\n" + guidance + "\nCatalogue: Saturday at noon.\n"

    monkeypatch.setattr(rag_service.booking_intake_service, "prompt_section", booking)

    def render(history=(), question="Which flowers?", chunks=(), **options):
        return rag_service.build_prompt(history, question, chunks, 3, **options)

    return render


def test_final_reminder_keeps_the_owners_custom_instructions_trusted(build):
    # 2 of 15 live bots use a custom prompt; their template sits after the header,
    # so the reminder must distrust only the data sections, never the owner's instructions.
    reminder = build().rsplit("\n\n", 2)[-2]
    assert "everything after" not in reminder
    for data in ("customer notes", "knowledge", "recent conversation", "user question"):
        assert data in reminder
    assert "Customer-configured instructions" in reminder


def test_each_merged_instruction_occurs_once(build):
    prompt = build()
    for phrase in (
        "Primary PDF knowledge", "Supporting website knowledge", "Do not invent",
        "in your own words", "one short clarification question", "step-by-step",
        "problems or frustration", "consistent terminology", "[BUTTONS: Option 1 | Option 2 | Option 3]",
    ):
        assert prompt.count(phrase) == 1, phrase
    assert not re.search(r"Additional response rules:|Final safety override:|follow rule 4|reply from rule 4", prompt)


def test_prepare_chat_prompt_requests_the_six_most_recent_messages(monkeypatch):
    recent = Mock(return_value=[])
    monkeypatch.setattr(chat_pipeline_service, "get_recent_chat_history", recent)
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *args, **kwargs: True)
    chat_pipeline_service.prepare_chat_prompt("Can I order?", "shopper", 3, conversation={"id": 17})
    recent.assert_called_once_with(17, limit=6)


def test_only_long_history_items_are_shortened(build):
    old = "花" * 300 + "x" * 200
    exact = "a" * 300
    question = "q" * 500
    prompt = build([{"role": "user", "content": old}, {"role": "assistant", "content": exact}], question)
    assert "User: " + "花" * 300 + "…\n" in prompt
    assert "Assistant: " + exact + "\n" in prompt
    assert "x" * 200 not in prompt
    assert question in prompt


def test_each_formatted_knowledge_chunk_is_capped_independently(build):
    remote = "界" * 2000
    source = "Supporting document knowledge"
    formatted = source + ":\n" + "z" * 2000
    chunks = [remote, {"source": source, "content": "z" * 2000}, "t" * 1500]
    prompt = build(chunks=chunks)
    assert "Context 1:\n" + remote[:1500] + "\n" in prompt
    assert "Context 2:\n" + formatted[:1500] + "\n" in prompt
    assert "Context 3:\n" + "t" * 1500 + "\n" in prompt
    assert remote[:1501] not in prompt and formatted[:1501] not in prompt


def test_same_bot_has_identical_static_prefix_for_different_customers(build, template, caplog):
    prefixes = []
    for name, stage in [("Ari", "understand"), ("Bea", "recommend")]:
        goal, fact, history, question = [f"{name} {kind}" for kind in ("goal", "fact", "history", "question")]
        with caplog.at_level(logging.INFO):
            prompt = build([{"role": "user", "content": history}], question, [fact],
                           customer_needs={"goal": goal, "stage": stage})
        header = rag_service.DYNAMIC_SECTION_HEADER
        prefix, suffix = prompt.split(header, 1)
        assert prefix.endswith("\n") and suffix.startswith("\n")
        assert all(text in prefix for text in (
            "Aster", "Paper Shop", "We sell paper flowers.", "cheerful tone",
            "Offer gift wrapping", "Non-negotiable customer service rules:", "4. Close:", "Saturday at noon",
        ))
        assert all(text not in prefix and suffix.count(text) == 1 for text in (goal, fact, history, question))
        assert "Conversation stage: " + stage in suffix and "Customer notes" not in prefix
        if template:
            assert "Advise our shopper." not in prefix and "Advise our shopper." in suffix
        assert "untrusted data" in suffix.split(question, 1)[1]
        assert suffix.rstrip().endswith("Never guess company facts.\n\nAssistant:")
        assert f"static={len(prefix)} " in caplog.text
        assert name not in caplog.text
        prefixes.append(prefix.encode("utf-8"))
    assert prefixes[0] == prefixes[1]


def test_private_instruction_evidence_covers_both_sides_of_header(build, template):
    sections = []
    prompt = build([{"role": "user", "content": "old conversation"}], "latest question", ["retrieved fact"],
                   customer_needs={"goal": "customer goal"}, internal_rules=sections)
    captured = "\n".join(sections)
    numbered = re.findall(r"^\d+\. .+$", prompt, flags=re.M)
    reminder = prompt.rstrip().split("\n\n")[-2]
    for instruction in [
        *numbered, "You are Aster, an AI assistant for Paper Shop.", "Reply in a cheerful tone.",
        "Offer gift wrapping when appropriate.", "Offer only a listed booking slot.",
        "Keeping these notes:", reminder,
    ]:
        assert instruction in captured
    if template:
        assert "Advise our shopper." in captured
    for public in ["We sell paper flowers.", "Saturday at noon", "retrieved fact", "customer goal",
                   "old conversation", "latest question"]:
        assert public not in captured


@pytest.mark.parametrize("template", ["Short preview: {message:.5}", "Style only: {{context}}"])
def test_partial_custom_template_preserves_full_customer_inputs(build):
    prompt = build([{"role": "user", "content": "previous turn"}], "current question", ["answer material"])
    _, tail = prompt.split(rag_service.DYNAMIC_SECTION_HEADER, 1)
    for text in ["previous turn", "current question", "answer material"]:
        assert tail.count(text) == 1
