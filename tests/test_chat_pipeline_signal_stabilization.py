"""Shared-pipeline tests for handoff CRM behavior and non-blocking failures."""

from unittest.mock import patch

from app.services import chat_pipeline_service


HANDOFF_DECISION = {
    "intent": "handoff_request",
    "suggested_action": "request_handoff",
    "confidence": 0.86,
    "reason": "Customer requested a person.",
}
CONVERSATION = {
    "id": 101,
    "chatbot_id": 29,
    "company_id": 999,
    "customer_phone": "+60123456789",
    "source_channel": "whatsapp",
}


def _handoff_pipeline_patches(
    crm_side_effect=None,
    chatbot=None,
):
    if chatbot is None:
        chatbot = {"id": 29, "company_id": 42}

    return (
        patch.object(
            chat_pipeline_service,
            "get_or_create_conversation",
            return_value=CONVERSATION,
        ),
        patch.object(
            chat_pipeline_service,
            "get_recent_chat_history",
            return_value=[],
        ),
        patch(
            "app.database.agent_action_repository.is_conversation_escalated",
            return_value=False,
        ),
        patch.object(
            chat_pipeline_service,
            "analyze_agent_intent",
            return_value=HANDOFF_DECISION,
        ),
        patch.object(
            chat_pipeline_service,
            "build_safe_agent_action_payload",
            return_value={"safe": True},
        ),
        patch.object(
            chat_pipeline_service,
            "get_bot_by_id",
            return_value=chatbot,
        ),
        patch.object(
            chat_pipeline_service,
            "save_agent_action",
            return_value={"id": 501},
        ),
        patch.object(
            chat_pipeline_service,
            "create_crm_lead_from_agent_signal",
            side_effect=crm_side_effect,
        ),
        patch(
            "app.services.email_service.send_handoff_notification_email",
        ),
    )


def test_handoff_attempts_staff_attention_lead_and_still_pauses_ai():
    patches = _handoff_pipeline_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7] as create_lead, patches[8] as send_email:
        result = chat_pipeline_service.prepare_chat_prompt(
            "I need a human",
            "customer-1",
            29,
            source_channel="whatsapp",
        )

    create_lead.assert_called_once_with(
        chatbot_id=29,
        conversation=CONVERSATION,
        intent="handoff_request",
        suggested_action="request_handoff",
        reason="Customer requested a person.",
    )
    send_email.assert_called_once_with(
        company_id=42,
        conversation=CONVERSATION,
        chatbot_id=29,
    )
    assert result["intent"] == "handoff_request"
    assert result["prompt"] is None
    assert "transferring" in result["direct_reply"]


def test_handoff_crm_failure_is_logged_and_does_not_block_pause_response(caplog):
    patches = _handoff_pipeline_patches(
        crm_side_effect=RuntimeError("database unavailable"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
        result = chat_pipeline_service.prepare_chat_prompt(
            "Please transfer me",
            "customer-1",
            29,
            source_channel="whatsapp",
        )

    assert result["intent"] == "handoff_request"
    assert result["prompt"] is None
    assert "lead creation failed" in caplog.text


def test_handoff_missing_authoritative_ownership_never_uses_conversation_company(
    caplog,
):
    patches = _handoff_pipeline_patches(chatbot={})

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8] as send_email:
        result = chat_pipeline_service.prepare_chat_prompt(
            "Please transfer me",
            "customer-1",
            29,
            source_channel="whatsapp",
        )

    assert result["intent"] == "handoff_request"
    send_email.assert_not_called()
    assert "Authoritative chatbot ownership could not be resolved" in caplog.text
