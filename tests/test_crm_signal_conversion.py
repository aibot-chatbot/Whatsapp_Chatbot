"""CRM signal conversion correctness, ownership, and conflict recovery tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.database import crm_lead_repository
from app.services.crm_lead_service import create_crm_lead_from_agent_signal


BOT = {"id": 29, "company_id": 42}
CONVERSATION = {
    "id": 101,
    "chatbot_id": 29,
    "customer_phone": "+60123456789",
    "customer_name": "Database Customer",
    "source_channel": "whatsapp",
}
OPEN_LEAD = {
    "id": 7,
    "company_id": 42,
    "chatbot_id": 29,
    "conversation_id": 101,
    "lead_type": "follow_up",
    "priority": "medium",
    "status": "new",
}


class _UniqueViolation(Exception):
    code = "23505"


def test_automatic_conversion_derives_company_and_conversation_from_database():
    caller_conversation = {
        **CONVERSATION,
        "company_id": 999,
        "customer_name": "Caller Supplied Name",
    }
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
        return_value=BOT,
    ), patch(
        "app.services.crm_lead_service.get_conversation_by_id_and_chatbot",
        return_value=CONVERSATION,
    ) as get_conversation, patch(
        "app.services.crm_lead_service.get_open_crm_lead_by_conversation",
        return_value=None,
    ), patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
        return_value=(OPEN_LEAD, True),
    ) as create_lead:
        result = create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=caller_conversation,
            intent="lead_interest",
        )

    assert result == OPEN_LEAD
    get_conversation.assert_called_once_with(101, 29)
    create_lead.assert_called_once_with(
        company_id=42,
        chatbot_id=29,
        conversation_id=101,
        customer_phone="+60123456789",
        customer_name="Database Customer",
        source_channel="whatsapp",
        lead_type="follow_up",
        status="new",
        priority="medium",
        summary="Customer may need business follow-up or further assistance.",
        notes="",
    )


@pytest.mark.parametrize(
    "chatbot",
    [
        None,
        {"id": 30, "company_id": 42},
        {"id": 29, "company_id": None},
        {"id": 29, "company_id": 0},
        {"id": 29, "company_id": "42"},
    ],
)
def test_automatic_conversion_rejects_missing_or_invalid_chatbot_ownership(
    chatbot,
):
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
        return_value=chatbot,
    ), patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
    ) as create_lead, pytest.raises(
        ValueError,
        match="Authoritative chatbot ownership could not be resolved",
    ):
        create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=CONVERSATION,
            intent="lead_interest",
        )

    create_lead.assert_not_called()


def test_automatic_conversion_rejects_missing_authoritative_conversation():
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
        return_value=BOT,
    ), patch(
        "app.services.crm_lead_service.get_conversation_by_id_and_chatbot",
        return_value=None,
    ), patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
    ) as create_lead, pytest.raises(
        ValueError,
        match="Authoritative conversation ownership could not be resolved",
    ):
        create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=CONVERSATION,
            intent="complaint",
        )

    create_lead.assert_not_called()


def test_handoff_request_creates_staff_attention_lead():
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
        return_value=BOT,
    ), patch(
        "app.services.crm_lead_service.get_conversation_by_id_and_chatbot",
        return_value=CONVERSATION,
    ), patch(
        "app.services.crm_lead_service.get_open_crm_lead_by_conversation",
        return_value=None,
    ), patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
        return_value=({**OPEN_LEAD, "lead_type": "staff_attention"}, True),
    ) as create_lead:
        create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=CONVERSATION,
            intent="handoff_request",
        )

    assert create_lead.call_args.kwargs["lead_type"] == "staff_attention"
    assert create_lead.call_args.kwargs["priority"] == "high"


def test_knowledge_gap_does_not_create_a_crm_lead():
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
    ) as get_bot, patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
    ) as create_lead:
        result = create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=CONVERSATION,
            intent="knowledge_gap",
        )

    assert result is None
    get_bot.assert_not_called()
    create_lead.assert_not_called()


def test_existing_open_lead_is_reused_and_deterministically_escalated():
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
        return_value=BOT,
    ), patch(
        "app.services.crm_lead_service.get_conversation_by_id_and_chatbot",
        return_value=CONVERSATION,
    ), patch(
        "app.services.crm_lead_service.get_open_crm_lead_by_conversation",
        return_value=OPEN_LEAD,
    ), patch(
        "app.services.crm_lead_service.update_crm_lead_signal",
        return_value={**OPEN_LEAD, "lead_type": "negative_feedback", "priority": "high"},
    ) as update_lead, patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
    ) as create_lead:
        result = create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=CONVERSATION,
            intent="complaint",
        )

    assert result["lead_type"] == "negative_feedback"
    update_lead.assert_called_once_with(
        7,
        chatbot_id=29,
        company_id=42,
        lead_type="negative_feedback",
        priority="high",
        summary="Customer message may contain dissatisfaction or service issues.",
    )
    create_lead.assert_not_called()


def test_automatic_conversion_escalates_concurrently_created_winner():
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
        return_value=BOT,
    ), patch(
        "app.services.crm_lead_service.get_conversation_by_id_and_chatbot",
        return_value=CONVERSATION,
    ), patch(
        "app.services.crm_lead_service.get_open_crm_lead_by_conversation",
        return_value=None,
    ), patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
        return_value=(OPEN_LEAD, False),
    ), patch(
        "app.services.crm_lead_service.update_crm_lead_signal",
        return_value={**OPEN_LEAD, "lead_type": "negative_feedback", "priority": "high"},
    ) as update_lead:
        result = create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=CONVERSATION,
            intent="complaint",
        )

    assert result["lead_type"] == "negative_feedback"
    update_lead.assert_called_once_with(
        7,
        chatbot_id=29,
        company_id=42,
        lead_type="negative_feedback",
        priority="high",
        summary="Customer message may contain dissatisfaction or service issues.",
    )


def test_automatic_conversion_keeps_closed_lead_historical_and_creates_open_lead():
    closed_lead = {**OPEN_LEAD, "id": 6, "status": "closed"}
    created_lead = {**OPEN_LEAD, "id": 8, "status": "new"}
    with patch(
        "app.services.crm_lead_service.get_bot_by_id",
        return_value=BOT,
    ), patch(
        "app.services.crm_lead_service.get_conversation_by_id_and_chatbot",
        return_value=CONVERSATION,
    ), patch(
        "app.services.crm_lead_service.get_open_crm_lead_by_conversation",
        return_value=None,
    ), patch(
        "app.database.crm_lead_repository.get_crm_lead_by_conversation",
        return_value=closed_lead,
    ) as get_latest_any_status, patch(
        "app.services.crm_lead_service.update_crm_lead_signal",
    ) as update_lead, patch(
        "app.services.crm_lead_service.create_crm_lead_with_open_conflict_recovery",
        return_value=(created_lead, True),
    ) as create_lead:
        result = create_crm_lead_from_agent_signal(
            chatbot_id=29,
            conversation=CONVERSATION,
            intent="lead_interest",
        )

    assert result == created_lead
    get_latest_any_status.assert_not_called()
    update_lead.assert_not_called()
    create_lead.assert_called_once()


def test_unique_conflict_returns_the_winning_open_lead():
    with patch(
        "app.database.crm_lead_repository.create_crm_lead",
        side_effect=_UniqueViolation(),
    ), patch(
        "app.database.crm_lead_repository.get_open_crm_lead_by_conversation",
        return_value=OPEN_LEAD,
    ) as get_winner:
        lead, created = crm_lead_repository.create_crm_lead_with_open_conflict_recovery(
            company_id=42,
            chatbot_id=29,
            conversation_id=101,
        )

    assert lead == OPEN_LEAD
    assert created is False
    get_winner.assert_called_once_with(29, 101, company_id=42)


def test_unique_conflict_fails_clearly_when_winner_cannot_be_loaded():
    with patch(
        "app.database.crm_lead_repository.create_crm_lead",
        side_effect=_UniqueViolation(),
    ), patch(
        "app.database.crm_lead_repository.get_open_crm_lead_by_conversation",
        return_value=None,
    ), pytest.raises(
        RuntimeError,
        match="winning lead could not be loaded",
    ):
        crm_lead_repository.create_crm_lead_with_open_conflict_recovery(
            company_id=42,
            chatbot_id=29,
            conversation_id=101,
        )


def test_null_conversation_does_not_treat_unique_error_as_open_lead_conflict():
    error = _UniqueViolation()
    with patch(
        "app.database.crm_lead_repository.create_crm_lead",
        side_effect=error,
    ), patch(
        "app.database.crm_lead_repository.get_open_crm_lead_by_conversation",
    ) as get_winner, pytest.raises(_UniqueViolation):
        crm_lead_repository.create_crm_lead_with_open_conflict_recovery(
            company_id=42,
            chatbot_id=29,
            conversation_id=None,
        )

    get_winner.assert_not_called()


def test_unstructured_insert_error_is_not_misclassified_as_unique_conflict():
    error = RuntimeError("duplicate key value violates unique constraint")
    with patch(
        "app.database.crm_lead_repository.create_crm_lead",
        side_effect=error,
    ), patch(
        "app.database.crm_lead_repository.get_open_crm_lead_by_conversation",
    ) as get_winner, pytest.raises(RuntimeError) as raised:
        crm_lead_repository.create_crm_lead_with_open_conflict_recovery(
            company_id=42,
            chatbot_id=29,
            conversation_id=101,
        )

    assert raised.value is error
    get_winner.assert_not_called()


def test_manual_upsert_does_not_reopen_a_closed_lead():
    created_lead = {**OPEN_LEAD, "id": 8}
    final_lead = {
        **created_lead,
        "customer_phone": "***6789",
        "customer_name": "Database Customer",
        "source_channel": "whatsapp",
        "summary": "",
        "notes": "",
        "assigned_to": "",
        "follow_up_date": None,
        "created_at": None,
        "updated_at": None,
    }
    with patch(
        "app.database.crm_lead_repository.get_open_crm_lead_by_conversation",
        return_value=None,
    ), patch(
        "app.database.crm_lead_repository.get_crm_lead_by_conversation",
    ) as get_latest_any_status, patch(
        "app.database.crm_lead_repository.create_crm_lead_with_open_conflict_recovery",
        return_value=(created_lead, True),
    ) as create_lead, patch(
        "app.database.crm_lead_repository.update_crm_lead_status_notes",
        return_value=final_lead,
    ):
        result = crm_lead_repository.upsert_crm_lead_by_conversation(
            company_id=42,
            chatbot_id=29,
            conversation_id=101,
            customer_phone="+60123456789",
            customer_name="Database Customer",
            source_channel="whatsapp",
        )

    assert result["id"] == 8
    get_latest_any_status.assert_not_called()
    create_lead.assert_called_once()


def test_manual_upsert_reuses_an_existing_open_lead():
    updated = {
        **OPEN_LEAD,
        "customer_phone": "+60123456789",
        "customer_name": "Database Customer",
        "source_channel": "whatsapp",
        "summary": "Existing summary",
        "notes": "Updated notes",
        "assigned_to": "",
        "follow_up_date": None,
        "created_at": None,
        "updated_at": "2026-07-27T00:00:00+00:00",
    }
    supabase = MagicMock()
    (
        supabase.table.return_value
        .update.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[updated])

    with patch(
        "app.database.crm_lead_repository.get_open_crm_lead_by_conversation",
        return_value=OPEN_LEAD,
    ) as get_open, patch(
        "app.database.crm_lead_repository.create_crm_lead_with_open_conflict_recovery",
    ) as create_lead, patch(
        "app.database.crm_lead_repository.supabase",
        supabase,
    ):
        result = crm_lead_repository.upsert_crm_lead_by_conversation(
            company_id=42,
            chatbot_id=29,
            conversation_id=101,
            customer_phone="+60123456789",
            customer_name="Database Customer",
            source_channel="whatsapp",
            notes="Updated notes",
        )

    assert result["id"] == 7
    get_open.assert_called_once_with(29, 101, company_id=42)
    create_lead.assert_not_called()
