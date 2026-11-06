"""OpenRouter judges the whole account, so every call is attributable and every block is seen."""
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import requests

from app.services import (
    ai_router, chat_pipeline_service, email_service, geo_comparison_service, geo_provider_service,
    openrouter_service, report_service,
)
from app.services import channel_delivery_service as delivery
from app.services.channel_delivery_service import HandoffAcknowledgement

PHONE = "60123456789"
MODEL = "openai/gpt-6-luna"
FLAGGED_TEXT = "synthetic flagged customer sentence"
APP_DIR = Path(__file__).resolve().parents[1] / "app"
MODERATION = {"error": {"code": 403, "message": "Your input was flagged", "metadata": {
    "reasons": ["violence"], "flagged_input": FLAGGED_TEXT,
    "provider_name": "OpenAI", "model_slug": MODEL,
}}}


def http_response(status=200, payload=None):
    body = payload if payload is not None else {"choices": [{"message": {"content": "hi"}}]}
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body
    response.text = json.dumps(body)
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=response)
    return response


@pytest.fixture
def world(monkeypatch):
    from app.database import agent_action_repository, conversation_repository
    from app.services import company_status_service

    saved = []

    def save(**fields):
        saved.append(fields)
        return {"id": 40 + len(saved)}

    def pending(action_id, conversation_id, chatbot_id, company_id):
        return any(40 + index == action_id and row["conversation_id"] == conversation_id
                   and row["intent"] == "handoff_request" for index, row in enumerate(saved, 1))

    world = SimpleNamespace(
        saved=saved, post=Mock(return_value=http_response()), usage=Mock(), lead=Mock(),
        staff_email=Mock(return_value=True), owner_email=Mock(return_value=True),
    )
    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda conversation_id, chatbot_id: {
        "id": conversation_id, "chatbot_id": chatbot_id, "source_channel": "telegram", "customer_phone": PHONE})
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated",
                        lambda conversation_id, *_, **__: any(row["conversation_id"] == conversation_id for row in saved))
    monkeypatch.setattr(delivery, "is_pending_handoff_action", pending)
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=save))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", world.lead)
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", lambda _label, work: work())
    monkeypatch.setattr(chat_pipeline_service, "_outage_email_sent_at", {})
    monkeypatch.setattr(email_service, "send_handoff_notification_email", world.staff_email)
    monkeypatch.setattr(email_service, "send_moderation_alert_email", world.owner_email)
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=False, should_handoff_to_ai=True, reply=None)))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("openai", MODEL)))
    monkeypatch.setattr(ai_router, "_get_system_provider_for_enforcement", Mock(return_value=("openai", MODEL)))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router, "_make_usage_log", world.usage)
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", Mock(return_value={
        "direct_reply": None, "prompt": "built prompt", "intent": "question"}))
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", "synthetic-openrouter-key")
    monkeypatch.setattr(openrouter_service.requests, "post", world.post)
    monkeypatch.setattr(openrouter_service, "_moderation_alert_sent_at", {})
    monkeypatch.setattr(openrouter_service, "_in_background", lambda work: work())
    return world


def customer_message(**kwargs):
    return ai_router.generate_response("a question", PHONE, 3, source_channel="telegram",
                                       conversation_id=8, **kwargs)


def sent_body(world):
    return world.post.call_args.kwargs["json"]


def geo_comparison():
    return geo_provider_service._openrouter_openai("Prompt", "MY", "en")


# Every call names a pseudonymous end user, so a provider block lands on one person.

def test_a_customer_reply_names_a_hashed_end_user(world):
    ai_router.call_provider("openai", "hello", PHONE, 3, model_name=MODEL, company_id=1)

    user = sent_body(world)["user"]
    assert re.fullmatch(r"omx_[0-9a-f]{32}", user)
    assert PHONE not in user


def test_one_customer_keeps_one_id_and_clients_never_share_one():
    first = openrouter_service.end_user_id(1, PHONE)

    assert first == openrouter_service.end_user_id(1, PHONE)
    assert first != openrouter_service.end_user_id(2, PHONE)
    assert first != openrouter_service.end_user_id(1, "60199999999")


def test_the_id_cannot_be_recomputed_without_the_server_secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "synthetic-secret-one")
    first = openrouter_service.end_user_id(1, PHONE)
    monkeypatch.setenv("SECRET_KEY", "synthetic-secret-two")

    assert first != openrouter_service.end_user_id(1, PHONE)


def test_background_ai_work_is_attributed_to_the_client(world):
    ai_router.generate_system_response("summarise this", 3)

    assert sent_body(world)["user"] == openrouter_service.end_user_id(1)


def test_the_geo_comparison_does_not_fall_back_to_the_account_identity(world):
    geo_comparison()

    assert re.fullmatch(r"omx_[0-9a-f]{32}", sent_body(world)["user"])


