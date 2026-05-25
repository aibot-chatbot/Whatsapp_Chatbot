import logging
import os
import re
import requests
from datetime import datetime, timezone, timedelta

from app.services.ai_router import generate_response
from app.database.conversation_repository import get_or_create_conversation
from app.database.message_repository import save_message
from app.database.wasender_channel_repository import get_wasender_channel_by_secret
from app.database.processed_wasender_message_repository import (
    is_wasender_message_processed,
    save_processed_wasender_message,
)


WASENDER_BASE_URL = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com")


def get_retry_schedule(delay_seconds: int = 60):
    now = datetime.now(timezone.utc)
    return now.isoformat(), (now + timedelta(seconds=delay_seconds)).isoformat()


def normalize_wasender_recipient(value: str):
    """
    Convert Wasender sender ID into a format suitable for /api/send-message.
    Example:
    60123456789@s.whatsapp.net -> +60123456789
    +60123456789 -> +60123456789
    group@g.us -> group@g.us
    """
    if not value:
        return ""

    value = str(value).strip()

    # Keep group/community JID as-is
    if "@g.us" in value or "@newsletter" in value:
        return value

    # Convert WhatsApp personal JID to phone number
    if "@s.whatsapp.net" in value:
        value = value.split("@")[0]

    # Remove all characters except digits and +
    value = re.sub(r"[^\d+]", "", value)

    if not value:
        return ""

    if value.startswith("+"):
        return value

    return f"+{value}"


def extract_wasender_message(payload: dict):
    """
    Extract useful message data from Wasender webhook payload.
    Based on messages.received payload style.
    """
    event = payload.get("event")

    data = payload.get("data") or {}
    message_data = data.get("messages") or data.get("message") or {}

    key = message_data.get("key") or {}

    message_id = (
        key.get("id")
        or message_data.get("id")
        or payload.get("id")
    )

    from_me = key.get("fromMe", False)

    sender_raw = (
        key.get("cleanedSenderPn")
        or key.get("senderPn")
        or key.get("remoteJid")
        or message_data.get("from")
        or message_data.get("sender")
    )

    remote_jid = key.get("remoteJid") or sender_raw

    message_text = (
        message_data.get("messageBody")
        or (message_data.get("message") or {}).get("conversation")
        or message_data.get("text")
        or payload.get("messageBody")
        or payload.get("text")
    )

    customer_name = (
        message_data.get("pushName")
        or message_data.get("senderName")
        or data.get("pushName")
        or data.get("senderName")
    )

    return {
        "event": event,
        "message_id": str(message_id) if message_id else None,
        "from_me": bool(from_me),
        "sender_raw": sender_raw,
        "remote_jid": remote_jid,
        "customer_phone": normalize_wasender_recipient(sender_raw or remote_jid),
        "message_text": message_text.strip() if isinstance(message_text, str) else None,
        "customer_name": customer_name,
    }


def send_wasender_text_message(api_key: str, to: str, text: str):
    """
    Send text reply back to WhatsApp using WasenderAPI.
    Returns:
    {
        "success": True/False,
        "data": response_json_or_none,
        "error": error_message_or_none
    }
    """
    if not api_key:
        error = "Wasender API key is missing."
        logging.error(error)
        return {"success": False, "data": None, "error": error}

    recipient = normalize_wasender_recipient(to)

    if not recipient:
        error = "Wasender recipient is missing."
        logging.error(error)
        return {"success": False, "data": None, "error": error}

    if not text:
        text = "Sorry, I’m having trouble replying right now."

    url = f"{WASENDER_BASE_URL.rstrip('/')}/api/send-message"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "to": recipient,
        "text": text,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)

        try:
            response_data = response.json()
        except ValueError:
            response_data = None

        if response.status_code >= 400:
            error = f"Wasender send message failed: {response.status_code} {response.text}"
            logging.error(error)
            return {
                "success": False,
                "data": response_data,
                "error": error,
            }

        logging.info(f"Wasender send message success: {response.status_code}")

        return {
            "success": True,
            "data": response_data,
            "error": None,
        }

    except requests.Timeout:
        error = "Timeout occurred while sending Wasender message"
        logging.error(error)
        return {"success": False, "data": None, "error": error}

    except requests.RequestException as e:
        error = f"Failed to send Wasender message: {e}"
        logging.error(error)
        return {"success": False, "data": None, "error": error}


