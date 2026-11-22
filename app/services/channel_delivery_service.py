"""Require the conversation's original, verified channel for every delivery."""

import logging

from app.database.telegram_channel_repository import get_telegram_channel_by_id, get_telegram_channels_by_chatbot
from app.database.whatsapp_channel_repository import get_whatsapp_channel_by_id, get_whatsapp_channels_by_chatbot
from app.database.channel_server_repository import get as get_linked_channel, list_channels as list_linked_channels
from app.database.agent_action_repository import is_pending_handoff_action
from app.utils.message_style_utils import parse_buttons_tag

logger = logging.getLogger(__name__)


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


def send_linked_reply(conversation, text):
    """Resolve the original session immediately before automatic, staff or held delivery."""
    from app.services.channel_server_service import send_list, send_text, ChannelServerError

    channel = get_bound_channel(conversation)
    session = channel["session_name"]
    recipient = conversation.get("platform_user_id") or conversation.get("customer_phone")
    body, options = parse_buttons_tag(text)
    unique = {}
    for label in options:
        unique.setdefault(label.casefold(), label)
    labels = list(unique.values())
    offer_list = bool(body.strip()) and len(labels) >= 2
    outbound = body if offer_list else "\n".join([body, *labels]).strip()
    try:
        delivered = send_text(session, recipient, outbound)
    except ChannelServerError:
        delivered = False
    if not delivered:
        raise ChannelDeliveryError("DELIVERY_FAILED", "Channel Server did not confirm delivery.")
    if not offer_list:
        return True
    try:
        if send_list(session, recipient, labels):
            return True
    except ChannelServerError:
        pass
    logger.warning("[ChannelServer] list unconfirmed, sending choices as text")
    try:
        if send_text(session, recipient, "\n".join(labels)):
            return True
    except ChannelServerError:
        pass
    logger.warning("[ChannelServer] choice text unconfirmed after body delivery")
    return True
