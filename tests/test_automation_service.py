from unittest.mock import ANY, patch

import pytest

from app.services.automation_service import (
    apply_crm_stage_automation,
    schedule_knowledge_document_follow_up,
)


@pytest.fixture(autouse=True)
def _langflow_offline(monkeypatch):
    """Keep these unit tests off the network.

    The service now consults Langflow advisorily. Without this the suite would
    make a real HTTP call and its result would depend on whether a local
    Langflow happens to be running - the decision layer's own fail-open
    behaviour is covered in test_langflow_decision.py instead.
    """
    monkeypatch.delenv("LANGFLOW_CRM_FLOW_ID", raising=False)
    monkeypatch.delenv("LANGFLOW_KNOWLEDGE_FLOW_ID", raising=False)


def test_knowledge_document_follow_up_is_idempotent_and_tenant_scoped():
    event = {
        "id": 11,
        "company_id": 42,
        "chatbot_id": 7,
        "event_type": "knowledge_document_follow_up",
        "idempotency_key": "knowledge:99:completed",
        "status": "queued",
    }

    with patch(
        "app.services.automation_service.create_automation_event",
        return_value=event,
    ) as create_event:
        result = schedule_knowledge_document_follow_up(
            company_id=42,
            chatbot_id=7,
            file_id=99,
            display_name="policy.pdf",
            chunk_count=12,
            target_role="supporting",
        )

    assert result == event
    create_event.assert_called_once_with(
        company_id=42,
        chatbot_id=7,
        event_type="knowledge_document_follow_up",
        idempotency_key="knowledge:99:completed",
        payload={
            "file_id": 99,
            "display_name": "policy.pdf",
            "chunk_count": 12,
            "target_role": "supporting",
            "requires_review": True,
            # Advisory enrichment: the review is queued either way, and the
            # event records why Langflow did not contribute a summary.
            "automation": {
                "consulted": False,
                "correlation_id": ANY,
                "skipped_because": "LANGFLOW_KNOWLEDGE_FLOW_ID is not configured",
            },
        },
    )


def test_knowledge_document_follow_up_rejects_empty_ingest():
    with pytest.raises(ValueError, match="chunk_count"):
        schedule_knowledge_document_follow_up(
            company_id=42,
            chatbot_id=7,
            file_id=99,
            display_name="policy.pdf",
            chunk_count=0,
        )


def test_crm_stage_automation_allows_only_forward_or_terminal_transition():
    lead = {"id": 5, "company_id": 42, "chatbot_id": 7, "status": "contacted"}
    updated = {**lead, "status": "qualified"}
    event = {"id": 12, "event_type": "crm_stage_transition", "status": "completed"}

    with patch(
        "app.services.automation_service.get_crm_lead_by_id",
        return_value=lead,
    ), patch(
        "app.services.automation_service.transition_crm_lead_stage",
        return_value=updated,
    ) as transition, patch(
        "app.services.automation_service.get_automation_event_by_key",
        return_value=None,
    ), patch(
        "app.services.automation_service.create_automation_event",
        return_value=event,
    ) as create_event, patch(
        "app.services.automation_service.update_automation_event_status",
        return_value=event,
    ):
        result = apply_crm_stage_automation(
            company_id=42,
            chatbot_id=7,
            lead_id=5,
            target_status="qualified",
            reason="Document follow-up confirmed buying intent.",
        )

    assert result == {"changed": True, "lead": updated, "event": event}
    transition.assert_called_once_with(
        lead_id=5,
        company_id=42,
        chatbot_id=7,
        from_status="contacted",
        to_status="qualified",
    )
    create_event.assert_called_once()
    assert create_event.call_args.kwargs["payload"] == {
        "lead_id": 5,
        "from_status": "contacted",
        "to_status": "qualified",
        "reason": "Document follow-up confirmed buying intent.",
        "automation": {
            "consulted": False,
            "correlation_id": ANY,
            "skipped_because": "LANGFLOW_CRM_FLOW_ID is not configured",
        },
    }


def test_crm_stage_automation_rejects_backward_transition():
    with patch(
        "app.services.automation_service.get_crm_lead_by_id",
        return_value={"id": 5, "company_id": 42, "chatbot_id": 7, "status": "qualified"},
    ):
        with pytest.raises(ValueError, match="transition"):
            apply_crm_stage_automation(
                company_id=42,
                chatbot_id=7,
                lead_id=5,
                target_status="new",
            )


def test_crm_stage_automation_blocked_by_langflow_does_not_transition_the_lead():
    """A Langflow refusal must record a blocked event and leave the lead alone.

    This is the whole reason the advisory layer exists. Flask's own allowlist
    already permits contacted -> qualified, so this test is the only place that
    proves a Langflow refusal actually stops the side effect rather than merely
    being reported. The decision-layer tests cover the verdict; nothing covered
    what the service does with it.
    """
    lead = {"id": 5, "company_id": 42, "chatbot_id": 7, "status": "contacted"}
    blocked_event = {"id": 13, "event_type": "crm_stage_transition", "status": "blocked"}
    refusal = {
        "consulted": True,
        "blocked": True,
        "reason": "Duplicate lead already won under another record",
        "detail": "",
        "correlation_id": "corr-block-1",
    }

    with patch(
        "app.services.automation_service.get_crm_lead_by_id", return_value=lead
    ), patch(
        "app.services.automation_service.crm_stage_decision", return_value=refusal
    ), patch(
        "app.services.automation_service.get_automation_event_by_key", return_value=None
    ), patch(
        "app.services.automation_service.create_automation_event",
        return_value=blocked_event,
    ) as create_event, patch(
        "app.services.automation_service.transition_crm_lead_stage"
    ) as transition:
        with pytest.raises(PermissionError, match="Duplicate lead"):
            apply_crm_stage_automation(
                company_id=42,
                chatbot_id=7,
                lead_id=5,
                target_status="qualified",
            )

    # The assertion the suite was missing: the stage must not move.
    transition.assert_not_called()

    create_event.assert_called_once()
    assert create_event.call_args.kwargs["status"] == "blocked"
    assert create_event.call_args.kwargs["payload"] == {
        "lead_id": 5,
        "from_status": "contacted",
        "to_status": "qualified",
        "reason": "Duplicate lead already won under another record",
        "automation": {"consulted": True, "correlation_id": "corr-block-1"},
    }


def test_crm_stage_automation_remains_fail_open_when_event_table_is_unavailable():
    lead = {"id": 5, "company_id": 42, "chatbot_id": 7, "status": "contacted"}
    updated = {**lead, "status": "qualified"}

    with patch(
        "app.services.automation_service.get_crm_lead_by_id", return_value=lead
    ), patch(
        "app.services.automation_service.transition_crm_lead_stage",
        return_value=updated,
    ) as transition, patch(
        "app.services.automation_service.get_automation_event_by_key",
        side_effect=RuntimeError("automation_events table is unavailable"),
    ), patch(
        "app.services.automation_service.create_automation_event",
        side_effect=RuntimeError("automation_events table is unavailable"),
    ), patch(
        "app.services.automation_service.crm_stage_decision",
        return_value={
            "consulted": False,
            "blocked": False,
            "reason": "",
            "detail": "",
            "correlation_id": "corr-1",
        },
    ):
        result = apply_crm_stage_automation(
            company_id=42,
            chatbot_id=7,
            lead_id=5,
            target_status="qualified",
        )

    assert result == {"changed": True, "lead": updated, "event": None}
    transition.assert_called_once()
