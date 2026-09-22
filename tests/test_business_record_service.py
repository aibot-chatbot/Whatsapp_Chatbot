from unittest.mock import Mock

import pytest

from app.services import business_record_service as service


def test_model_cannot_record_authoritative_success(monkeypatch):
    record = Mock()
    monkeypatch.setattr(service.repository, "record_business_event", record)
    with pytest.raises(ValueError):
        service.record_observation(company_id=10, chatbot_id=7, conversation_id=8,
            event_key="event-1", action_type="booking", status="confirmed",
            evidence_message_ids=[9])
    record.assert_not_called()


def test_actorless_customer_event_still_carries_full_scope(monkeypatch):
    record = Mock(return_value={"id": 1})
    monkeypatch.setattr(service.repository, "record_business_event", record)
    service.record_observation(company_id=10, chatbot_id=7, conversation_id=8,
        event_key="event-1", action_type="booking", status="intent", evidence_message_ids=[9])
    args = record.call_args.kwargs
    assert args["company_id"] == 10 and args["chatbot_id"] == 7
    assert args["conversation_id"] == 8 and args["actor_user_id"] is None
    assert args["source"] == "observation"


def test_service_result_requires_server_owned_entity_and_preserves_failure(monkeypatch):
    record = Mock(side_effect=service.repository.AnalysisUnavailable("Storage unavailable"))
    monkeypatch.setattr(service.repository, "record_business_event", record)
    with pytest.raises(service.repository.AnalysisUnavailable):
        service.record_service_outcome(company_id=10, chatbot_id=7, conversation_id=8,
            event_key="booking:b1:confirmed", action_type="booking", status="confirmed", record_id="b1")
    assert record.call_args.kwargs["source"] == "business_service"
    assert record.call_args.kwargs["record_id"] == "b1"


@pytest.mark.parametrize("status", ["confirmed", "completed", "failed", "cancelled", "rescheduled"])
def test_observation_cannot_invent_business_outcome(status):
    with pytest.raises(ValueError):
        service.record_observation(company_id=10, chatbot_id=7, conversation_id=8,
            event_key="e1", action_type="booking", status=status, evidence_message_ids=[9])
