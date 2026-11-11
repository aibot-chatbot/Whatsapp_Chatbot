import logging
import threading
import time

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
from app.services.channel_delivery_service import HandoffAcknowledgement
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services import content_filter


def _after_reply(label, work):
    """Run bookkeeping that the customer's reply must not wait for.

    Each of these writes is a remote PostgREST round trip (~124 ms measured
    from the deployed machine) and none of them changes the reply. Failures
    keep the warning they were logged with when they ran inline, so nothing
    becomes silent.

    Ceiling: one bare daemon thread per call, so a deploy mid-flight drops the
    record and nothing bounds how many are in flight. That is acceptable while
    these are best-effort records of a turn that already succeeded; move them
    onto a real queue before anything starts depending on them.
    """
    def run():
        try:
            work()
        except Exception as e:
            logging.warning("%s failed off the reply path: %s", label, e)

    threading.Thread(target=run, name="chat-bookkeeping", daemon=True).start()


def _resolve_chatbot_company_id(chatbot_id):
    chatbot = get_bot_by_id(chatbot_id)
    if not chatbot or chatbot.get("id") != chatbot_id:
        raise ValueError("Authoritative chatbot ownership could not be resolved")

    company_id = chatbot.get("company_id")
    if not isinstance(company_id, int) or isinstance(company_id, bool) or company_id <= 0:
        raise ValueError("Authoritative chatbot ownership could not be resolved")

    return company_id


# Sent when the AI provider could not answer a real customer; the chat is already queued for staff.
AI_UNAVAILABLE_HANDOFF_REPLY = (
    "Sorry, our AI assistant is temporarily unavailable. I've passed your message to our "
    "Customer Service team, and a staff member will reply to you here shortly."
)
_OUTAGE_REASON = "The AI assistant could not reply, so the chat was handed to staff automatically."
# Sent when the provider's safety filter refused a real customer's message. It accuses nobody.
MODERATION_HANDOFF_REPLY = "Let me check this with our team. A staff member will reply to you here soon."
# For a test chat, or a handoff that could not be recorded: this one promises no staff reply.
MODERATION_BLOCKED_REPLY = "Sorry, I can't help with that here."
_MODERATION_REASON = "The AI provider's safety filter refused this message, so the chat was handed to staff."
# For a test chat, or a handoff that could not be recorded. A real customer gets the outage reply,
# because the limit is the Client's to deal with and the customer did nothing.
KEY_LIMIT_PLAIN_REPLY = "This assistant has reached its usage limit for now. Please try again later."
_KEY_LIMIT_REASON = "The AI assistant reached its usage limit, so the chat was handed to staff."
# Filter 1 (plan A3) stopped the message on our own server; no AI saw it.
_CONTENT_FLAG_REASON = "Omnexa's safety check stopped this message before any AI saw it, so the chat was handed to staff."
# Helpline chosen by the owner 2026-11-11: Befrienders KL (24 hours) plus 999, Malaysia's emergency number.
_HELPLINE = ("You can talk to Befrienders KL any time, day or night, at 03-7627 2929. "
             "If you are in danger right now, please call 999.")
SELF_HARM_PLAIN_REPLY = (
    "I'm really sorry you're going through this. You don't have to face it alone. " + _HELPLINE
)
SELF_HARM_HANDOFF_REPLY = (
    "I'm really sorry you're going through this. You don't have to face it alone. I've passed "
    "your message to our team and someone will reply to you here soon. " + _HELPLINE
)
_SELF_HARM_REASON = "The customer may be at risk of self-harm. Please reply to them yourself as soon as you can."
# One provider outage can hand over many chats at once; one email per company per window keeps
# the shared mailbox quota (also used for sign-in mail) safe. The dashboard still lists every chat.
OUTAGE_EMAIL_WINDOW_SECONDS = 15 * 60
# shortcut: per-process memory, correct while Fly runs one gunicorn worker; move to the DB if that changes.
_outage_email_sent_at = {}
_outage_email_lock = threading.Lock()