def test_only_one_place_in_the_app_can_call_openrouter():
    builders = sorted(path.name for path in APP_DIR.rglob("*.py")
                      if "openrouter_chat_completions_url(" in path.read_text(encoding="utf-8")
                      and path.name != "ai_gateway.py")

    assert builders == ["openrouter_service.py"]
    assert not [path.name for path in APP_DIR.rglob("*.py")
                if "openrouter.ai/api/v1/chat" in path.read_text(encoding="utf-8")
                and path.name != "ai_gateway.py"]
    assert (APP_DIR / "services" / "openrouter_service.py").read_text(encoding="utf-8").count("requests.post(") == 1


# A moderation block is a violation to act on, not an outage.

def test_a_block_pauses_the_chat_without_calling_it_an_outage(world):
    world.post.return_value = http_response(403, MODERATION)

    reply = customer_message()

    assert isinstance(reply, HandoffAcknowledgement)
    assert reply == chat_pipeline_service.MODERATION_HANDOFF_REPLY
    assert "unavailable" not in reply.lower()
    assert world.saved[0]["intent"] == "handoff_request"
    assert world.saved[0]["action_type"] == "request_handoff"
    assert world.saved[0]["payload"] == {"trigger": "moderation_block", "reasons": ["violence"],
                                         "provider_name": "OpenAI", "model_slug": MODEL}
    assert world.staff_email.call_args.kwargs["trigger"] == "moderation_block"


def test_the_record_keeps_the_reason_but_never_the_customers_words(world):
    world.post.return_value = http_response(403, MODERATION)

    customer_message()

    assert FLAGGED_TEXT not in repr(world.saved)
    assert FLAGGED_TEXT not in repr(world.staff_email.call_args)
    assert FLAGGED_TEXT not in repr(world.owner_email.call_args)


def test_a_blocked_message_is_sent_once_and_costs_the_client_nothing(world):
    world.post.return_value = http_response(403, MODERATION)

    customer_message()

    assert world.post.call_count == 1
    world.usage.assert_not_called()


def test_a_403_without_moderation_details_stays_an_outage(world):
    world.post.return_value = http_response(403, {"error": {"code": 403, "message": "Key limit exceeded"}})

    reply = customer_message()

    assert reply == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    assert world.saved[0]["payload"] == {"trigger": "ai_unavailable"}
    world.owner_email.assert_not_called()


def test_a_test_chat_is_refused_without_paging_staff(world):
    world.post.return_value = http_response(403, MODERATION)

    reply = customer_message(operation_type=ai_router.OPERATION_TEST_BOT)

    assert reply == chat_pipeline_service.MODERATION_BLOCKED_REPLY
    assert world.saved == []
    world.staff_email.assert_not_called()
    world.owner_email.assert_called_once()


def test_a_failed_handoff_never_promises_that_staff_will_reply(world, monkeypatch):
    world.post.return_value = http_response(403, MODERATION)
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=RuntimeError("database down")))

    reply = customer_message()

    assert reply == chat_pipeline_service.MODERATION_BLOCKED_REPLY


def test_background_work_fails_on_a_block_and_still_alerts_the_owner(world):
    world.post.return_value = http_response(403, MODERATION)

    with pytest.raises(openrouter_service.ModerationBlocked):
        ai_router.generate_system_response("summarise this", 3)

    world.owner_email.assert_called_once()


def test_the_geo_comparison_reports_a_block_as_its_own_failure(world):
    world.post.return_value = http_response(403, MODERATION)

    result = geo_comparison()

    assert result["request_status"] == "failed"
    assert result["error_code"] == "provider_moderation_block"
    world.owner_email.assert_called_once()


# Provider error bodies can quote the customer, so they never reach a log.

@pytest.mark.parametrize("status,payload", [
    (403, MODERATION),
    (500, {"error": {"code": 500, "message": FLAGGED_TEXT}}),
])
def test_provider_error_bodies_never_reach_the_logs(world, caplog, status, payload):
    world.post.return_value = http_response(status, payload)

    with caplog.at_level(logging.DEBUG):
        try:
            openrouter_service._request("prompt", model=MODEL, company_id=1, customer_id=PHONE)
        except openrouter_service.ModerationBlocked:
            pass

    assert FLAGGED_TEXT not in caplog.text
    assert PHONE not in caplog.text


# The owner hears about a block while the account is still healthy.

def test_a_burst_emails_once_per_client_but_logs_every_block(world, caplog):
    world.post.return_value = http_response(403, MODERATION)

    with caplog.at_level(logging.ERROR):
        for company_id in (1, 1, 2):
            with pytest.raises(openrouter_service.ModerationBlocked):
                openrouter_service.post_chat_completion({"model": MODEL}, api_key="k", company_id=company_id)

    assert world.owner_email.call_count == 2
    assert caplog.text.count("OpenRouter moderation block") == 3


@pytest.mark.parametrize("configured,expected", [
    ("owner@example.test", "owner@example.test"),
    ("", "noreply@example.test"),
])
def test_the_owner_email_reports_the_block_without_customer_data(monkeypatch, configured, expected):
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "noreply@example.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "synthetic-password")
    monkeypatch.setenv("PLATFORM_ALERT_EMAIL", configured)
    smtp = Mock()
    connect = Mock(return_value=smtp)
    monkeypatch.setattr(email_service.smtplib, "SMTP", connect)

    sent = email_service.send_moderation_alert_email(
        company_id=1, reasons=["violence"], provider_name="OpenAI", model_slug=MODEL)

    assert sent is True
    assert smtp.sendmail.call_args.args[1] == expected
    message = smtp.sendmail.call_args.args[2]
    assert "violence" in message and MODEL in message and "Company ID: 1" in message
    assert connect.call_args.kwargs["timeout"] == email_service.SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS


