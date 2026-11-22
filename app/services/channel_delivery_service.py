"""Require the conversation's original, verified channel for every delivery."""

import logging
from datetime import datetime, timedelta, timezone

from app.database.telegram_channel_repository import get_telegram_channel_by_id, get_telegram_channels_by_chatbot
from app.database.whatsapp_channel_repository import get_whatsapp_channel_by_id, get_whatsapp_channels_by_chatbot
from app.database.channel_server_repository import get as get_linked_channel, list_channels as list_linked_channels
from app.database import agent_action_repository, message_repository
from app.database.agent_action_repository import is_pending_handoff_action
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.free_trial_status_service import parse_iso_datetime
from app.services.handoff_service import handoff_control_enabled
from app.utils.message_style_utils import parse_buttons_tag

logger = logging.getLogger(__name__)
STAFF_IDLE_RESUME_MINUTES = 30
AI_RESUMED_NOTICE = "The customer service session has ended. You are now chatting with the AI assistant again."


class HandoffAcknowledgement(str):
    """Server-generated acknowledgement of this turn's persisted handoff."""

    def __new__(cls, text, *, action_id, conversation_id, chatbot_id, company_id):
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
               for value in (action_id, conversation_id, chatbot_id, company_id)):
            raise ValueError("A handoff acknowledgement requires a persisted action and owner")
        reply = super().__new__(cls, text)
        reply.action_id = action_id
        reply.conversation_id = conversation_id
        reply.chatbot_id = chatbot_id
        reply.company_id = company_id
        return reply


def automatic_reply_allowed(conversation, reply, *, paused, control=None, epoch_at_dispatch=None):
    if not isinstance(reply, HandoffAcknowledgement):
        allowed = not paused
    else:
        # Text returned by a model cannot create this marker. Resolve may have
        # completed while this turn was running, so recheck the exact saved action.
        allowed = (reply.conversation_id == conversation.get("id")
                   and reply.chatbot_id == conversation.get("chatbot_id")
                   and is_pending_handoff_action(reply.action_id, reply.conversation_id,
                                                 reply.chatbot_id, reply.company_id))
    # The handoff gate may only ever subtract permission, never grant it: a
    # denial above is final, and with no control the legacy `paused` boolean
    # stays authoritative. Never fold these two verdicts into an `or`.
    if not allowed or control is None:
        return allowed
    from app.services.handoff_service import automation_admission, handoff_control_enabled
    if not handoff_control_enabled():
        return allowed
    return automation_admission(control, epoch_at_dispatch=epoch_at_dispatch).allowed


class ChannelDeliveryError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


PROVIDER_FIELDS = {
    "telegram": "telegram_bot_id",
    "whatsapp": "phone_number_id",
    "whatsapp_link": "phone_number",
}


def channel_identity(channel, source_channel):
    field = PROVIDER_FIELDS.get(source_channel)
    provider_id = channel.get(field) if field else None
    if not channel.get("id") or not provider_id:
        raise ChannelDeliveryError("CHANNEL_IDENTITY_UNVERIFIED", "The original channel identity has not been verified.")
    return {"source_channel_id": channel["id"], "source_provider_id": str(provider_id)}


def validate_channel(channel, source_channel, chatbot_id):
    if not channel or channel.get("chatbot_id") != chatbot_id:
        raise ChannelDeliveryError("CHANNEL_NOT_CONNECTED", "The original channel is unavailable.")
    if not channel.get("is_active") or channel.get("connection_status") != "connected":
        raise ChannelDeliveryError("CHANNEL_NOT_CONNECTED", "The original channel is disconnected. Reconnect it before replying.")
    if not channel.get("verified_at"):
        raise ChannelDeliveryError("CHANNEL_IDENTITY_UNVERIFIED", "Verify the original channel connection before replying.")
    channel_identity(channel, source_channel)
    return channel


def get_bound_channel(conversation):
    source = conversation.get("source_channel")
    loaders = {
        "telegram": get_telegram_channel_by_id,
        "whatsapp": get_whatsapp_channel_by_id,
        "whatsapp_link": get_linked_channel,
    }
    if source not in loaders:
        raise ChannelDeliveryError("CHANNEL_UNSUPPORTED", "This conversation does not support external replies.")
    channel_id = conversation.get("source_channel_id")
    provider_id = conversation.get("source_provider_id")
    if not channel_id or not provider_id:
        raise ChannelDeliveryError("CHANNEL_IDENTITY_UNVERIFIED", "This conversation's original channel has not been verified.")
    channel = loaders[source](channel_id)
    if channel and str(channel.get(PROVIDER_FIELDS[source]) or "") != str(provider_id):
        raise ChannelDeliveryError("CHANNEL_REPLACED", "This conversation belongs to a previous bot or number. Reconnect its original channel.")
    if channel and not channel.get("is_active"):
        list_channels = {"telegram": get_telegram_channels_by_chatbot, "whatsapp": get_whatsapp_channels_by_chatbot,
                         "whatsapp_link": list_linked_channels}[source]
        current = list_channels(conversation["chatbot_id"])
        if any(row.get("id") != channel_id and row.get("is_active") and row.get("connection_status") == "connected"
               and row.get("verified_at") for row in current):
            raise ChannelDeliveryError("CHANNEL_REPLACED", "This conversation belongs to a previous connection. Reconnect its original bot or number before replying.")
    return validate_channel(channel, source, conversation.get("chatbot_id"))