def _record_agent_action(**fields):
    # The pipeline's single agent-action write site (pinned by test_agent_action_ownership).
    return save_agent_action(**fields)


def _claim_outage_email(company_id):
    with _outage_email_lock:
        now = time.monotonic()
        last = _outage_email_sent_at.get(company_id)
        if last is not None and now - last < OUTAGE_EMAIL_WINDOW_SECONDS:
            return False
        _outage_email_sent_at[company_id] = now
        return True


def hand_off_after_ai_failure(chatbot_id, conversation):
    """Pause the AI and queue the chat for staff because the provider could not answer."""
    return _hand_off_to_staff(chatbot_id, conversation, trigger="ai_unavailable",
                              reason=_OUTAGE_REASON, reply=AI_UNAVAILABLE_HANDOFF_REPLY)


def hand_off_after_key_limit(chatbot_id, conversation):
    """Pause the AI and queue the chat for staff because this Client's key spent its cap."""
    return _hand_off_to_staff(chatbot_id, conversation, trigger="key_limit",
                              reason=_KEY_LIMIT_REASON, reply=AI_UNAVAILABLE_HANDOFF_REPLY)


def hand_off_after_moderation_block(chatbot_id, conversation, block):
    """Pause the AI and queue the chat for staff because the provider refused the message.

    shortcut: pausing is what stops the flagged message being re-sent in the chat history.
    Filter 1 now drops history text it recognises (plan A3), but a message only the provider
    refused can still be re-sent after Resolve; Filter 2 (plan A4) is the next check for it.
    """
    return _hand_off_to_staff(
        chatbot_id, conversation, trigger="moderation_block", reason=_MODERATION_REASON,
        reply=MODERATION_HANDOFF_REPLY,
        details={"reasons": block.reasons, "provider_name": block.provider_name, "model_slug": block.model_slug},
        # The reply promises staff, so it is never throttled. The pause limits it to one per customer.
        always_email=True,
    )


def hand_off_after_content_flag(chatbot_id, conversation, flag):
    """Pause the AI and queue the chat for staff because Filter 1 stopped the customer's message.

    The reply promises staff, so the email is never throttled; the pause limits it to one per customer.
    """
    details = {"category": flag.category, "rule": flag.rule}
    if flag.is_self_harm:
        return _hand_off_to_staff(chatbot_id, conversation, trigger="self_harm", reason=_SELF_HARM_REASON,
                                  reply=SELF_HARM_HANDOFF_REPLY, details=details, always_email=True)
    return _hand_off_to_staff(chatbot_id, conversation, trigger="content_flag", reason=_CONTENT_FLAG_REASON,
                              reply=MODERATION_HANDOFF_REPLY, details=details, always_email=True)


def review_customer_message(message, *, company_id, chatbot_id, conversation_id):
    """Filter 2 (plan A4) on Workers AI. Returns a ContentFlag only when block mode stops the message.

    Log mode reviews off the reply path, because Workers AI takes 0.7 s to over 13 s (measured
    2026-11-10). An unavailable review lets the message through: Filter 1 already ran here.
    """
    from app.services import content_review_service

    review_mode = content_review_service.mode()
    if review_mode == "off":
        return None

    def review():
        # The verdict never needs IC or card numbers, so Cloudflare never sees them.
        result = content_review_service.review_text(content_filter.hide_sensitive_numbers(message))
        if result.verdict != "unsafe":
            return None
        flag = result.as_flag()
        if review_mode == "log":
            record_content_flag(company_id=company_id, chatbot_id=chatbot_id, conversation_id=conversation_id,
                                flag=flag, source="customer", review_mode="log")
        return flag

    if review_mode == "log":
        _after_reply("[ContentReview] log-mode review for chatbot_id=%s" % chatbot_id, review)
        return None
    return review()


# shortcut: Filter 2 reviews at most this many sections per document; move the review onto the
# ingest job queue, with a per-chunk budget, before dropping sections on its verdict.
MAX_REVIEWED_SECTIONS = 40


