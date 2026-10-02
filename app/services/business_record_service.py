"""Business audit records. Language-model observations never establish success.

Only authoritative application services call record_service_outcome after their
business operation commits. This module is deliberately not an HTTP/model tool.
"""
from app.database import analysis_repository as repository


def record_observation(*, company_id, chatbot_id, conversation_id, event_key,
                       action_type, status="intent", evidence_message_ids=None, details=None,
                       actor_user_id=None):
    if status not in {"intent", "requested"}:
        raise ValueError("An observation cannot confirm or complete a business operation")
    return repository.record_business_event(company_id=company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, actor_user_id=actor_user_id, event_key=event_key,
        action_type=action_type, status=status, source="observation",
        evidence_message_ids=evidence_message_ids, details=details)


def record_service_outcome(*, company_id, chatbot_id, conversation_id, event_key,
                           action_type, status, record_id, evidence_message_ids=None,
                           details=None, actor_user_id=None):
    """Use a server-owned record ID and verified result, never model confirmed=true.

    Failure propagates so the owning service can durably retry the audit write
    with event_key; callers must not report an audit record as saved on error.
    """
    if status not in {"requested", "confirmed", "completed", "failed", "cancelled", "rescheduled"}:
        raise ValueError("Invalid authoritative business outcome")
    return repository.record_business_event(company_id=company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, actor_user_id=actor_user_id, event_key=event_key,
        action_type=action_type, status=status, source="business_service", record_id=record_id,
        evidence_message_ids=evidence_message_ids, details=details)
