"""Token control: usage we can trust, one length rule, and caps that never cut real work."""
import logging
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services import ai_gateway, ai_router, deepseek_service, openrouter_service, rag_service

SONNET = "anthropic/claude-sonnet-5.5"
LUNA = "openai/gpt-6-luna"
FLASH = "google/gemini-3.8-flash"
PRO = "google/gemini-3.1-pro-preview"
LARGEST_REAL_SYSTEM_OUTPUT = 9913


def chat_data(content="Hi there.", finish_reason="stop"):
    return {"id": "gen-1", "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 532, "total_tokens": 632, "cost": 0.002,
                      "completion_tokens_details": {"reasoning_tokens": 498},
                      "prompt_tokens_details": {"cached_tokens": 40}}}


@pytest.fixture
def post(monkeypatch):
    response = MagicMock(status_code=200)
    response.json.return_value = chat_data()
    sender = Mock(return_value=response)
    monkeypatch.setattr(openrouter_service.requests, "post", sender)
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    return sender


def body_of(sender):
    return sender.call_args.kwargs["json"]


@pytest.fixture
def reply_with(monkeypatch):
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", Mock(return_value={
        "direct_reply": None, "prompt": "built prompt", "intent": "question"}))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())

    def _reply(content, finish_reason):
        monkeypatch.setattr(openrouter_service, "_request", Mock(return_value=(True, chat_data(content, finish_reason))))
        return ai_router.call_provider("anthropic", "hello", "60123456789", 3, model_name=SONNET, company_id=1).text

    return _reply


@pytest.fixture
def build(monkeypatch):
    settings = {"company_name": "Bright Tuition", "industry_template_published": {}}
    monkeypatch.setattr(rag_service, "get_deployed_settings",
                        lambda _: {**settings, "custom_prompt": settings.get("custom_prompt", "")})
    monkeypatch.setattr(rag_service.booking_intake_service, "prompt_section", lambda _: "")

    def _build(custom_prompt="", message="synthetic customer words"):
        settings["custom_prompt"] = custom_prompt
        return rag_service.build_prompt([{"role": "user", "content": "earlier words"}], message, [], 7)

    return _build


class FakeOpenAI:
    last = None

    def __init__(self, **_kwargs):
        FakeOpenAI.last = self
        self.sent = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.sent = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
                               usage=None)


# Usage we can trust

def test_reasoning_and_cached_tokens_are_read_from_where_openrouter_puts_them():
    result = ai_router._complete_provider_result("hi", "openrouter", SONNET, chat_data())

    assert result.reasoning_tokens == 498
    assert result.cached_tokens == 40


def test_reading_those_fields_leaves_the_billed_cost_alone():
    result = ai_router._complete_provider_result("hi", "openrouter", SONNET, chat_data())

    assert result.provider_cost_micro_usd == 2000
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 532