def scan_client_text(sections, chatbot_id, *, source):
    """The upload scan (plan A4): a Client's document or website, before embedding or any AI.

    Filter 1 drops flagged sections and records one flag per category. Filter 2, when on, only
    records, in the background: up to 40 sections at 1-13 s each is too slow to wait for.
    Numbers are left alone, because a Client's own bank account must reach the bot. Never raises.
    """
    from app.services import content_review_service

    kept, flagged = [], {}
    for section in sections:
        flag = content_filter.check_bot_text(section, chatbot_id)
        if flag is None:
            kept.append(section)
        else:
            flagged.setdefault(flag.category, flag)
    if flagged:
        logging.warning("[ContentFilter] chatbot %s: %d %s section(s) left out (%s)", chatbot_id,
                        len(sections) - len(kept), source, ", ".join(sorted(flagged)))
    review_on = content_review_service.mode() != "off" and kept
    if not flagged and not review_on:
        return kept  # nothing to record: skip the company lookup
    try:
        company_id = _resolve_chatbot_company_id(chatbot_id)
    except Exception as error:
        logging.error("[ContentFilter] %s flags not saved for chatbot_id=%s (%s)", source, chatbot_id,
                      type(error).__name__)
        return kept
    for flag in flagged.values():
        record_content_flag(company_id=company_id, chatbot_id=chatbot_id, conversation_id=None,
                            flag=flag, source=source)

    if review_on:
        def review():
            reviewed = {}
            for section in kept[:MAX_REVIEWED_SECTIONS]:
                result = content_review_service.review_text(section)
                if result.verdict == "unsafe":
                    reviewed.setdefault(result.group, result.as_flag())
            for flag in reviewed.values():
                record_content_flag(company_id=company_id, chatbot_id=chatbot_id, conversation_id=None,
                                    flag=flag, source=source, review_mode="log")
        _after_reply("[ContentReview] %s review for chatbot_id=%s" % (source, chatbot_id), review)
    return kept


def scan_client_page(text, chatbot_id, *, source):
    """scan_client_text for one block of page text, by section: scraped HTML breaks lines at tags,
    so a phrase can span two lines. A page with nothing flagged comes back unchanged."""
    from app.services.rag_service import split_text_into_sections

    sections = split_text_into_sections(text)
    kept = scan_client_text(sections, chatbot_id, source=source)
    return text if len(kept) == len(sections) else "\n\n".join(kept)


def record_content_flag(*, company_id, chatbot_id, conversation_id, flag, source, review_mode=None):
    """Keep a Filter 1 flag in agent_actions for the Consequences step (plan A5).

    Never raises: the message is stopped whether or not the record lands. Stores the category and
    rule only, never the text. intent stays "unknown" because the live CHECK constraint (027)
    rejects a new intent; the payload's content_flag key is what marks the row.
    """
    try:
        _record_agent_action(
            company_id=company_id,
            chatbot_id=chatbot_id,
            conversation_id=conversation_id,
            intent="unknown",
            action_type="none",
            confidence=1.0,
            reason=(f"Safety review flagged a {source} message ({flag.category}); it was not stopped (log mode)."
                    if review_mode == "log" else f"Safety check stopped a {source} message ({flag.category})."),
            # "mode": "log" marks a Filter 2 verdict that was recorded but did not stop the message.
            payload={"content_flag": {"filter": flag.filter, "category": flag.category, "rule": flag.rule,
                                      "source": source, **({"mode": review_mode} if review_mode else {})}},
        )
    except Exception as error:
        logging.error("[ContentFilter] flag not saved for chatbot_id=%s (%s)", chatbot_id, type(error).__name__)

    if flag.category == content_filter.CHILD_SEXUAL:
        def alert_owner():
            from app.services.email_service import send_content_flag_alert_email
            send_content_flag_alert_email(company_id=company_id, category=flag.category, source=source,
                                          stopped=review_mode != "log")
        _after_reply("[ContentFilter] owner alert for chatbot_id=%s" % chatbot_id, alert_owner)


