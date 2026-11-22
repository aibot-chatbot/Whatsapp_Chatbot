import logging
from flask import current_app, jsonify
import json
import requests
import re

from app.services.ai_router import generate_response
from app.services.channel_delivery_service import (
    ConsentPersistenceError,
    handle_marketing_reply,
    marketing_reply_kind,
    save_inbound_with_consent_evidence,
)
from app.database.bot_repository import get_bot_by_id
from app.database.conversation_repository import get_or_create_conversation
from app.database.message_repository import save_message
from app.services import follow_up_service
from app.database.processed_message_repository import claim_processed_message, release_processed_message_claim
from app.database.whatsapp_channel_repository import get_whatsapp_channel_by_phone_number_id
from app.services.workflow_tracker import update_workflow_state
from app.services.media_send_service import dispatch_media_after_reply
from app.services.channel_delivery_service import channel_identity, validate_channel, get_bound_channel, delivery_accepted, automatic_reply_allowed, ChannelDeliveryError, resume_ai_after_staff_idle
from app.database.agent_action_repository import is_conversation_escalated
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.utils.message_style_utils import parse_buttons_tag, format_for_whatsapp_markdown


def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )


def get_interactive_button_message(recipient: str, text: str, buttons: list) -> str:
    """Build a WhatsApp interactive quick-reply button payload.

    Args:
        recipient: The WhatsApp phone number (wa_id).
        text: The message body text (without the [BUTTONS:] tag).
        buttons: List of button label strings (max 3, each ≤20 chars).

    Returns:
        JSON string ready to POST to the Meta Graph API.
    """
    button_objects = []
    for raw_label in buttons or []:
        if raw_label is None:
            continue
        label = str(raw_label).strip()[:20]
        if not label:
            continue
        button_objects.append(
            {
                "type": "reply",
                "reply": {"id": f"btn_{len(button_objects)}", "title": label},
            }
        )
        if len(button_objects) == 3:
            break

    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": button_objects},
            },
        }
    )


def get_interactive_button_message_input(recipient: str, text: str, buttons: list) -> str:
    return get_interactive_button_message(recipient, text, buttons)



