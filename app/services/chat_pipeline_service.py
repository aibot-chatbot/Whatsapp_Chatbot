import logging

from app.database.chat_history_repository import get_recent_chat_history
from app.database.conversation_repository import get_or_create_conversation
from app.database.agent_action_repository import save_agent_action
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
            save_agent_action(
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
