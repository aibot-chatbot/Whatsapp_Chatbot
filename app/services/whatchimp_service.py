"""WhatChimp inbound webhook: customer message in, AI reply out.

WhatChimp forwards each customer message to /whatchimp/webhook/<secret>; the
secret in the path is the only authentication, so only its fingerprint is ever
logged. The pipeline mirrors WaSender's (claim, handoff pause, delivery lock
around every send), with one difference: WhatChimp numbers run on the WhatsApp
Cloud API, so the AI's [BUTTONS: ...] become real tappable reply buttons.
"""

import hashlib
import logging
import re

from app.database.agent_action_repository import is_conversation_escalated
from app.database.conversation_repository import get_or_create_conversation
from app.database.message_repository import save_message
from app.database.whatchimp_channel_repository import (
    claim_whatchimp_message,
    get_whatchimp_channel_by_secret,
    mark_whatchimp_inbound,
    release_whatchimp_message_claim,
)
from app.services.ai_router import generate_response
from app.services.channel_delivery_service import (
    automatic_reply_allowed,
    channel_identity,
    delivery_accepted,
    get_bound_channel,
    validate_channel,
)
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.media_send_service import dispatch_media_after_reply
from app.services.turn_cache import turn_cache
from app.services.wasender_service import split_reply_buttons, split_wasender_reply
from app.services.whatchimp_client import WHATSAPP_BSUID, send_whatchimp_buttons, send_whatchimp_text

SOURCE = "whatchimp"
# WhatsApp caps the text of a button message at 1024 characters.
BUTTON_BODY_LIMIT = 1024
BUTTON_FALLBACK_BODY = "Choose an option"
TEXT_ONLY_REPLY = ("I received your message, but I can only reply to text messages for now. "
                   "Please type your question and I'll help you.")


def _fingerprint(secret):
    return hashlib.sha256(str(secret).encode()).hexdigest()[:12]


MAX_LOGGED_FIELDS = 40
_UNSAFE_FIELD_CHARS = re.compile(r"[^A-Za-z0-9_]")
_SENDER = re.compile(r"\d{6,15}")
_FLAT_SENDER = re.compile(r"\+?(\d{6,15})")
MAX_MESSAGE_ID_LENGTH = 200


def _key_paths(payload):
    """Field names only, never values: enough to see an unexpected payload shape without logging customer text.

    Breadth-first and capped, so a huge body costs at most MAX_LOGGED_FIELDS steps;
    names are reduced to [A-Za-z0-9_] so a crafted key cannot forge log lines.
    """
    paths, queue = [], [("", payload, 0)]
    while queue and len(paths) < MAX_LOGGED_FIELDS:
        prefix, value, depth = queue.pop(0)
        if depth > 8:  # deep enough for entry[].changes[].value.messages[].<field>
            continue
        if isinstance(value, dict):
            for key, child in list(value.items())[:MAX_LOGGED_FIELDS]:
                name = _UNSAFE_FIELD_CHARS.sub("?", str(key))[:40]
                path = f"{prefix}.{name}" if prefix else name
                paths.append(path)
                queue.append((path, child, depth + 1))
        elif isinstance(value, list) and value:
            queue.append((f"{prefix}[]", value[0], depth + 1))
    return paths[:MAX_LOGGED_FIELDS]


def extract_whatchimp_messages(payload, phone_number_id=None):
    """Customer messages in a WhatChimp delivery, oldest first.

    A change addressed to another WhatsApp number is skipped, so two numbers pointed at
    one link can never make this channel's bot answer the other number's customers.

    shortcut: parses the WhatsApp Cloud API envelope (entry[].changes[].value.messages[]);
    confirm against a captured WhatChimp delivery before launch.
    """
    messages = []
    for entry in (payload or {}).get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            addressed_to = str((value.get("metadata") or {}).get("phone_number_id") or "")
            if phone_number_id and addressed_to and addressed_to != str(phone_number_id):
                continue
            names = {str(contact.get("wa_id")): (contact.get("profile") or {}).get("name")
                     for contact in value.get("contacts") or [] if isinstance(contact, dict)}
            for message in value.get("messages") or []:
                if (not isinstance(message, dict) or not message.get("id")
                        or not _SENDER.fullmatch(str(message.get("from") or ""))):
                    continue
                kind = message.get("type")
                interactive = message.get("interactive") or {}
                if kind == "text":
                    text = (message.get("text") or {}).get("body")
                elif kind == "interactive":
                    text = (interactive.get("button_reply") or interactive.get("list_reply") or {}).get("title")
                elif kind == "button":
                    text = (message.get("button") or {}).get("text")
                else:
                    text = None
                messages.append({
                    "message_id": str(message["id"]),
                    "customer_phone": "+" + str(message["from"]).lstrip("+"),
                    "customer_name": names.get(str(message["from"])),
                    "message_text": text.strip() if isinstance(text, str) and text.strip() else None,
                })
    return messages or _flat_messages(payload or {})


