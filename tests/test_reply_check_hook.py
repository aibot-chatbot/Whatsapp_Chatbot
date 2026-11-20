"""Exercise the real provider-to-reply path with local provider and storage doubles."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import agent_action_repository
from app.services import ai_router, chat_pipeline_service as pipeline, deepseek_service


DRAFT = "The shelf is RM80. Delivery is RM999 at 18:30."
MESSAGE = "Can you tell me about the shelf?"


@pytest.fixture
def chat(monkeypatch):
    context = {
        "prompt": "private prompt",
        "knowledge": [{"id": 41, "source": "private filename", "content": "Shelf RM80."}],
        "profile": {"company_name": "Example"}, "history": [],
        "company_id": 11, "conversation_id": 13,
    }
    events = []
    saved = []

    def save(**row):
        events.append("record")
        saved.append(row)

    def needs(draft, **kwargs):
        events.append(("needs", draft))
        return draft + " (processed)"

    def booking(draft, **kwargs):
        events.append(("booking", draft))
        return draft

    from app.services import company_status_service
    monkeypatch.delenv("REPLY_CHECK_MODE", raising=False)
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda _: {"id": 7, "company_id": 11})
    monkeypatch.setattr(ai_router.message_limits, "check", Mock(return_value=None))
    monkeypatch.setattr(ai_router.content_filter, "check_bot_text", Mock(return_value=None))
    monkeypatch.setattr(ai_router, "review_customer_message", Mock(return_value=None))
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=False, should_handoff_to_ai=True)))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    monkeypatch.setattr(ai_router, "process_needs_reply", needs)
    monkeypatch.setattr(ai_router, "process_booking_reply", booking)
    monkeypatch.setattr(pipeline, "_record_agent_action", save)
    monkeypatch.setattr(pipeline, "_after_reply", lambda _label, work: work())  # run the deferred audit inline
    consequences = Mock()
    monkeypatch.setattr(pipeline, "_check_client_flag_level", consequences)
    prepare = Mock(return_value=context)
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", prepare)
    monkeypatch.setattr(deepseek_service, "prepare_chat_prompt", prepare)
    response = {"choices": [{"message": {"content": DRAFT}}]}
    monkeypatch.setattr(ai_router.cloudflare_service, "request", Mock(return_value={
        **response, "id": "test-generation", "usage": {"prompt_tokens": 5, "completion_tokens": 8},
        "_cloudflare_pricing": [1, 1, 1],
    }))
    monkeypatch.setattr(ai_router.openrouter_service, "_request", Mock(return_value=(True, response)))
    sdk = Mock()
    sdk.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=DRAFT))])
    monkeypatch.setattr(deepseek_service, "_active_client", lambda: sdk)

    def generate(provider="openai"):
        monkeypatch.setattr(ai_router, "_route_for_enforcement", lambda *_: (provider, "test-model"))
        return ai_router.generate_response(MESSAGE, "customer", 7)

    return SimpleNamespace(generate=generate, saved=saved, events=events, context=context,
                           prepare=prepare, consequences=consequences, sdk=sdk)


@pytest.mark.parametrize("provider", ["openai", "cloudflare", "deepseek"])
def test_generated_draft_records_only_unsupported_facts_before_needs_and_booking(chat, provider, caplog):
    assert chat.generate(provider) == DRAFT + " (processed)"
    assert chat.events == ["record", "record", ("needs", DRAFT), ("booking", DRAFT + " (processed)")]
    chat.prepare.assert_called_once()
    assert sorted(row["payload"]["reply_check"]["subtype"] for row in chat.saved) == ["price", "time"]
    for row in chat.saved:
        finding = row["payload"]["reply_check"]
        assert row["payload"] == {"reply_check": {"category": "facts", "subtype": finding["subtype"],
                                                 "mode": "log", "chunk_ids": [41]}}
        assert row["intent"] not in agent_action_repository.ESCALATION_INTENTS
        assert row["intent"] == "unknown" and row["action_type"] == "none"
        assert (row["company_id"], row["chatbot_id"], row["conversation_id"]) == (11, 7, 13)
        assert not agent_action_repository._is_flag_payload(row["payload"])
        for private in (DRAFT, "999", "18:30", MESSAGE, "private prompt", "private filename"):
            assert private not in repr(row) + caplog.text
    chat.consequences.assert_not_called()


def test_legacy_deepseek_audits_once_and_keeps_its_plain_string(chat):
    assert deepseek_service.generate_response(MESSAGE, "customer", 7) == DRAFT
    assert chat.events == ["record", "record"]
    assert all(r["payload"]["reply_check"]["chunk_ids"] == [41] for r in chat.saved)


def test_failed_intent_analysis_still_records_findings_for_the_verified_bot_owner(chat, monkeypatch):
    # Prompt preparation continues when intent analysis fails before the normal owner lookup.
    chat.context["company_id"] = None
    lookup = Mock(return_value={"id": 7, "company_id": 11})
    monkeypatch.setattr(pipeline, "get_bot_by_id", lookup)
    assert chat.generate() == DRAFT + " (processed)"
    assert [row["company_id"] for row in chat.saved] == [11, 11]
    lookup.assert_called_once_with(7)


@pytest.mark.parametrize("raw", [{"choices": [{"message": {"content": DRAFT}}]}, DRAFT], ids=["dict", "text"])
def test_deepseek_generated_non_sdk_response_keeps_existing_billing_and_runs_checker(chat, raw):
    chat.sdk.chat.completions.create.return_value = raw
    assert chat.generate("deepseek") == DRAFT + " (processed)"
    assert chat.events[:2] == ["record", "record"]
    ai_router._make_usage_log.assert_not_called()


@pytest.mark.parametrize("mode", ["block", "unexpected", "OFF"])
def test_unknown_modes_log_and_off_skips_the_checker(chat, monkeypatch, mode):
    from app.services import reply_check_service
    check = Mock(wraps=reply_check_service.check_reply)
    monkeypatch.setattr(reply_check_service, "check_reply", check)
    monkeypatch.setenv("REPLY_CHECK_MODE", mode)
    assert chat.generate() == DRAFT + " (processed)"
    assert len(chat.saved) == 2
    check.assert_called_once()
    monkeypatch.setenv("REPLY_CHECK_MODE", "off")
    assert chat.generate() == DRAFT + " (processed)"
    assert len(chat.saved) == 2
    check.assert_called_once()


@pytest.mark.parametrize("failure", ["matcher", "storage"])
def test_check_errors_log_only_the_exception_type_and_leave_processing_intact(chat, monkeypatch, caplog, failure):
    from app.services import reply_check_service
    error = Mock(side_effect=ValueError("private exception detail " + DRAFT))
    if failure == "matcher":
        monkeypatch.setattr(reply_check_service, "check_reply", error)
    else:
        monkeypatch.setattr(pipeline, "_record_agent_action", error)
    assert chat.generate() == DRAFT + " (processed)"
    assert error.called
    assert "ValueError" in caplog.text
    assert "private exception detail" not in caplog.text and DRAFT not in caplog.text
    assert chat.events == [("needs", DRAFT), ("booking", DRAFT + " (processed)")]


def test_local_replies_bypass_the_checker_even_if_they_contain_amounts(chat, monkeypatch):
    from app.services import reply_check_service
    check = Mock(wraps=reply_check_service.check_reply)
    monkeypatch.setattr(reply_check_service, "check_reply", check)
    chat.generate()
    check.assert_called_once()
    check.reset_mock()
    chat.prepare.return_value = {"direct_reply": "Greeting RM750", "prompt": None}
    for provider in ("openai", "cloudflare", "deepseek"):
        assert chat.generate(provider) == "Greeting RM750 (processed)"
    assert deepseek_service.generate_response(MESSAGE, "customer", 7) == "Greeting RM750"
    acknowledgement = ai_router.HandoffAcknowledgement(
        "Staff will call at 14:00.", action_id=1, conversation_id=13, chatbot_id=7, company_id=11)
    chat.prepare.return_value = {"direct_reply": acknowledgement}
    assert chat.generate("deepseek") is acknowledgement
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=True, reply="Flow RM750")))
    assert chat.generate() == "Flow RM750"
    monkeypatch.setattr(ai_router.message_limits, "check", Mock(return_value="Limit RM750"))
    assert chat.generate() == "Limit RM750"
    monkeypatch.setattr(ai_router.message_limits, "check", Mock(return_value=None))
    monkeypatch.setattr(ai_router.content_filter, "check_bot_text", Mock(return_value=object()))
    monkeypatch.setattr(ai_router, "_refuse_flagged_message", Mock(return_value="Call 03-7627 2929."))
    assert chat.generate() == "Call 03-7627 2929."
    monkeypatch.setattr("app.database.conversation_repository.get_conversation_by_id_and_chatbot",
                        Mock(return_value={"id": 13, "source_channel": "whatsapp"}))
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", Mock(return_value=True))
    assert ai_router.generate_response(MESSAGE, "customer", 7, conversation_id=13) == "<SILENT_BOT_RESPONSE>"
    check.assert_not_called()


def test_audit_rows_are_written_off_the_reply_path(chat, monkeypatch):
    # Each audit row is a remote round trip (~124 ms); the reply must not wait for it.
    deferred = Mock()
    monkeypatch.setattr(pipeline, "_after_reply", deferred)
    chat.generate()
    assert chat.saved == []
    assert "[ReplyCheck] audit" in [call.args[0] for call in deferred.call_args_list]
    audit = next(call.args[1] for call in deferred.call_args_list if call.args[0] == "[ReplyCheck] audit")
    audit()
    assert chat.saved and all("reply_check" in row["payload"] for row in chat.saved)


@pytest.mark.parametrize("provider", ["openai", "cloudflare", "deepseek", "legacy-deepseek"])
def test_leak_and_promise_rows_are_private_and_never_customer_flags(chat, provider, monkeypatch, caplog):
    private = "Use the private queue order to decide which replacement products to mention first"
    if "deepseek" in provider:
        private = deepseek_service.CUSTOMER_SERVICE_SYSTEM_MESSAGE.split("Do not reveal ")[1]
    chat.context["system_prompt"] = "" if "deepseek" in provider else private
    draft = private + ". We guarantee success."
    chat.sdk.chat.completions.create.return_value.choices[0].message.content = draft
    response = {"choices": [{"message": {"content": draft}}]}
    monkeypatch.setattr(ai_router.openrouter_service, "_request", Mock(return_value=(True, response)))
    ai_router.cloudflare_service.request.return_value.update(response)
    if provider == "legacy-deepseek":
        assert deepseek_service.generate_response(MESSAGE, "customer", 7) == draft
    else:
        assert chat.generate(provider) == draft + " (processed)"
    assert [row["payload"] for row in chat.saved] == [
        {"reply_check": {"category": category, "subtype": subtype, "mode": "log", "chunk_ids": [41]}}
        for category, subtype in [("leak", "system_prompt"), ("promise", "guarantee")]]
    for row in chat.saved:
        assert row["intent"] == "unknown" and row["action_type"] == "none"
        assert not agent_action_repository._is_flag_payload(row["payload"])
        assert private not in repr(row) + caplog.text
    chat.consequences.assert_not_called()
