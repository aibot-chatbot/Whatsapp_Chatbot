import logging
import requests

from app.services.ai_router import generate_response
from app.database.conversation_repository import (
    get_or_create_platform_conversation,
    update_conversation_phone_by_platform,
)
from app.database.message_repository import save_message
from app.database.telegram_channel_repository import get_telegram_channel_by_secret
from app.database.processed_telegram_update_repository import (
    is_telegram_update_processed,
    save_processed_telegram_update,
)


def send_telegram_message(bot_token: str, chat_id: str, text: str):
    """
    Send text reply back to Telegram.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logging.info(f"Telegram send message success: {response.status_code}")
        return response.json()

    except requests.Timeout:
        logging.error("Timeout occurred while sending Telegram message")
        return None

    except requests.RequestException as e:
        logging.error(f"Failed to send Telegram message: {e}")
        return None


def send_telegram_contact_request(bot_token: str, chat_id: str):
    """
    Ask Telegram user to share phone number.
    User must click the button before Telegram sends contact.phone_number.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": (
            "Hi, before we continue, please share your phone number "
            "so our staff can contact you."
        ),
        "reply_markup": {
            "keyboard": [[
                {
                    "text": "Share Phone Number",
                    "request_contact": True
                }
            ]],
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logging.info(f"Telegram contact request sent: {response.status_code}")
        return response.json()

    except requests.Timeout:
        logging.error("Timeout occurred while sending Telegram contact request")
        return None

    except requests.RequestException as e:
        logging.error(f"Failed to send Telegram contact request: {e}")
        return None


def get_telegram_customer_name(from_user: dict):
    """
    Build readable Telegram customer name.
    """
    if not from_user:
        return None

    first_name = from_user.get("first_name", "")
    last_name = from_user.get("last_name", "")
    username = from_user.get("username", "")

    full_name = f"{first_name} {last_name}".strip()

    if full_name and username:
        return f"{full_name} (@{username})"

    if full_name:
        return full_name

    if username:
        return f"@{username}"

    return None


def split_telegram_reply(text: str, max_length: int = 3900):
    """
    Telegram message limit is around 4096 characters.
    Keep lower limit for safety.
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


def process_telegram_update(update: dict, webhook_secret: str):
    """
    Process incoming Telegram webhook update.
    """
    channel = get_telegram_channel_by_secret(webhook_secret)

    if not channel:
        logging.error(f"No active Telegram channel found for secret: {webhook_secret}")
        return

    telegram_channel_id = channel["id"]
    chatbot_id = channel["chatbot_id"]
    bot_token = channel["bot_token"]

    update_id = update.get("update_id")

    if is_telegram_update_processed(telegram_channel_id, update_id):
        logging.info(f"Duplicate Telegram update ignored: {update_id}")
        return

    message = update.get("message")

    if not message:
        logging.info("Telegram update has no message. Ignored.")
        save_processed_telegram_update(telegram_channel_id, update_id)
        return

    chat = message.get("chat", {})
    from_user = message.get("from", {})

    chat_id = chat.get("id")
    message_id = message.get("message_id")
    message_text = message.get("text")
    contact = message.get("contact")
    customer_name = get_telegram_customer_name(from_user)

    if not chat_id:
        logging.warning("Telegram message missing chat_id. Ignored.")
        save_processed_telegram_update(telegram_channel_id, update_id)
        return

    customer_key = str(chat_id)
    platform_user_id = str(from_user.get("id") or chat_id)

    conversation = get_or_create_platform_conversation(
        chatbot_id=chatbot_id,
        platform_user_id=platform_user_id,
        customer_name=customer_name,
        source_channel="telegram",
        customer_phone=None,
    )

    # Handle phone number shared from Telegram contact button
    if contact:
        phone_number = contact.get("phone_number")
        contact_user_id = contact.get("user_id")

        if contact_user_id and str(contact_user_id) != platform_user_id:
            reply = "Please share your own phone number using the button."

            save_message(
                conversation_id=conversation["id"],
                sender_type="bot",
                message_text=reply,
                message_type="text",
                delivery_status="sent",
                ai_generated=False,
            )

            send_telegram_message(bot_token, customer_key, reply)
            send_telegram_contact_request(bot_token, customer_key)
            save_processed_telegram_update(telegram_channel_id, update_id)
            return

        if not phone_number:
            reply = "I could not read your phone number. Please tap Share Phone Number again."

            save_message(
                conversation_id=conversation["id"],
                sender_type="bot",
                message_text=reply,
                message_type="text",
                delivery_status="sent",
                ai_generated=False,
            )

            send_telegram_message(bot_token, customer_key, reply)
            send_telegram_contact_request(bot_token, customer_key)
            save_processed_telegram_update(telegram_channel_id, update_id)
            return

        save_message(
            conversation_id=conversation["id"],
            sender_type="customer",
            message_text=f"[Phone number shared: {phone_number}]",
            message_type="contact",
            platform_message_id=str(message_id),
            delivery_status="received",
            ai_generated=False,
        )

        conversation = update_conversation_phone_by_platform(
            chatbot_id=chatbot_id,
            platform_user_id=platform_user_id,
            customer_phone=phone_number,
            customer_name=customer_name,
            source_channel="telegram",
        )

        reply = "Thanks, your phone number has been saved. How can I help you today?"

        save_message(
            conversation_id=conversation["id"],
            sender_type="bot",
            message_text=reply,
            message_type="text",
            delivery_status="sent",
            ai_generated=False,
        )

        send_telegram_message(bot_token, customer_key, reply)
        save_processed_telegram_update(telegram_channel_id, update_id)
        return

    # Handle non-text Telegram messages safely
    if not message_text:
        logging.info("Unsupported Telegram message type received.")

        save_message(
            conversation_id=conversation["id"],
            sender_type="customer",
            message_text="[Unsupported Telegram message type]",
            message_type="unsupported",
            platform_message_id=str(message_id),
            delivery_status="received",
            ai_generated=False,
        )

        reply = (
            "I received your message, but I can only reply to text messages for now. "
            "Please type your question and I’ll help you."
        )

        save_message(
            conversation_id=conversation["id"],
            sender_type="bot",
            message_text=reply,
            message_type="text",
            delivery_status="sent",
            ai_generated=True,
        )

        send_telegram_message(bot_token, customer_key, reply)
        save_processed_telegram_update(telegram_channel_id, update_id)
        return

    save_message(
        conversation_id=conversation["id"],
        sender_type="customer",
        message_text=message_text,
        message_type="text",
        platform_message_id=str(message_id),
        delivery_status="received",
        ai_generated=False,
    )

    # Stop normal AI reply until Telegram user shares phone number
    if not conversation.get("customer_phone"):
        reply = (
            "Hi, before we continue, please share your phone number "
            "so our staff can contact you."
        )

        save_message(
            conversation_id=conversation["id"],
            sender_type="bot",
            message_text=reply,
            message_type="text",
            delivery_status="sent",
            ai_generated=False,
        )

        send_telegram_contact_request(bot_token, customer_key)
        save_processed_telegram_update(telegram_channel_id, update_id)
        return

    reply = generate_response(
        message_text,
        customer_key,
        chatbot_id,
        source_channel="telegram",
    )

    for reply_part in split_telegram_reply(reply):
        send_telegram_message(bot_token, customer_key, reply_part)

    save_message(
        conversation_id=conversation["id"],
        sender_type="bot",
        message_text=reply,
        message_type="text",
        delivery_status="sent",
        ai_generated=True,
    )

    save_processed_telegram_update(telegram_channel_id, update_id)