def _flat_messages(payload):
    """WhatChimp's own delivery format, first captured live on 2026-10-17: one flat object.

    Fields seen: wa_message_id, user_message, chat_id (the customer), phone_number (first message
    only), first_name, wa_username, whatsapp_bot_id, subscriber_id, event, subscribed_at.
    No wrong-number guard: whatsapp_bot_id is WhatChimp's own bot id, not the Meta phone_number_id
    (checked live), and each webhook link already belongs to exactly one channel.
    """
    message_id = str(payload.get("wa_message_id") or "").strip()
    if not message_id or len(message_id) > MAX_MESSAGE_ID_LENGTH:
        return []
    sender = _flat_customer(payload)
    if not sender:
        return []
    text = payload.get("user_message")
    name = payload.get("first_name") or payload.get("wa_username")
    return [{
        "message_id": message_id,
        "customer_phone": sender,
        "customer_name": name.strip() if isinstance(name, str) and name.strip() else None,
        "message_text": text.strip() if isinstance(text, str) and text.strip() else None,
    }]


def _flat_customer(payload):
    """The reply address: chat_id first, because only a customer's first message carries phone_number.

    chat_id is the customer's number or, since WhatsApp usernames, a business-scoped user ID
    (seen live 2026-10-17), so one customer keeps one conversation from the first message on.
    """
    for field in ("chat_id", "phone_number"):
        value = str(payload.get(field) or "").strip()
        match = _FLAT_SENDER.fullmatch(value)
        if match:
            return "+" + match.group(1)
        if WHATSAPP_BSUID.fullmatch(value):
            return value
    return None


def process_whatchimp_webhook(payload, webhook_secret):
    channel = get_whatchimp_channel_by_secret(webhook_secret)
    if not channel:
        logging.warning("WhatChimp webhook has no active channel for %s; message dropped.", _fingerprint(webhook_secret))
        return
    try:
        from app.services.company_status_service import ensure_company_operational
        ensure_company_operational(channel.get("company_id"))
    except Exception:
        logging.info("WhatChimp webhook ignored because company is not operational.")
        return

    # Any delivery proves the link pasted into WhatChimp works, even one we cannot read.
    mark_whatchimp_inbound(channel["id"])
    messages = extract_whatchimp_messages(payload if isinstance(payload, dict) else {}, channel.get("phone_number_id"))
    if not messages:
        logging.info("WhatChimp delivery carried no customer message; fields: %s",
                     ", ".join(_key_paths(payload)) or "none")
        return
    for parsed in messages:
        try:
            _claim_and_process(parsed, channel)
        except Exception as error:
            # The type name only: the exception text can quote customer messages.
            logging.error("WhatChimp message processing failed (%s)", type(error).__name__)


def _claim_and_process(parsed, channel):
    """Handle each WhatChimp message id once; release the claim if nothing started."""
    validate_channel(channel, SOURCE, channel["chatbot_id"])
    if not claim_whatchimp_message(channel["id"], parsed["message_id"]):
        logging.info("Duplicate WhatChimp message ignored.")
        return
    progress = {"started": False}
    try:
        with turn_cache():
            return _process_claimed_message(parsed, channel, progress)
    except Exception:
        if not progress["started"]:
            release_whatchimp_message_claim(channel["id"], parsed["message_id"])
        raise


def remember_sent(channel, result):
    """Claim the wa_message_id of a message we sent: WhatChimp posts it back to the webhook (seen live
    2026-10-17), and the claimed id turns that echo into a duplicate instead of a customer message."""
    message_id = ((result or {}).get("data") or {}).get("wa_message_id") if delivery_accepted(SOURCE, result) else None
    if (channel or {}).get("id") and message_id:
        try:
            claim_whatchimp_message(channel["id"], message_id)
        except Exception as error:
            logging.warning("Could not record a sent WhatChimp message (%s)", type(error).__name__)
    return result


