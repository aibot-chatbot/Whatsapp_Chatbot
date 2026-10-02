"""Where chat intake plugs in: the model's reply on its way out, and the prompt on its way in.

Seam: ai_router.generate_response (real routing, replaced provider transport) and
rag_service.build_prompt. Only the provider, the database and the recorder are replaced.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import ai_access_policy, ai_router, booking_intake_service, rag_service
from app.services.model_catalog import CLOUDFLARE_PLAN_MODELS

FIELDS = {"kind": "booking", "service": "Haircut", "when": "2026-10-05 15:00", "name": "Ada"}
MARKER = "<<BOOKING " + json.dumps(FIELDS) + ">>"
CONVERSATION = {"id": 8, "chatbot_id": 3, "source_channel": "whatsapp"}


def _bot(enabled):
    model = CLOUDFLARE_PLAN_MODELS["essential"][0]
    return {"id": 3, "company_id": 7, "ai_provider": "cloudflare", "model_name": model,
            "booking_intake_enabled": enabled}


@pytest.fixture
def pipeline(monkeypatch):
    """generate_response with a provider that answers with whatever `say(text)` set."""
    from app.database import agent_action_repository, conversation_repository

    policy = ai_access_policy.AIAccessPolicy(
        allowed=True, access_state="essential", api_route="cloudflare", model_editable=True)
    monkeypatch.setattr(ai_router, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(ai_access_policy, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(ai_router, "_try_process_flow_message", lambda *a, **k: SimpleNamespace(
        handled=False, should_handoff_to_ai=True))
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", lambda **k: {"prompt": "tenant knowledge"})
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot",
                        lambda conversation_id, chatbot_id: dict(CONVERSATION))
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *a, **k: False)
    record = Mock(return_value={"id": 1})
    monkeypatch.setattr(booking_intake_service.booking_service, "record_chat_request", record)

    state = {"bot": _bot(True)}
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda _: state["bot"])

    def say(text):
        monkeypatch.setattr(ai_router.cloudflare_service, "request", Mock(return_value={
            "id": "call", "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}))

    def ask(conversation_id=8, **options):
        return ai_router.generate_response("book me a haircut", "60123456789", 3,
                                           source_channel="whatsapp", conversation_id=conversation_id, **options)

    return SimpleNamespace(state=state, say=say, ask=ask, record=record)


# --- outgoing reply ----------------------------------------------------------------

def test_an_enabled_bot_records_the_request_and_the_customer_never_sees_the_marker(pipeline):
    pipeline.say("Thanks Ada, I have your details. " + MARKER)

    reply = pipeline.ask()

    assert "BOOKING" not in reply
    assert reply == "Thanks Ada, I have your details.\n\n" + booking_intake_service._ACKNOWLEDGEMENT
    kwargs = pipeline.record.call_args.kwargs
    assert (kwargs["company_id"], kwargs["chatbot_id"], kwargs["conversation_id"]) == (7, 3, 8)
    assert kwargs["channel"] == "whatsapp" and kwargs["customer_phone"] == "+60123456789"
    assert kwargs["fields"] == FIELDS


def test_a_disabled_bot_still_hides_the_marker_and_records_nothing(pipeline):
    pipeline.state["bot"] = _bot(False)
    pipeline.say("Noted. " + MARKER)

    reply = pipeline.ask()

    assert "BOOKING" not in reply
    pipeline.record.assert_not_called()


def test_a_chat_without_a_verified_conversation_hides_the_marker_and_records_nothing(pipeline):
    pipeline.say("Noted. " + MARKER)

    reply = pipeline.ask(conversation_id=None)

    assert "BOOKING" not in reply
    pipeline.record.assert_not_called()


def test_an_ordinary_reply_is_untouched(pipeline):
    pipeline.say("We open at 9am.")

    assert pipeline.ask() == "We open at 9am."
    pipeline.record.assert_not_called()


def test_a_recorder_failure_never_breaks_the_reply_and_never_claims_success(pipeline):
    pipeline.record.side_effect = RuntimeError("db down")
    pipeline.say("It has been sent to the team! " + MARKER)

    assert pipeline.ask() == booking_intake_service._NOT_RECORDED


def test_the_marker_is_stripped_before_markdown_cleanup_can_mangle_it(pipeline):
    # clean_ai_reply rewrites "**", "__" and leading "- "; the JSON must be read first.
    tricky = '<<BOOKING {"service": "Dinner __ Lunch", "notes": "**window**"}>>'
    pipeline.say("Thanks! " + tricky)

    reply = pipeline.ask()

    assert reply == "Thanks!\n\n" + booking_intake_service._ACKNOWLEDGEMENT
    assert pipeline.record.call_args.kwargs["fields"]["service"] == "Dinner __ Lunch"


@pytest.mark.parametrize("wrapped", ["**{m}**", "### {m}", "__{m}__", "```\n{m}\n```"])
def test_a_marker_wrapped_in_markdown_never_sends_an_empty_message(pipeline, wrapped):
    pipeline.say(wrapped.format(m=MARKER))

    assert pipeline.ask() == booking_intake_service._ACKNOWLEDGEMENT


@pytest.mark.parametrize("operation", [ai_router.OPERATION_TEST_CHAT, ai_router.OPERATION_TEST_BOT])
def test_dashboard_test_chats_never_create_bookings_or_emails(pipeline, operation):
    pipeline.say("Thanks Ada! " + MARKER)

    reply = pipeline.ask(operation_type=operation)

    assert "BOOKING" not in reply and booking_intake_service._TEST_NOTE in reply
    pipeline.record.assert_not_called()


# --- incoming prompt -----------------------------------------------------------------

@pytest.fixture
def prompt(monkeypatch):
    runtime = {"deployed_profile_name": "Profile", "industry_template_published": {}}
    monkeypatch.setattr(rag_service, "get_deployed_runtime", lambda _: runtime)
    monkeypatch.setattr(rag_service, "get_profile_by_name", lambda *_: {"custom_prompt": ""})
    state = {"bot": _bot(True)}
    monkeypatch.setattr(booking_intake_service, "get_bot_by_id", lambda _: state["bot"])
    return SimpleNamespace(state=state, build=lambda: rag_service.build_prompt([], "book a table", [], 3))


def test_an_enabled_bot_prompt_carries_the_booking_rules(prompt):
    built = prompt.build()

    assert "<<BOOKING" in built and "not confirmed" in built


def test_a_disabled_bot_prompt_is_unchanged(prompt):
    prompt.state["bot"] = _bot(False)

    assert "<<BOOKING" not in prompt.build()


def test_a_custom_prompt_still_gets_the_booking_rules(monkeypatch, prompt):
    monkeypatch.setattr(rag_service, "get_profile_by_name",
                        lambda *_: {"custom_prompt": "Custom reply for {message}"})

    assert "<<BOOKING" in prompt.build()