def test_the_owner_email_reports_failure_without_smtp_settings(monkeypatch):
    monkeypatch.delenv("SMTP_SENDER_EMAIL", raising=False)
    monkeypatch.delenv("SMTP_APP_PASSWORD", raising=False)

    assert email_service.send_moderation_alert_email(
        company_id=1, reasons=[], provider_name=None, model_slug=None) is False


def test_a_block_with_empty_reasons_still_reaches_the_owner(world):
    body = {"error": {"code": 403, "metadata": {"reasons": ["", None, "violence"], "flagged_input": FLAGGED_TEXT}}}
    world.post.return_value = http_response(403, body)

    with pytest.raises(openrouter_service.ModerationBlocked) as blocked:
        openrouter_service.post_chat_completion({"model": MODEL}, api_key="k", company_id=1)

    assert blocked.value.reasons == ["violence"]


def test_the_geo_comparison_keeps_its_own_request_shape(world):
    result = geo_comparison()

    assert result["request_status"] == "complete"
    assert sent_body(world)["provider"]["order"] == ["openai"]
    assert world.post.call_args.kwargs["headers"]["X-OpenRouter-Title"] == "Omnexa GEO Route Comparison"


def test_a_geo_comparison_is_attributed_to_the_client_who_ran_it(world, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    repository = Mock()
    repository.get_comparison_by_key.return_value = None
    repository.reserve_comparison.return_value = {"reserved_new": True, "comparison_id": 1}
    repository.finish_comparison.return_value = {}
    monkeypatch.setattr(geo_comparison_service, "geo_repository", repository)
    monkeypatch.setattr(geo_comparison_service, "_public_result", Mock(return_value={}))

    geo_comparison_service.run_metered_comparison(7, 1, {}, "request-1", prompt="Prompt", country="MY", language="en")

    users = [call.kwargs["json"].get("user") for call in world.post.call_args_list]
    assert openrouter_service.end_user_id(7, geo_provider_service._GEO_END_USER) in users


def test_an_observation_never_shares_an_identity_with_the_whole_client(world):
    ai_router.generate_system_response("classify this", 3, customer_id="observation-message:5")

    assert sent_body(world)["user"] == openrouter_service.end_user_id(1, "observation-message:5")


def test_a_403_that_is_not_json_stays_an_outage(world):
    response = http_response(403)
    response.json.side_effect = ValueError("not json")
    world.post.return_value = response

    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY
    world.owner_email.assert_not_called()


def test_a_normal_reply_is_still_billed_exactly_once(world, monkeypatch):
    monkeypatch.setattr(ai_router, "process_needs_reply", lambda text, **_: text)
    monkeypatch.setattr(ai_router, "process_booking_reply", lambda text, **_: text)
    world.post.return_value = http_response(200, {
        "id": "gen-1", "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "cost": 0.001},
    })

    assert customer_message() == "hi"
    world.usage.assert_called_once()


def test_a_block_after_staff_took_over_stays_silent(world):
    def taken_over_during_the_call(*_args, **_kwargs):
        world.saved.append({"conversation_id": 8, "intent": "handoff_request"})
        return http_response(403, MODERATION)

    world.post.side_effect = taken_over_during_the_call

    assert customer_message() == "<SILENT_BOT_RESPONSE>"


def test_every_blocked_customer_is_reported_to_staff(world):
    world.post.return_value = http_response(403, MODERATION)

    customer_message()
    ai_router.generate_response("a question", "60199999999", 3, source_channel="telegram", conversation_id=9)

    assert world.staff_email.call_count == 2


def test_an_undelivered_owner_alert_is_tried_again_on_the_next_block(world):
    world.post.return_value = http_response(403, MODERATION)
    world.owner_email.return_value = False

    for _ in range(2):
        with pytest.raises(openrouter_service.ModerationBlocked):
            openrouter_service.post_chat_completion({"model": MODEL}, api_key="k", company_id=1)

    assert world.owner_email.call_count == 2


def test_a_blocked_report_says_that_retrying_will_not_help(monkeypatch):
    monkeypatch.setattr(report_service, "get_transcript_logs", Mock(return_value=[{"phone": PHONE, "chat": "text"}]))
    monkeypatch.setattr(report_service, "get_bot_by_id", Mock(return_value={"ai_provider": "openai", "model_name": MODEL}))
    monkeypatch.setattr(report_service, "generate_system_response",
                        Mock(side_effect=openrouter_service.ModerationBlocked()))

    with pytest.raises(ValueError, match="Trying again will not help"):
        report_service.generate_weekly_report(3)


def test_the_comparison_screen_explains_a_block():
    script = APP_DIR.parent / "frontend" / "assets" / "js" / "geo-provider-comparison.js"

    assert "provider_moderation_block:" in script.read_text(encoding="utf-8")