def _paused(conversation, chatbot_id):
    return is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation)


def _save_bot_reply(conversation, text, error):
    save_message(conversation_id=conversation["id"], sender_type="bot", message_text=text, message_type="text",
                 delivery_status="failed" if error else "sent", ai_generated=True, retry_count=0,
                 last_error=error[:1000] if error else None)


def _process_claimed_message(parsed, channel, progress):
    chatbot_id = channel["chatbot_id"]
    customer_phone = parsed["customer_phone"]
    message_text = parsed.get("message_text")
    conversation = get_or_create_conversation(chatbot_id=chatbot_id, customer_phone=customer_phone,
                                              customer_name=parsed.get("customer_name"), source_channel=SOURCE,
                                              **channel_identity(channel, SOURCE))
    paused = _paused(conversation, chatbot_id)
    progress["started"] = True
    save_message(conversation_id=conversation["id"], sender_type="customer",
                 message_text=message_text or "[Unsupported WhatChimp message type]",
                 message_type="text" if message_text else "unsupported",
                 platform_message_id=parsed["message_id"], delivery_status="received", ai_generated=False)
    if paused:
        return

    if not message_text:
        with conversation_delivery_lock(conversation["id"]):
            channel = get_bound_channel(conversation)
            if _paused(conversation, chatbot_id):
                return
            result = remember_sent(channel, send_whatchimp_text(channel["api_token"], channel["phone_number_id"],
                                                                customer_phone, TEXT_ONLY_REPLY))
        _save_bot_reply(conversation, TEXT_ONLY_REPLY,
                        None if delivery_accepted(SOURCE, result) else (result or {}).get("error") or "WhatChimp send failed")
        return

    reply = generate_response(message_text, customer_phone, chatbot_id, source_channel=SOURCE,
                              conversation_id=conversation["id"])
    if reply == "<SILENT_BOT_RESPONSE>":
        logging.info("AI is silenced (conversation escalated to human).")
        return

    error = _deliver_reply(conversation, chatbot_id, customer_phone, reply)
    if error == "stopped":
        return
    _save_bot_reply(conversation, reply, error)
    if not error and not _paused(conversation, chatbot_id):
        dispatch_media_after_reply(message_text, chatbot_id, SOURCE, get_bound_channel(conversation), customer_phone,
                                   conversation=conversation)


def _deliver_reply(conversation, chatbot_id, customer_phone, reply):
    """Send the reply in WhatsApp-sized parts; the last part carries the buttons when it fits.

    Returns None when everything was accepted, "stopped" when a handoff began
    before the first part, otherwise the reason delivery stopped.
    """
    text, labels = split_reply_buttons(reply)
    parts = split_wasender_reply(text)
    buttons_sent = False
    for index, part in enumerate(parts):
        with_buttons = bool(labels) and index == len(parts) - 1 and len(part) <= BUTTON_BODY_LIMIT
        with conversation_delivery_lock(conversation["id"]):
            channel = get_bound_channel(conversation)
            if not automatic_reply_allowed(conversation, reply, paused=_paused(conversation, chatbot_id)):
                return "stopped" if index == 0 else "Automatic reply stopped because human handoff is active."
            if with_buttons:
                result = send_whatchimp_buttons(channel["api_token"], channel["phone_number_id"], customer_phone, part, labels)
            else:
                result = send_whatchimp_text(channel["api_token"], channel["phone_number_id"], customer_phone, part)
            remember_sent(channel, result)
        if not delivery_accepted(SOURCE, result):
            return (result or {}).get("error") or "WhatChimp did not confirm delivery."
        buttons_sent = buttons_sent or with_buttons

    if labels and not buttons_sent:
        # The last part was too long to carry buttons; offer them on their own.
        with conversation_delivery_lock(conversation["id"]):
            channel = get_bound_channel(conversation)
            if automatic_reply_allowed(conversation, reply, paused=_paused(conversation, chatbot_id)):
                result = remember_sent(channel, send_whatchimp_buttons(channel["api_token"], channel["phone_number_id"],
                                                                       customer_phone, BUTTON_FALLBACK_BODY, labels))
                if not delivery_accepted(SOURCE, result):
                    logging.warning("WhatChimp did not accept the reply buttons.")
    return None
