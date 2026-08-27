import logging

from app.database.chat_history_repository import get_recent_chat_history
from app.database.conversation_repository import get_or_create_conversation
from app.database.agent_action_repository import save_agent_action
from app.database.bot_repository import get_bot_by_id
from app.services.chat_logic_service import (
    detect_intent,
    handle_greeting,
    handle_out_of_scope,
    MAX_HISTORY,
)
from app.services.rag_service import retrieve_relevant_chunks, build_prompt
from app.services.workflow_tracker import update_workflow_state
from app.services.agent_decision_service import (
    analyze_agent_intent,
    build_safe_agent_action_payload,
)
from app.services.crm_lead_service import create_crm_lead_from_agent_signal


def _resolve_chatbot_company_id(chatbot_id):
    chatbot = get_bot_by_id(chatbot_id)
    if not chatbot or chatbot.get("id") != chatbot_id:
        raise ValueError("Authoritative chatbot ownership could not be resolved")

    company_id = chatbot.get("company_id")
    if not isinstance(company_id, int) or isinstance(company_id, bool) or company_id <= 0:
        raise ValueError("Authoritative chatbot ownership could not be resolved")

    return company_id


def prepare_chat_prompt(
    message,
    customer_id,
    chatbot_id,
    source_channel="whatsapp",
):
    conversation = get_or_create_conversation(
        chatbot_id=chatbot_id,
        customer_phone=customer_id,
        customer_name=None,
        source_channel=source_channel,
    )

    history = get_recent_chat_history(
        conversation["id"],
        limit=MAX_HISTORY,
    )

    from app.database.agent_action_repository import is_conversation_escalated
    if is_conversation_escalated(conversation["id"], chatbot_id):
        logging.info(f"[ChatPipeline] Conversation {conversation['id']} is currently escalated to human staff. Skipping AI response.")
        return {
            "direct_reply": "<SILENT_BOT_RESPONSE>",
            "prompt": None,
            "intent": "escalated_to_human",
        }

    authoritative_company_id = None

    try:
        agent_decision = analyze_agent_intent(
            message,
            conversation_history=history,
        )
        logging.info(
            "[AgentDecision] chatbot_id=%s intent=%s action=%s confidence=%.2f",
            chatbot_id,
            agent_decision.get("intent"),
            agent_decision.get("suggested_action"),
            agent_decision.get("confidence", 0.0),
        )

        try:
            authoritative_company_id = _resolve_chatbot_company_id(chatbot_id)
            save_agent_action(
                company_id=authoritative_company_id,
                chatbot_id=chatbot_id,
                conversation_id=conversation.get("id"),
                intent=agent_decision.get("intent", "unknown"),
                action_type=agent_decision.get("suggested_action", "none"),
                confidence=agent_decision.get("confidence"),
                reason=agent_decision.get("reason", ""),
                payload=build_safe_agent_action_payload(agent_decision),
            )
        except Exception as e:
            logging.warning(
                "[AgentDecision] save failed for chatbot_id=%s: %s",
                chatbot_id,
                e,
            )

        try:
            create_crm_lead_from_agent_signal(
                chatbot_id=chatbot_id,
                conversation=conversation,
                intent=agent_decision.get("intent", "unknown"),
                suggested_action=agent_decision.get("suggested_action", "none"),
                reason=agent_decision.get("reason", ""),
            )
        except Exception as e:
            logging.warning(
                "[CRM] lead creation failed for chatbot_id=%s conversation_id=%s: %s",
                chatbot_id,
                conversation.get("id"),
                e,
            )

        # Persist what this turn revealed about the customer as conversation-
        # scoped graph nodes, so a later turn can recall it. analyze_agent_intent
        # is pure regex, so these fields are already extracted for free -- this
        # adds no LLM call and no billing change.
        try:
            from app.services import conversation_memory_service

            # Plan gate (data/042 conversation_memory). Resolved through
            # conversation_memory_denial, which returns instead of raising, so
            # a denial cannot be caught below and logged as a store failure --
            # "not on your plan" and "the write broke" must stay distinct.
            memory_denial = conversation_memory_service.conversation_memory_denial(
                chatbot_id
            )
            if memory_denial:
                logging.info(
                    "[ConversationMemory] not stored for chatbot_id=%s "
                    "conversation_id=%s: plan denies conversation memory (code=%s)",
                    chatbot_id,
                    conversation.get("id"),
                    memory_denial,
                )
            else:
                conversation_memory_service.remember_conversation_facts(
                    chatbot_id=chatbot_id,
                    conversation_id=conversation.get("id"),
                    extracted_fields=agent_decision.get("extracted_fields"),
                )
        except Exception as e:
            logging.warning(
                "[ConversationMemory] store failed for chatbot_id=%s conversation_id=%s: %s",
                chatbot_id,
                conversation.get("id"),
                e,
            )

        # Trigger email notification for handoff requests after the CRM attempt
        # so staff-attention lead creation is not skipped by the early return.
        if agent_decision.get("intent") == "handoff_request":
            try:
                if authoritative_company_id is None:
                    raise ValueError(
                        "Authoritative chatbot ownership could not be resolved"
                    )

                from app.services.email_service import send_handoff_notification_email
                send_handoff_notification_email(
                    company_id=authoritative_company_id,
                    conversation=conversation,
                    chatbot_id=chatbot_id
                )
            except Exception as e:
                logging.warning(f"[AgentDecision] failed to send handoff email: {e}")

            return {
                "direct_reply": "I'm transferring you to our Customer Service team now. Please hold on while I connect you. They will be with you shortly! \U0001f60a",
                "prompt": None,
                "intent": "handoff_request",
            }
    except Exception as e:
        logging.warning("[AgentDecision] analysis failed for chatbot_id=%s: %s", chatbot_id, e)

    intent = detect_intent(message)
    logging.info(f"[ChatPipeline] Detected intent: {intent}")

    if intent in ["greeting", "main_menu"]:
        return {
            "direct_reply": handle_greeting(chatbot_id),
            "prompt": None,
            "intent": intent,
        }

    if intent == "out_of_scope":
        return {
            "direct_reply": handle_out_of_scope(chatbot_id),
            "prompt": None,
            "intent": intent,
        }

    update_workflow_state(chatbot_id, "RAG_SEARCH", message, customer_id)

    context_chunks = retrieve_relevant_chunks(
        message,
        chatbot_id=chatbot_id,
        conversation_id=conversation.get("id"),
    )

    logging.info(f"[ChatPipeline] Retrieved chunks: {len(context_chunks)}")

    prompt = build_prompt(
        history,
        message,
        context_chunks,
        chatbot_id=chatbot_id,
    )

    return {
        "direct_reply": None,
        "prompt": prompt,
        "intent": intent,
    }