def _hand_off_to_staff(chatbot_id, conversation, *, trigger, reason, reply, details=None, always_email=False):
    """Returns the acknowledgement to send, or None when the handoff was not recorded:
    the caller then keeps its plain reply instead of promising that staff will answer.
    Raises when ownership cannot be resolved or the record cannot be written.
    """
    from app.database.agent_action_repository import is_conversation_escalated

    company_id = _resolve_chatbot_company_id(chatbot_id)
    # Two messages can fail at once (channels call the AI outside the delivery lock):
    # the second sees the first's handoff and stays silent instead of escalating again.
    with conversation_delivery_lock(conversation["id"]):
        if is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
            return None
        saved = _record_agent_action(
            company_id=company_id,
            chatbot_id=chatbot_id,
            conversation_id=conversation["id"],
            intent="handoff_request",
            action_type="request_handoff",
            confidence=1.0,
            reason=reason,
            payload={"trigger": trigger, **(details or {})},
        )
    action_id = saved.get("id") if isinstance(saved, dict) else None
    if not isinstance(action_id, int) or isinstance(action_id, bool) or action_id <= 0:
        return None

    try:
        create_crm_lead_from_agent_signal(
            chatbot_id=chatbot_id,
            conversation=conversation,
            intent="handoff_request",
            suggested_action="request_handoff",
            reason=reason,
        )
    except Exception as e:
        logging.warning("[AIOutage] lead creation failed for chatbot_id=%s conversation_id=%s: %s",
                        chatbot_id, conversation["id"], e)

    if always_email or _claim_outage_email(company_id):
        def notify():
            from app.services.email_service import send_handoff_notification_email
            send_handoff_notification_email(company_id=company_id, conversation=conversation,
                                            chatbot_id=chatbot_id, trigger=trigger)
        # SMTP has no timeout here; the customer's holding message must not wait on it.
        _after_reply("[AIOutage] staff email for chatbot_id=%s" % chatbot_id, notify)

    return HandoffAcknowledgement(
        reply,
        action_id=action_id, conversation_id=conversation["id"],
        chatbot_id=chatbot_id, company_id=company_id,
    )


