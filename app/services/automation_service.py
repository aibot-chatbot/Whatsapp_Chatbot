import logging

from app.database.automation_event_repository import (
    create_automation_event,
    get_automation_event_by_key,
    list_automation_events,
    update_automation_event_status,
)


logger = logging.getLogger(__name__)
from app.database.crm_lead_repository import (
    normalize_crm_lead_status,
    get_crm_lead_by_id,
    transition_crm_lead_stage,
)
from app.services.langflow_decision import (
    crm_stage_decision,
    knowledge_document_decision,
)


CRM_STAGE_TRANSITIONS = {
    "new": {"contacted", "qualified", "lost"},
    "contacted": {"qualified", "won", "lost"},
    "qualified": {"won", "lost"},
    "won": set(),
    "lost": set(),
}


def _positive_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def schedule_knowledge_document_follow_up(
    *, company_id, chatbot_id, file_id, display_name, chunk_count, target_role="primary"
):
    _positive_int(company_id, "company_id")
    _positive_int(chatbot_id, "chatbot_id")
    _positive_int(file_id, "file_id")
    _positive_int(chunk_count, "chunk_count")
    if target_role not in {"primary", "supporting"}:
        raise ValueError("target_role must be primary or supporting")

    safe_name = str(display_name or "knowledge document").strip()[:200]

    # Enrichment only. The contract fixes this flow's decision to
    # "review_document", so it cannot change whether a review is queued - it
    # just adds a reviewer-facing summary when Langflow is available.
    decision = knowledge_document_decision(
        company_id=company_id,
        chatbot_id=chatbot_id,
        file_id=file_id,
        display_name=safe_name,
        chunk_count=chunk_count,
        target_role=target_role,
    )

    automation = {
        "consulted": decision["consulted"],
        "correlation_id": decision["correlation_id"],
    }
    if decision["consulted"]:
        automation["summary"] = decision.get("summary", "")
    elif decision["detail"]:
        automation["skipped_because"] = decision["detail"]

    return create_automation_event(
        company_id=company_id,
        chatbot_id=chatbot_id,
        event_type="knowledge_document_follow_up",
        idempotency_key=f"knowledge:{file_id}:completed",
        payload={
            "file_id": file_id,
            "display_name": safe_name,
            "chunk_count": chunk_count,
            "target_role": target_role,
            "requires_review": True,
            "automation": automation,
        },
    )


def apply_crm_stage_automation(
    *, company_id, chatbot_id, lead_id, target_status, reason="", idempotency_key=None
):
    _positive_int(company_id, "company_id")
    _positive_int(chatbot_id, "chatbot_id")
    _positive_int(lead_id, "lead_id")

    target = normalize_crm_lead_status(target_status)
    if target not in CRM_STAGE_TRANSITIONS:
        raise ValueError("Unsupported CRM stage")

    lead = get_crm_lead_by_id(lead_id, chatbot_id, company_id)
    if not lead:
        raise LookupError("CRM lead not found")

    raw_current = str(lead.get("status") or "").strip().lower()
    current = normalize_crm_lead_status(raw_current)
    if current == target:
        return {"changed": False, "lead": lead, "event": None}
    if target not in CRM_STAGE_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid CRM stage transition: {current} -> {target}")

    # Advisory second opinion. The allowlist above stays the primary authority:
    # Langflow may refuse a transition Flask allows, but can never permit one
    # Flask rejects, and any Langflow failure leaves the decision with Flask
    # rather than blocking a user-facing action.
    decision = crm_stage_decision(
        company_id=company_id,
        chatbot_id=chatbot_id,
        lead_id=lead_id,
        current_status=current,
        target_status=target,
        reason=reason,
    )

    supplied_key = str(idempotency_key or "").strip()[:80]
    event_key = f"crm:{lead_id}:{current}:{target}:{supplied_key}" if supplied_key else f"crm:{lead_id}:{current}:{target}"
    try:
        existing = get_automation_event_by_key(company_id, event_key)
    except Exception as exc:
        # Event persistence is optional until migration 049 is applied. Keep
        # the CRM transition fail-open and surface the loss through health.
        logger.warning("Automation event lookup unavailable: %s", exc)
        existing = None
    if existing:
        return {"changed": False, "lead": lead, "event": existing}

    automation = {
        "consulted": decision["consulted"],
        "correlation_id": decision["correlation_id"],
    }
    if decision["detail"]:
        automation["skipped_because"] = decision["detail"]

    if decision["blocked"]:
        try:
            create_automation_event(
                company_id=company_id,
                chatbot_id=chatbot_id,
                event_type="crm_stage_transition",
                idempotency_key=event_key,
                status="blocked",
                payload={
                    "lead_id": lead_id,
                    "from_status": current,
                    "to_status": target,
                    "reason": decision["reason"],
                    "automation": automation,
                },
            )
        except Exception as exc:
            logger.warning("Unable to record blocked automation event: %s", exc)
        raise PermissionError(
            decision["reason"] or "Automation policy blocked this stage transition"
        )

    try:
        event = create_automation_event(
            company_id=company_id,
            chatbot_id=chatbot_id,
            event_type="crm_stage_transition",
            idempotency_key=event_key,
            payload={
                "lead_id": lead_id,
                "from_status": current,
                "to_status": target,
                "reason": str(reason or "").strip()[:500],
                "automation": automation,
            },
        )
    except Exception as exc:
        logger.warning("Unable to record CRM automation event: %s", exc)
        event = None

    updated = transition_crm_lead_stage(
        lead_id=lead_id,
        company_id=company_id,
        chatbot_id=chatbot_id,
        from_status=raw_current,
        to_status=target,
    )
    if not updated:
        if event:
            try:
                update_automation_event_status(
                    company_id=company_id,
                    chatbot_id=chatbot_id,
                    event_id=event["id"],
                    status="failed",
                    error_message="Lead stage changed before automation could apply the compare-and-set update.",
                )
            except Exception as exc:
                logger.warning("Unable to record failed automation event: %s", exc)
        raise RuntimeError("CRM lead stage update was not applied")

    completed_event = None
    if event:
        try:
            completed_event = update_automation_event_status(
                company_id=company_id,
                chatbot_id=chatbot_id,
                event_id=event["id"],
                status="completed",
                result={"lead_id": lead_id, "from_status": current, "to_status": target},
            )
        except Exception as exc:
            logger.warning("Unable to complete automation event: %s", exc)
    return {"changed": True, "lead": updated, "event": completed_event or event}
