import logging

from app.database.bot_repository import get_bot_by_id
from app.database.crm_lead_repository import (
    create_crm_lead,
    get_open_crm_lead_by_conversation,
    update_crm_lead_signal,
)


CRM_SIGNAL_RULES = {
    "lead_interest": {
        "lead_type": "follow_up",
        "priority": "medium",
        "summary": "Customer may need business follow-up or further assistance.",
    },
    "handoff_request": {
        "lead_type": "staff_attention",
        "priority": "high",
        "summary": "Customer requested or may need help from a team member.",
    },
    "complaint": {
        "lead_type": "negative_feedback",
        "priority": "high",
        "summary": "Customer message may contain dissatisfaction or service issues.",
    },
}

PRIORITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}

SIGNAL_SEVERITY_RANK = {
    "follow_up": 1,
    "staff_attention": 2,
    "negative_feedback": 3,
}


def _priority_rank(priority):
    return PRIORITY_RANK.get((priority or "").lower(), 0)


def _signal_severity_rank(lead_type):
    return SIGNAL_SEVERITY_RANK.get((lead_type or "").lower(), 0)


def _resolve_company_id(company_id, chatbot_id):
    if company_id:
        return company_id

    bot = get_bot_by_id(chatbot_id)
    return bot.get("company_id") if bot else None


def create_crm_lead_from_agent_signal(
    company_id,
    chatbot_id,
    conversation,
    intent,
    suggested_action=None,
    reason="",
):
    rule = CRM_SIGNAL_RULES.get(intent)

    if not rule:
        logging.info("[CRM] Skipped lead creation for intent=%s", intent)
        return None

    conversation = conversation or {}
    conversation_id = conversation.get("id")
    resolved_company_id = _resolve_company_id(company_id, chatbot_id)

    if not resolved_company_id:
        logging.warning("[CRM] Skipped lead creation because company_id was unavailable chatbot_id=%s", chatbot_id)
        return None

    existing = get_open_crm_lead_by_conversation(chatbot_id, conversation_id)

    if existing:
        update_fields = {}
        new_priority_rank = _priority_rank(rule["priority"])
        existing_priority_rank = _priority_rank(existing.get("priority"))
        new_signal_rank = _signal_severity_rank(rule["lead_type"])
        existing_signal_rank = _signal_severity_rank(existing.get("lead_type"))

        if (
            new_priority_rank > existing_priority_rank
            or (
                new_priority_rank == existing_priority_rank
                and new_signal_rank > existing_signal_rank
            )
        ):
            update_fields = {
                "lead_type": rule["lead_type"],
                "priority": rule["priority"],
                "summary": rule["summary"],
            }

        updated = update_crm_lead_signal(existing["id"], **update_fields)
        logging.info(
            "[CRM] Updated open lead id=%s chatbot_id=%s conversation_id=%s",
            existing.get("id"),
            chatbot_id,
            conversation_id,
        )
        return updated

    lead = create_crm_lead(
        company_id=resolved_company_id,
        chatbot_id=chatbot_id,
        conversation_id=conversation_id,
        customer_phone=conversation.get("customer_phone"),
        customer_name=conversation.get("customer_name") or "",
        source_channel=conversation.get("source_channel"),
        lead_type=rule["lead_type"],
        status="new",
        priority=rule["priority"],
        summary=rule["summary"],
        notes="",
    )

    logging.info(
        "[CRM] Created lead chatbot_id=%s conversation_id=%s lead_type=%s",
        chatbot_id,
        conversation_id,
        rule["lead_type"],
    )
    return lead