def send_message(data, channel=None):
    access_token = channel.get("access_token") if channel else None
    phone_number_id = channel.get("phone_number_id") if channel else None

    if not access_token or not phone_number_id:
        return jsonify({"status": "error", "message": "Verified channel credentials are required"}), 409
    if isinstance(data, dict):
        data = json.dumps(data)

    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{phone_number_id}/messages"

    try:
        response = requests.post(url, data=data, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.Timeout:
        logging.error("Timeout occurred while sending message")
        return jsonify({"status": "error", "message": "Request timed out"}), 408
    except requests.RequestException as e:
        logging.error("WhatsApp send failed (%s)", type(e).__name__)
        return jsonify({"status": "error", "message": "Provider did not confirm delivery"}), 502
    else:
        log_http_response(response)
        return response


def process_text_for_whatsapp(text):
    pattern = r"\【.*?\】"
    text = re.sub(pattern, "", text).strip()

    pattern = r"\*\*(.*?)\*\*"
    replacement = r"*\1*"
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text


def process_whatsapp_message(body):
    value = body["entry"][0]["changes"][0]["value"]

    # Get Meta phone number ID from webhook metadata
    phone_number_id = value.get("metadata", {}).get("phone_number_id")

    # Find which chatbot this WhatsApp number belongs to
    channel = get_whatsapp_channel_by_phone_number_id(phone_number_id)

    if not channel:
        logging.error(f"No active WhatsApp channel found for phone_number_id: {phone_number_id}")
        return

    chatbot_id = channel["chatbot_id"]
    try:
        from app.services.company_status_service import ensure_company_operational
        ensure_company_operational(channel.get("company_id"))
    except Exception:
        logging.info("WhatsApp webhook ignored because company is not operational.")
        return

    wa_id = value["contacts"][0]["wa_id"]
    customer_name = value["contacts"][0].get("profile", {}).get("name")

    message = value["messages"][0]
    message_id = message["id"]

    validate_channel(channel, "whatsapp", chatbot_id)
    if not claim_processed_message(chatbot_id, message_id):
        logging.info("Duplicate WhatsApp message ignored")
        return
    progress = {"started": False}
    try:
        return _process_claimed_whatsapp_message(value, channel, progress)
    except Exception as error:
        if not progress["started"] or isinstance(error, ConsentPersistenceError):
            release_processed_message_claim(chatbot_id, message_id)
        raise


def _process_claimed_whatsapp_message(value, channel, progress):
    chatbot_id = channel["chatbot_id"]
    wa_id = value["contacts"][0]["wa_id"]
    customer_name = value["contacts"][0].get("profile", {}).get("name")
    message = value["messages"][0]
    message_id = message["id"]
    # Handle non-text messages safely
    message_type = message.get("type", "unknown")

    if message_type not in ("text", "interactive"):

        logging.info(f"Unsupported WhatsApp message type: {message_type}")

        conversation = get_or_create_conversation(
            chatbot_id=chatbot_id,
            customer_phone=wa_id,
            customer_name=customer_name,
            source_channel="whatsapp",
            **channel_identity(channel, "whatsapp"),
        )

        follow_up_service.stop_for_customer_reply(conversation, channel.get("company_id"))
        progress["started"] = True
        save_message(
            conversation_id=conversation["id"],
            sender_type="customer",
            message_text=f"[Unsupported message type: {message_type}]",
            message_type=message_type,
            platform_message_id=message_id,
            delivery_status="received",
            ai_generated=False,
        )

        if message_type == "image":
            reply = (
                "I received your image, but I can only read text messages for now. "
                "Please type your question or copy the text from the image, and I’ll help you."
            )
        else:
            reply = (
                f"I received your {message_type}, but I can only reply to text messages for now. "
                "Please type your question and I’ll help you."
            )

        with conversation_delivery_lock(conversation["id"]):
            channel = get_bound_channel(conversation)
            resume_ai_after_staff_idle(conversation, chatbot_id)
            if is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
                return
            result = send_message(get_text_message_input(wa_id, reply), channel)
        accepted = delivery_accepted("whatsapp", result)
        save_message(conversation_id=conversation["id"], sender_type="bot", message_text=reply,
                     message_type="text", delivery_status="sent" if accepted else "failed", ai_generated=False,
                     last_error=None if accepted else "Provider did not confirm delivery; review before retrying.")
        return

    if message_type == "interactive":
        interactive_data = message.get("interactive", {})
        if interactive_data.get("type") == "button_reply":
            message_body = interactive_data.get("button_reply", {}).get("title", "")
        elif interactive_data.get("type") == "list_reply":
            message_body = interactive_data.get("list_reply", {}).get("title", "")
        else:
            message_body = ""
    else:
        message_body = message["text"]["body"]

    conversation = get_or_create_conversation(
        chatbot_id=chatbot_id,
        customer_phone=wa_id,
        customer_name=customer_name,
        source_channel="whatsapp",
        **channel_identity(channel, "whatsapp"),
    )

    follow_up_service.stop_for_customer_reply(conversation, channel.get("company_id"))
    progress["started"] = True
    kind = marketing_reply_kind(message_body)
    customer_message = save_inbound_with_consent_evidence(
        kind, channel.get("company_id"), save_message,
        conversation_id=conversation["id"],
        sender_type="customer",
        message_text=message_body,
        message_type="text",
        platform_message_id=message_id,
        delivery_status="received",
        ai_generated=False,
    )

    if handle_marketing_reply(conversation, channel.get("company_id"), kind, customer_message):
        return
    resume_ai_after_staff_idle(conversation, chatbot_id)
    if is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
        return

    update_workflow_state(chatbot_id, "RECEIVING", message_body, wa_id)
    update_workflow_state(chatbot_id, "AI_GENERATING", message_body, wa_id)

    response = generate_response(
        message_body,
        wa_id,
        chatbot_id,
        source_channel="whatsapp",
        conversation_id=conversation["id"],
        **({"message_id": customer_message["id"]}
           if isinstance(customer_message, dict) and customer_message.get("id") is not None else {}),
    )

    if response == "<SILENT_BOT_RESPONSE>":
        logging.info("AI is silenced (conversation escalated to human).")
        update_workflow_state(chatbot_id, "COMPLETED", "<SILENT_BOT_RESPONSE>", wa_id)
        return

    # Read message style settings from the bot record (safe default: enabled)
    bot_record = get_bot_by_id(chatbot_id) or {}
    buttons_enabled = bot_record.get("whatsapp_buttons_enabled", True)
    markdown_enabled = bot_record.get("whatsapp_markdown_enabled", True)

    # Parse [BUTTONS: A | B | C] tag out of the reply FIRST so the tag is never
    # processed by the markdown formatter (which could mangle or strip it).
    clean_response, button_labels = parse_buttons_tag(response)

    # Apply WhatsApp markdown formatting to the clean text only
    if markdown_enabled:
        clean_response = format_for_whatsapp_markdown(clean_response)
    else:
        clean_response = process_text_for_whatsapp(clean_response)


    update_workflow_state(chatbot_id, "SENDING", clean_response, wa_id)
    if buttons_enabled and button_labels:
        data = get_interactive_button_message(wa_id, clean_response, button_labels)
    else:
        data = get_text_message_input(wa_id, clean_response)
    try:
        with conversation_delivery_lock(conversation["id"]):
            channel = get_bound_channel(conversation)
            if not automatic_reply_allowed(conversation, response, paused=is_conversation_escalated(
                    conversation["id"], chatbot_id, conversation=conversation)):
                update_workflow_state(chatbot_id, "COMPLETED", "<SILENT_BOT_RESPONSE>", wa_id)
                return
            result = send_message(data, channel)
    except ChannelDeliveryError as error:
        # The number was replaced or disconnected between this customer's message
        # arriving and the reply going out. The inbound dedup claim is already
        # held, so letting this propagate would answer 500, Meta would redeliver,
        # claim_processed_message would drop it as a duplicate, and the customer's
        # message would disappear with no bot row and no error anywhere. Record
        # the failed reply instead, so staff see a broken thread they can resend.
        save_message(conversation_id=conversation["id"], sender_type="bot", message_text=response,
                     message_type="text", delivery_status="failed", ai_generated=True,
                     last_error=error.code)
        update_workflow_state(chatbot_id, "FAILED", clean_response, wa_id)
        return
    accepted = delivery_accepted("whatsapp", result)
    save_message(conversation_id=conversation["id"], sender_type="bot", message_text=response,
                 message_type="text", delivery_status="sent" if accepted else "failed", ai_generated=True,
                 last_error=None if accepted else "Provider did not confirm delivery; review before retrying.")
    update_workflow_state(chatbot_id, "COMPLETED" if accepted else "FAILED", clean_response, wa_id)
    if accepted and not is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
        dispatch_media_after_reply(message_body, chatbot_id, "meta", get_bound_channel(conversation), wa_id,
                                   conversation=conversation)


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