def prepare_chat_prompt(
    message,
    customer_id,
    chatbot_id,
    source_channel="whatsapp",
    conversation=None,
):
    conversation = conversation if conversation is not None else get_or_create_conversation(
        chatbot_id=chatbot_id,
        customer_phone=customer_id,
        customer_name=None,
        source_channel=source_channel,
    )

    # Old messages go back to the AI with every turn, so Filter 1 runs on them again (plan A3).
    history = content_filter.clean_history(
        get_recent_chat_history(conversation["id"], limit=MAX_HISTORY),
        chatbot_id,
    )
    # Retrieval (Gemini embeddings), the prompt and conversation memory all get IC and card
    # numbers hidden; the raw message is kept only for workflow state, which no AI reads.
    ai_message = content_filter.hide_sensitive_numbers(message)

    from app.database.agent_action_repository import is_conversation_escalated
    if is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
        logging.info(f"[ChatPipeline] Conversation {conversation['id']} is currently escalated to human staff. Skipping AI response.")
        return {
            "direct_reply": "<SILENT_BOT_RESPONSE>",
            "prompt": None,
            "intent": "escalated_to_human",
        }

    authoritative_company_id = None
    action_saved = False

    try:
        # Its extracted fields become conversation memory, which a later prompt recalls.
        agent_decision = analyze_agent_intent(
            ai_message,
            conversation_history=history,
        )
        logging.info(
            "[AgentDecision] chatbot_id=%s intent=%s action=%s confidence=%.2f",
            chatbot_id,
            agent_decision.get("intent"),
            agent_decision.get("suggested_action"),
            agent_decision.get("confidence", 0.0),
        )

        is_handoff = agent_decision.get("intent") == "handoff_request"
        saved_action_id = None

        try:
            authoritative_company_id = _resolve_chatbot_company_id(chatbot_id)
            def save_action():
                return _record_agent_action(
                    company_id=authoritative_company_id,
                    chatbot_id=chatbot_id,
                    conversation_id=conversation.get("id"),
                    intent=agent_decision.get("intent", "unknown"),
                    action_type=agent_decision.get("suggested_action", "none"),
                    confidence=agent_decision.get("confidence"),
                    reason=agent_decision.get("reason", ""),
                    payload=build_safe_agent_action_payload(agent_decision),
                )

            # Only a handoff blocks on this write: action_saved is the proof
            # that customer service was actually notified, and the reply below
            # depends on it. Every other intent is a record of what happened
            # and is written after the customer has their answer.
            if is_handoff:
                saved_action = save_action()
                saved_action_id = saved_action.get("id") if isinstance(saved_action, dict) else None
                action_saved = isinstance(saved_action_id, int) and not isinstance(saved_action_id, bool) and saved_action_id > 0
            else:
                _after_reply("[AgentDecision] save", save_action)
        except Exception as e:
            logging.warning(
                "[AgentDecision] save failed for chatbot_id=%s: %s",
                chatbot_id,
                e,
            )

        if is_handoff and not action_saved:
            return {"direct_reply": "I could not notify our customer service team. Please try requesting a human again.",
                    "prompt": None, "intent": "handoff_failed"}

        def create_lead():
            return create_crm_lead_from_agent_signal(
                chatbot_id=chatbot_id,
                conversation=conversation,
                intent=agent_decision.get("intent", "unknown"),
                suggested_action=agent_decision.get("suggested_action", "none"),
                reason=agent_decision.get("reason", ""),
            )

        # A handoff lead is the staff-attention record the acknowledgement below
        # promises, so it stays inline. Ordinary signals do not gate the reply.
        if is_handoff:
            try:
                create_lead()
            except Exception as e:
                logging.warning(
                    "[CRM] lead creation failed for chatbot_id=%s conversation_id=%s: %s",
                    chatbot_id,
                    conversation.get("id"),
                    e,
                )
        else:
            _after_reply(
                "[CRM] lead creation for chatbot_id=%s conversation_id=%s"
                % (chatbot_id, conversation.get("id")),
                create_lead,
            )

        # Persist what this turn revealed about the customer as conversation-
        # scoped graph nodes, so a later turn can recall it. analyze_agent_intent
        # is pure regex, so these fields are already extracted for free -- this
        # adds no LLM call and no billing change. Only a *later* turn reads it,
        # so this turn's reply does not wait for the plan gate or the write.
        def remember_facts():
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
                return

            conversation_memory_service.remember_conversation_facts(
                chatbot_id=chatbot_id,
                conversation_id=conversation.get("id"),
                extracted_fields=agent_decision.get("extracted_fields"),
            )

        _after_reply(
            "[ConversationMemory] store for chatbot_id=%s conversation_id=%s"
            % (chatbot_id, conversation.get("id")),
            remember_facts,
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
                "direct_reply": HandoffAcknowledgement(
                    "I'm transferring you to our Customer Service team now. Please hold on while I connect you. They will be with you shortly! \U0001f60a",
                    action_id=saved_action_id, conversation_id=conversation["id"],
                    chatbot_id=chatbot_id, company_id=authoritative_company_id,
                ),
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
        ai_message,
        chatbot_id=chatbot_id,
        conversation_id=conversation.get("id"),
    )

    logging.info(f"[ChatPipeline] Retrieved chunks: {len(context_chunks)}")

    prompt = build_prompt(
        history,
        ai_message,
        context_chunks,
        chatbot_id=chatbot_id,
        customer_needs=conversation.get("customer_needs"),
    )

    return {
        "direct_reply": None,
        "prompt": prompt,
        "intent": intent,
    }