def split_wasender_reply(text: str, max_length: int = 3500):
    """
    Split long AI replies into safer WhatsApp-sized messages.
    """
    if not text:
        return ["Sorry, I’m having trouble replying right now."]

    if len(text) <= max_length:
        return [text]

    parts = []
    current = ""

    paragraphs = text.split("\n\n")

    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_length:
            current += ("\n\n" if current else "") + paragraph
        else:
            if current:
                parts.append(current)
            current = paragraph

    if current:
        parts.append(current)

    return parts


def process_wasender_webhook(payload: dict, webhook_secret: str):
    """
    Process incoming WasenderAPI webhook.
    """
    channel = get_wasender_channel_by_secret(webhook_secret)

    if not channel:
        logging.error(f"No active Wasender channel found for secret: {webhook_secret}")
        return

    wasender_channel_id = channel["id"]
    chatbot_id = channel["chatbot_id"]
    api_key = channel["api_key"]

    parsed = extract_wasender_message(payload)

    event = parsed.get("event")
    message_id = parsed.get("message_id")
    from_me = parsed.get("from_me")
    customer_phone = parsed.get("customer_phone")
    message_text = parsed.get("message_text")
    customer_name = parsed.get("customer_name")

    logging.info(f"Wasender webhook event: {event}")
    logging.info(f"Wasender parsed message: {parsed}")

    # Only handle incoming message event
    if event and event != "messages.received":
        logging.info(f"Wasender event ignored: {event}")
        return

    # Avoid replying to own outgoing messages
    if from_me:
        logging.info("Wasender message is from bot account. Ignored.")
        return

    if not message_id:
        logging.warning("Wasender message missing message_id. Ignored.")
        return

    if is_wasender_message_processed(wasender_channel_id, message_id):
        logging.info(f"Duplicate Wasender message ignored: {message_id}")
        return

    if not customer_phone:
        logging.warning("Wasender message missing sender phone. Ignored.")
        save_processed_wasender_message(wasender_channel_id, message_id)
        return

    conversation = get_or_create_conversation(
        chatbot_id=chatbot_id,
        customer_phone=customer_phone,
        customer_name=customer_name,
        source_channel="wasender",
    )

    # Handle non-text messages safely
    if not message_text:
        save_message(
            conversation_id=conversation["id"],
            sender_type="customer",
            message_text="[Unsupported Wasender message type]",
            message_type="unsupported",
            platform_message_id=message_id,
            delivery_status="received",
            ai_generated=False,
        )

        reply = (
            "I received your message, but I can only reply to text messages for now. "
            "Please type your question and I’ll help you."
        )

        send_result = send_wasender_text_message(api_key, customer_phone, reply)
        send_ok = send_result and send_result.get("success")

        first_failed_at = None
        next_retry_at = None
        last_error = None

        if not send_ok:
            first_failed_at, next_retry_at = get_retry_schedule(delay_seconds=60)
            last_error = send_result.get("error") if send_result else "WasenderAPI send failed"

        save_message(
            conversation_id=conversation["id"],
            sender_type="bot",
            message_text=reply,
            message_type="text",
            delivery_status="sent" if send_ok else "failed",
            ai_generated=True,
            retry_count=0,
            next_retry_at=next_retry_at,
            first_failed_at=first_failed_at,
            last_error=last_error,
        )

        save_processed_wasender_message(wasender_channel_id, message_id)
        return

    save_message(
        conversation_id=conversation["id"],
        sender_type="customer",
        message_text=message_text,
        message_type="text",
        platform_message_id=message_id,
        delivery_status="received",
        ai_generated=False,
    )

    reply = generate_response(
        message_text,
        customer_phone,
        chatbot_id,
        source_channel="wasender",
    )

    send_success = True
    send_errors = []

    for reply_part in split_wasender_reply(reply):
        send_result = send_wasender_text_message(api_key, customer_phone, reply_part)

        if not send_result or not send_result.get("success"):
            send_success = False
            send_errors.append(
                send_result.get("error") if send_result else "WasenderAPI send failed"
            )

    first_failed_at = None
    next_retry_at = None
    last_error = None

    if not send_success:
        first_failed_at, next_retry_at = get_retry_schedule(delay_seconds=60)
        last_error = " | ".join(send_errors)[:1000] if send_errors else "WasenderAPI send failed"

    save_message(
        conversation_id=conversation["id"],
        sender_type="bot",
        message_text=reply,
        message_type="text",
        delivery_status="sent" if send_success else "failed",
        ai_generated=True,
        retry_count=0,
        next_retry_at=next_retry_at,
        first_failed_at=first_failed_at,
        last_error=last_error,
    )

    save_processed_wasender_message(wasender_channel_id, message_id)