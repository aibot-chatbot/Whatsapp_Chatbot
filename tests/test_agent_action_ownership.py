"""Tenant-ownership regression tests for agent action persistence."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.database.agent_action_repository import save_agent_action
from app.services import chat_pipeline_service


AGENT_DECISION = {
    "intent": "lead_interest",
    "suggested_action": "create_lead",
    "confidence": 0.87,
    "reason": "Customer requested pricing details.",
}
SAFE_PAYLOAD = {"intent": "lead_interest", "safe": True}


@pytest.mark.parametrize("source_channel", ["whatsapp", "wasender", "telegram", "web"])
def test_shared_pipeline_saves_action_with_authoritative_chatbot_company(
    source_channel,
):
    conversation = {
        "id": 101,
        "company_id": 999,
        "chatbot_id": 29,
    }
    with patch.object(
        chat_pipeline_service,
        "get_or_create_conversation",
        return_value=conversation,
    ) as get_conversation, patch.object(
        chat_pipeline_service,
        "get_recent_chat_history",
        return_value=[],
    ), patch(
        "app.database.agent_action_repository.is_conversation_escalated",
        return_value=False,
    ), patch.object(
        chat_pipeline_service,
        "analyze_agent_intent",
        return_value=AGENT_DECISION,
    ), patch.object(
        chat_pipeline_service,
        "build_safe_agent_action_payload",
        return_value=SAFE_PAYLOAD,
    ), patch.object(
        chat_pipeline_service,
        "get_bot_by_id",
        return_value={"id": 29, "company_id": 42},
    ) as get_bot, patch.object(
        chat_pipeline_service,
        "save_agent_action",
    ) as save_action, patch.object(
        chat_pipeline_service,
        "create_crm_lead_from_agent_signal",
    ), patch.object(
        chat_pipeline_service,
        "detect_intent",
        return_value="greeting",
    ), patch.object(
        chat_pipeline_service,
        "handle_greeting",
        return_value="Hello",
    ):
        result = chat_pipeline_service.prepare_chat_prompt(
            "Hi",
            "customer-1",
            29,
            source_channel=source_channel,
        )

    assert result == {
        "direct_reply": "Hello",
        "prompt": None,
        "intent": "greeting",
    }
    get_conversation.assert_called_once_with(
        chatbot_id=29,
        customer_phone="customer-1",
        customer_name=None,
        source_channel=source_channel,
    )
    get_bot.assert_called_once_with(29)
    save_action.assert_called_once_with(
        company_id=42,
        chatbot_id=29,
        conversation_id=101,
        intent="lead_interest",
        action_type="create_lead",
        confidence=0.87,
        reason="Customer requested pricing details.",
        payload=SAFE_PAYLOAD,
    )


@pytest.mark.parametrize(
    "chatbot_record",
    [
        None,
        {"id": 29, "company_id": None},
        {"id": 30, "company_id": 42},
    ],
)
def test_missing_or_mismatched_authoritative_ownership_skips_action_insert(
    chatbot_record,
    caplog,
):
    with patch.object(
        chat_pipeline_service,
        "get_or_create_conversation",
        return_value={"id": 101, "company_id": 999, "chatbot_id": 29},
    ), patch.object(
        chat_pipeline_service,
        "get_recent_chat_history",
        return_value=[],
    ), patch(
        "app.database.agent_action_repository.is_conversation_escalated",
        return_value=False,
    ), patch.object(
        chat_pipeline_service,
        "analyze_agent_intent",
        return_value=AGENT_DECISION,
    ), patch.object(
        chat_pipeline_service,
        "get_bot_by_id",
        return_value=chatbot_record,
    ), patch.object(
        chat_pipeline_service,
        "save_agent_action",
    ) as save_action, patch.object(
        chat_pipeline_service,
        "create_crm_lead_from_agent_signal",
    ), patch.object(
        chat_pipeline_service,
        "detect_intent",
        return_value="greeting",
    ), patch.object(
        chat_pipeline_service,
        "handle_greeting",
        return_value="Hello",
    ):
        result = chat_pipeline_service.prepare_chat_prompt(
            "Hi",
            "customer-1",
            29,
            source_channel="whatsapp",
        )

    assert result["direct_reply"] == "Hello"
    assert "Authoritative chatbot ownership could not be resolved" in caplog.text
    save_action.assert_not_called()


def test_repository_preserves_action_fields_with_required_company_ownership():
    inserted_row = {"id": 501}
    response = MagicMock(data=[inserted_row])

    with patch(
        "app.database.agent_action_repository.supabase",
    ) as supabase:
        supabase.table.return_value.insert.return_value.execute.return_value = response
        result = save_agent_action(
            company_id=42,
            chatbot_id=29,
            conversation_id=101,
            message_id=202,
            intent="complaint",
            action_type="request_handoff",
            confidence=0.73,
            reason="Customer asked for a supervisor.",
            payload={"safe": True},
        )

    assert result == inserted_row
    supabase.table.assert_called_once_with("agent_actions")
    supabase.table.return_value.insert.assert_called_once_with({
        "company_id": 42,
        "chatbot_id": 29,
        "conversation_id": 101,
        "message_id": 202,
        "action_type": "request_handoff",
        "intent": "complaint",
        "status": "detected",
        "confidence": 0.73,
        "reason": "Customer asked for a supervisor.",
        "payload": {"safe": True},
    })


@pytest.mark.parametrize("company_id", [None, 0, -1, True, "42"])
def test_repository_rejects_missing_or_invalid_company_before_insert(company_id):
    with patch(
        "app.database.agent_action_repository.supabase",
    ) as supabase, pytest.raises(
        ValueError,
        match="company_id is required",
    ):
        save_agent_action(
            company_id=company_id,
            chatbot_id=29,
            intent="lead_interest",
        )

    supabase.table.assert_not_called()


def test_agent_action_creation_has_only_one_shared_pipeline_caller():
    channel_paths = [
        Path("app/utils/whatsapp_utils.py"),
        Path("app/utils/telegram_utils.py"),
        Path("app/services/wasender_service.py"),
        Path("app/routes/chat_routes.py"),
        Path("app/routes/testbot_routes.py"),
        Path("app/services/ai_router.py"),
        Path("app/services/deepseek_service.py"),
    ]

    assert all(
        b"save_agent_action(" not in path.read_bytes()
        for path in channel_paths
    )
    assert (
        Path("app/services/chat_pipeline_service.py")
        .read_bytes()
        .count(b"save_agent_action(")
        == 1
    )