def test_a_response_without_details_still_reads_as_zero():
    data = {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    result = ai_router._complete_provider_result("hi", "openrouter", SONNET, data)

    assert (result.reasoning_tokens, result.cached_tokens) == (0, 0)


@pytest.mark.parametrize("custom_prompt", ["", "Reply as our adviser: {message}"])
def test_prompt_size_is_logged_as_numbers_only(build, caplog, custom_prompt):
    with caplog.at_level(logging.INFO):
        build(custom_prompt)

    line = next(record.getMessage() for record in caplog.records if "[PromptSize]" in record.getMessage())
    assert re.search(r"chatbot_id=7 rules=\d+ knowledge=\d+ history=\d+ message=\d+$", line)
    assert "synthetic customer words" not in caplog.text
    assert "earlier words" not in caplog.text


# One length rule

@pytest.mark.parametrize("custom_prompt", ["", "Reply as our adviser: {message}"])
def test_the_prompt_has_one_length_rule(build, custom_prompt):
    prompt = build(custom_prompt)

    assert prompt.count("at most 3 short sentences") == 1
    assert "list, steps or a comparison" in prompt
    assert "one to three short sentences" not in prompt
    assert "Keep the reply short" not in prompt
    assert "Keep replies short" not in prompt
    assert "avoiding unnecessary filler" not in prompt


def test_rules_that_pushed_replies_longer_are_gone(build):
    prompt = build()

    assert "reference the source" not in prompt
    assert "practical examples" not in prompt


def test_the_remaining_extra_rules_are_numbered_without_gaps(build):
    block = build().split("Additional response rules:")[1].split("Final fallback instruction:")[0]

    assert re.findall(r"^(\d+)\. ", block, flags=re.M) == [str(n) for n in range(1, 14)]


# Caps

def test_a_chat_reply_is_capped_at_800_tokens(post):
    openrouter_service._request("prompt", model=SONNET)

    assert body_of(post)["max_tokens"] == 800


def test_a_trial_chat_reply_has_the_same_cap(monkeypatch):
    client = FakeOpenAI()
    monkeypatch.setattr(deepseek_service, "_active_client", lambda: client)
    monkeypatch.setattr(deepseek_service, "prepare_chat_prompt", Mock(return_value={
        "direct_reply": None, "prompt": "built prompt", "intent": "question"}))

    deepseek_service._request("hello", "60123456789", 3)

    assert client.sent["max_tokens"] == 800


def test_the_system_cap_sits_above_the_largest_real_job():
    assert ai_gateway.MAX_SYSTEM_RESPONSE_TOKENS > LARGEST_REAL_SYSTEM_OUTPUT


def test_background_openrouter_work_is_capped(post):
    ai_router._call_openrouter_direct("prompt", SONNET, 0.3)

    assert body_of(post)["max_tokens"] == ai_gateway.MAX_SYSTEM_RESPONSE_TOKENS


def test_background_deepseek_work_is_capped(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key")

    with patch("openai.OpenAI", FakeOpenAI):
        ai_router._call_deepseek_direct("prompt", "deepseek-v4-flash", 0.3)

    assert FakeOpenAI.last.sent["max_tokens"] == ai_gateway.MAX_SYSTEM_RESPONSE_TOKENS


# Reasoning, as measured on 2026-11-07

@pytest.mark.parametrize("model", [FLASH, PRO])
def test_gemini_chat_replies_use_the_lowest_reasoning_it_accepts(post, model):
    openrouter_service._request("prompt", model=model)

    assert body_of(post)["reasoning"] == {"effort": "minimal"}


@pytest.mark.parametrize("model", [SONNET, LUNA, "anthropic/claude-haiku-4.5", "openai/gpt-6.1-sol"])
def test_models_that_spent_no_reasoning_are_left_alone(post, model):
    openrouter_service._request("prompt", model=model)

    assert "reasoning" not in body_of(post)


def test_background_work_keeps_its_full_reasoning(post):
    ai_router._call_openrouter_direct("prompt", FLASH, 0.3)

    assert "reasoning" not in body_of(post)


def test_verbosity_is_not_sent_because_it_saved_nothing(post):
    openrouter_service._request("prompt", model=LUNA)

    assert "verbosity" not in body_of(post)


# Replies cut off by the cap

@pytest.mark.parametrize("cut,kept", [
    ("Math is RM120 a month. It runs on Satur", "Math is RM120 a month."),
    ("Math is RM12.50 a month! Classes run on Sat", "Math is RM12.50 a month!"),
    ("数学每月RM120。上课时间是星", "数学每月RM120。"),
    ('Thanks for waiting. <<NEEDS {"goal": "ma', "Thanks for waiting."),
    ("Thanks for waiting. <<NE", "Thanks for waiting."),
    ('Noted. <<NEEDS {"goal": "maths"}>> Next we ca', 'Noted. <<NEEDS {"goal": "maths"}>>'),
    ("No sentence ends anywhere in this text", "No sentence ends anywhere in this text"),
    ("Steps:\n1. Open settings.\n2. Tap Account and then choose", "Steps:\n1. Open settings."),
    ("The fee is RM120. It runs on Satur", "The fee is RM120."),
])
def test_a_cut_off_reply_ends_on_something_whole(reply_with, cut, kept):
    assert reply_with(cut, "length") == kept


def test_a_finished_reply_is_never_trimmed(reply_with):
    assert reply_with("Math is RM120. It runs on Satur", "stop") == "Math is RM120. It runs on Satur"


def test_a_cut_off_trial_reply_is_trimmed_too(monkeypatch):
    raw = SimpleNamespace(usage=None, choices=[SimpleNamespace(
        message=SimpleNamespace(content="Math is RM120. It runs on Satur"), finish_reason="length")])
    monkeypatch.setattr(deepseek_service, "_request", Mock(return_value=(True, raw)))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())

    result = ai_router.call_provider("deepseek", "hello", "60123456789", 3, model_name="deepseek-v4-flash", company_id=1)

    assert result.text == "Math is RM120."


def test_an_empty_reply_does_not_crash(reply_with):
    assert reply_with(None, "length") == ""


def test_an_empty_billed_reply_goes_to_staff_and_is_still_logged(monkeypatch):
    from app.database import agent_action_repository, conversation_repository
    from app.services import company_status_service

    usage_log = Mock()
    handoff = Mock(return_value="staff will reply")
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot",
                        lambda conversation_id, chatbot_id: {"id": conversation_id, "chatbot_id": chatbot_id,
                                                             "source_channel": "telegram"})
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated", lambda *_, **__: False)
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=False, should_handoff_to_ai=True, reply=None)))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("anthropic", SONNET)))
    monkeypatch.setattr(ai_router, "_make_usage_log", usage_log)
    monkeypatch.setattr(ai_router, "hand_off_after_ai_failure", handoff)
    monkeypatch.setattr(ai_router, "_reply_for_current_handoff", lambda reply, *_: reply)
    monkeypatch.setattr(ai_router, "call_provider", Mock(return_value=ai_router._complete_provider_result(
        "", "openrouter", SONNET, chat_data("", "length"))))

    reply = ai_router.generate_response("hello", "60123456789", 3, source_channel="telegram", conversation_id=8)

    assert reply == "staff will reply"
    usage_log.assert_called_once()


def test_an_empty_trial_reply_counts_as_a_failure(monkeypatch):
    raw = SimpleNamespace(usage=None, choices=[SimpleNamespace(
        message=SimpleNamespace(content=""), finish_reason="length")])
    monkeypatch.setattr(deepseek_service, "_request", Mock(return_value=(True, raw)))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())

    result = ai_router.call_provider("deepseek", "hello", "60123456789", 3, model_name="deepseek-v4-flash", company_id=1)

    assert result.success is False


def test_a_cut_off_cloudflare_reply_is_trimmed_too(monkeypatch):
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", Mock(return_value={
        "direct_reply": None, "prompt": "built prompt", "intent": "question"}))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router.cloudflare_service, "request",
                        Mock(return_value=chat_data("Math is RM120. It runs on Satur", "length")))
    monkeypatch.setattr(ai_router.cloudflare_service, "extract_usage",
                        Mock(return_value={"provider": "cloudflare", "model": "m"}))

    result = ai_router.call_provider("cloudflare", "hello", "60123456789", 3, model_name="m", company_id=1)

    assert result.text == "Math is RM120."
