import logging

from app.database.bot_repository import get_bot_by_id
from app.database.conversation_repository import get_conversation_by_id_and_chatbot
from app.database.crm_lead_repository import (
    create_crm_lead_with_open_conflict_recovery,
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


def _is_positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _resolve_authoritative_chatbot(chatbot_id):
    bot = get_bot_by_id(chatbot_id)
    if not bot or bot.get("id") != chatbot_id:
        raise ValueError("Authoritative chatbot ownership could not be resolved")

    company_id = bot.get("company_id")
    if not _is_positive_integer(company_id):
        raise ValueError("Authoritative chatbot ownership could not be resolved")

    return bot


def _resolve_authoritative_conversation(conversation, chatbot_id):
    conversation = conversation or {}
    conversation_id = conversation.get("id")
    if not conversation_id:
        return conversation

    authoritative = get_conversation_by_id_and_chatbot(conversation_id, chatbot_id)
    if not authoritative:
        raise ValueError("Authoritative conversation ownership could not be resolved")

    return authoritative


def _update_open_lead_from_rule(lead, rule, chatbot_id, company_id):
    update_fields = {}
    new_priority_rank = _priority_rank(rule["priority"])
    existing_priority_rank = _priority_rank(lead.get("priority"))
    new_signal_rank = _signal_severity_rank(rule["lead_type"])
    existing_signal_rank = _signal_severity_rank(lead.get("lead_type"))

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

    return update_crm_lead_signal(
        lead["id"],
        chatbot_id=chatbot_id,
        company_id=company_id,
        **update_fields,
    )


def create_crm_lead_from_agent_signal(
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

    bot = _resolve_authoritative_chatbot(chatbot_id)
    company_id = bot["company_id"]
    conversation = _resolve_authoritative_conversation(conversation, chatbot_id)
    conversation_id = conversation.get("id")

    existing = get_open_crm_lead_by_conversation(
        chatbot_id,
        conversation_id,
        company_id=company_id,
    )

    if existing:
        updated = _update_open_lead_from_rule(
            existing,
            rule,
            chatbot_id,
            company_id,
        )
        logging.info(
            "[CRM] Updated open lead id=%s chatbot_id=%s conversation_id=%s",
            existing.get("id"),
            chatbot_id,
            conversation_id,
        )
        return updated

    lead, created = create_crm_lead_with_open_conflict_recovery(
        company_id=company_id,
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

    if not created:
        lead = _update_open_lead_from_rule(
            lead,
            rule,
            chatbot_id,
            company_id,
        )
        logging.info(
            "[CRM] Reused concurrently created lead id=%s chatbot_id=%s conversation_id=%s",
            lead.get("id") if lead else None,
            chatbot_id,
            conversation_id,
        )
        return lead

    logging.info(
        "[CRM] Created lead chatbot_id=%s conversation_id=%s lead_type=%s",
        chatbot_id,
        conversation_id,
        rule["lead_type"],
    )
    return lead