def delivery_accepted(source, result):
    if source == "telegram":
        return isinstance(result, dict) and result.get("ok") is True
    if source == "whatsapp":
        if not hasattr(result, "status_code") or not 200 <= result.status_code < 300:
            return False
        try:
            data = result.json()
            return isinstance(data, dict) and bool(data.get("messages")) and not data.get("error")
        except (ValueError, TypeError):
            return False
    return False


def dispatch_conversation_reply(conversation, text, *, send_telegram=None, send_whatsapp=None):
    source = conversation["source_channel"]
    if source == "whatsapp_link":
        return send_linked_reply(conversation, text)
    channel = get_bound_channel(conversation)
    recipient = conversation.get("platform_user_id") or conversation.get("customer_phone")
    if not recipient:
        raise ChannelDeliveryError("DELIVERY_FAILED", "The conversation recipient is missing.")
    if source == "telegram":
        from app.utils.telegram_utils import send_telegram_message
        result = (send_telegram or send_telegram_message)(channel["bot_token"], recipient, text)
    else:
        from app.utils.whatsapp_utils import get_text_message_input, send_message
        result = (send_whatsapp or send_message)(get_text_message_input(recipient, text), channel=channel)
    if not delivery_accepted(source, result):
        raise ChannelDeliveryError("DELIVERY_FAILED", "The provider did not confirm delivery. Check the conversation before retrying.")
    return result


def send_ai_resumed_notice(conversation, chatbot_id, *, is_paused, save,
                           dispatch=dispatch_conversation_reply, lock=conversation_delivery_lock):
    if not conversation or conversation.get("source_channel") not in PROVIDER_FIELDS:
        return True, "not_sent", None
    conversation_id = conversation["id"]
    try:
        with lock(conversation_id):
            if is_paused(conversation_id, chatbot_id, conversation=conversation):
                return False, "not_sent", None
            dispatch(conversation, AI_RESUMED_NOTICE)
            save(conversation_id=conversation_id, sender_type="bot", message_text=AI_RESUMED_NOTICE,
                 message_type="text", delivery_status="sent", ai_generated=False)
        return True, "sent", None
    except Exception as error:
        logger.warning("AI resume notice failed conversation_id=%s chatbot_id=%s", conversation_id, chatbot_id)
        return True, "failed", error.code if isinstance(error, ChannelDeliveryError) else "DELIVERY_FAILED"


def _idle_escalations(conversation, chatbot_id, cutoff):
    conversation_id = conversation["id"]
    rows = agent_action_repository.get_open_conversation_escalations(conversation_id, chatbot_id)
    if not rows:
        return []
    for row in rows:
        opened = parse_iso_datetime(row["created_at"])
        if opened is None or opened > cutoff:
            return []
    latest = message_repository.latest_staff_reply_at(
        conversation_id, chatbot_id, web=conversation.get("source_channel") == "web")
    if latest is not None:
        replied = parse_iso_datetime(latest)
        if replied is None or replied > cutoff:
            return []
    return rows


def resume_ai_after_staff_idle(conversation, chatbot_id, *, now=None) -> bool:
    if handoff_control_enabled() or conversation.get("chatbot_id") != chatbot_id:
        return False
    conversation_id = conversation["id"]
    with conversation_delivery_lock(conversation_id):
        cutoff = (parse_iso_datetime(now) if now is not None else datetime.now(timezone.utc)) - timedelta(
            minutes=STAFF_IDLE_RESUME_MINUTES)
        try:
            rows = _idle_escalations(conversation, chatbot_id, cutoff)
            if not rows:
                return False
            for row in rows:
                resolved, changed = agent_action_repository.resolve_escalation(row["id"], chatbot_id, row["company_id"])
        except Exception:
            logger.warning("Staff idle check failed conversation_id=%s chatbot_id=%s", conversation_id, chatbot_id)
            return False
        if not resolved or not resolved.get("_ai_resumed"):
            return False
        if not changed:
            return True
        resumed, _, _ = send_ai_resumed_notice(conversation, chatbot_id,
                                               is_paused=agent_action_repository.is_conversation_escalated,
                                               save=message_repository.save_message)
        if resumed:
            logger.info("Staff idle handoff ended conversation_id=%s chatbot_id=%s", conversation_id, chatbot_id)
        return resumed


def send_linked_reply(conversation, text):
    """Resolve the original session immediately before automatic, staff or held delivery."""
    from app.services.channel_server_service import send_poll, send_text, ChannelServerError

    channel = get_bound_channel(conversation)
    session = channel["session_name"]
    recipient = conversation.get("platform_user_id") or conversation.get("customer_phone")
    body, options = parse_buttons_tag(text)
    unique = {}
    for label in options:
        unique.setdefault(label.casefold(), label)
    labels = list(unique.values())
    offer_poll = bool(body.strip()) and len(labels) >= 2
    outbound = body if offer_poll else "\n".join([body, *labels]).strip()
    try:
        delivered = send_text(session, recipient, outbound)
    except ChannelServerError:
        delivered = False
    if not delivered:
        raise ChannelDeliveryError("DELIVERY_FAILED", "Channel Server did not confirm delivery.")
    if not offer_poll:
        return True
    try:
        if send_poll(session, recipient, "Choose an option", labels):
            return True
    except ChannelServerError:
        pass
    logger.warning("[ChannelServer] poll unconfirmed, sending choices as text")
    try:
        if send_text(session, recipient, "\n".join(labels)):
            return True
    except ChannelServerError:
        pass
    logger.warning("[ChannelServer] choice list unconfirmed after body delivery")
    return True
