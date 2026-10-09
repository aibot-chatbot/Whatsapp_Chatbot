"""Where the needs card plugs in: the model's reply on its way out, and the prompt on its way in.

Seam: ai_router.generate_response (real routing, replaced provider transport) and
chat_pipeline_service.prepare_chat_prompt. Only the provider, the database and the writers
are replaced; the reply is parsed and cleaned for real.
"""

import json
from unittest.mock import Mock

import pytest

from app.database import conversation_repository
from app.services import booking_intake_service, chat_pipeline_service
from tests.test_booking_intake_wiring import MARKER as BOOKING_MARKER, pipeline  # noqa: F401

NEEDS = {"goal": "Haircut before a wedding", "timing": "this Saturday", "stage": "close"}
NEEDS_MARKER = "<<NEEDS " + json.dumps(NEEDS) + ">>"


@pytest.fixture
def saved(monkeypatch):
    save = Mock(return_value=True)
    monkeypatch.setattr(conversation_repository, "save_customer_needs", save)
    return save


def test_the_customer_never_sees_the_note_and_it_is_saved_for_this_conversation(pipeline, saved):
    pipeline.say("Saturday works well before a wedding. What time suits you?\n" + NEEDS_MARKER)

    reply = pipeline.ask()

    assert reply == "Saturday works well before a wedding. What time suits you?"
    saved.assert_called_once_with(8, 3, NEEDS)


def test_a_note_and_a_booking_in_one_reply_both_work(pipeline, saved):
    pipeline.say("Thanks Ada! " + NEEDS_MARKER + "\n" + BOOKING_MARKER)

    reply = pipeline.ask()

    assert "NEEDS" not in reply and "BOOKING" not in reply
    assert reply == "Thanks Ada!\n\n" + booking_intake_service._ACKNOWLEDGEMENT
    saved.assert_called_once()
    pipeline.record.assert_called_once()


def test_a_note_wrapped_in_markdown_never_leaves_stray_symbols(pipeline, saved):
    pipeline.say("See you Saturday! **" + NEEDS_MARKER + "**")

    assert pipeline.ask() == "See you Saturday!"


def test_test_chats_keep_notes_too_so_owners_can_try_the_conversation(pipeline, saved):
    from app.services import ai_router

    pipeline.say("Got it.\n" + NEEDS_MARKER)

    assert pipeline.ask(operation_type=ai_router.OPERATION_TEST_CHAT) == "Got it."
    saved.assert_called_once()


def test_the_stored_card_is_passed_into_the_prompt(monkeypatch):
    conversation = {"id": 8, "chatbot_id": 3, "customer_needs": {"goal": "Improve maths"}}
    build = Mock(return_value="PROMPT")
    monkeypatch.setattr(chat_pipeline_service, "get_recent_chat_history", lambda *a, **k: [])
    monkeypatch.setattr(chat_pipeline_service, "analyze_agent_intent",
                        Mock(side_effect=RuntimeError("skip agent bookkeeping")))
    monkeypatch.setattr(chat_pipeline_service, "update_workflow_state", Mock())
    monkeypatch.setattr(chat_pipeline_service, "retrieve_relevant_chunks", lambda *a, **k: [])
    monkeypatch.setattr(chat_pipeline_service, "build_prompt", build)
    from app.database import agent_action_repository
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *a, **k: False)

    result = chat_pipeline_service.prepare_chat_prompt(
        "how much is the form 3 class?", "60123456789", 3, conversation=conversation)

    assert result["prompt"] == "PROMPT"
    assert build.call_args.kwargs["customer_needs"] == {"goal": "Improve maths"}
