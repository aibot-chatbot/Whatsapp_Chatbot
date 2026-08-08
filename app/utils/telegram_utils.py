import logging
import requests
import re

from app.services.ai_router import generate_response
from app.database.bot_repository import get_bot_by_id
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
from app.services.media_send_service import dispatch_media_after_reply
from app.utils.message_style_utils import parse_buttons_tag, format_for_telegram_markdown


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    reply_markup: dict = None,
    parse_mode: str = None,
):
    """
    Send text reply back to Telegram, optionally with inline buttons and/or
    MarkdownV2 formatting.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    if parse_mode:
        payload["parse_mode"] = parse_mode

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
    callback_query = update.get("callback_query")

    if callback_query:
        message = callback_query.get("message")
        chat = message.get("chat", {}) if message else {}
        from_user = callback_query.get("from", {})
        chat_id = chat.get("id")
        message_id = message.get("message_id") if message else None
        message_text = callback_query.get("data")
        contact = None
        customer_name = get_telegram_customer_name(from_user)

        # Answer callback query to stop the loading indicator on the button
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_query.get("id")},
            timeout=5
        ).json()

        # Show typing indicator so the user knows the bot is processing their click
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5
        )

    elif message:
        chat = message.get("chat", {})
        from_user = message.get("from", {})
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        message_text = message.get("text")
        contact = message.get("contact")
        customer_name = get_telegram_customer_name(from_user)
    else:
        logging.info("Telegram update has no message or callback_query. Ignored.")
        save_processed_telegram_update(telegram_channel_id, update_id)
        return

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
        # Check if they manually typed a phone number instead of using the button
        cleaned_text = re.sub(r'[\D]', '', message_text)
        if 8 <= len(cleaned_text) <= 15:
            phone_number = cleaned_text
            if message_text.strip().startswith('+'):
                phone_number = '+' + phone_number
                
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

        reply = (
            "Please tap the 'Share Phone Number' button below, or type your phone number manually to continue."
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

    if reply == "<SILENT_BOT_RESPONSE>":
        logging.info("AI is silenced (conversation escalated to human).")
        save_processed_telegram_update(telegram_channel_id, update_id)
        return

    # Read message style settings from the bot record (safe default: enabled)
    bot_record = get_bot_by_id(chatbot_id) or {}
    buttons_enabled = bot_record.get("telegram_buttons_enabled", True)
    markdown_enabled = bot_record.get("telegram_markdown_enabled", True)

    # Parse [BUTTONS: A | B | C] tag out of the reply FIRST so the tag is never
    # processed by the markdown formatter (which would escape its characters and
    # prevent the buttons from rendering).
    clean_reply, button_labels = parse_buttons_tag(reply)

    # Build inline keyboard if buttons are present and enabled
    inline_markup = None
    if buttons_enabled and button_labels:
        inline_markup = {
            "inline_keyboard": [
                [{"text": lbl, "callback_data": lbl}]
                for lbl in button_labels
            ]
        }

    # Apply Telegram MarkdownV2 formatting to the clean text only
    parse_mode = None
    if markdown_enabled:
        try:
            clean_reply = format_for_telegram_markdown(clean_reply)
            parse_mode = "MarkdownV2"
        except Exception as fmt_err:
            logging.warning("Telegram markdown formatting failed, sending plain text: %s", fmt_err)
            # Recover the clean text without the tag and send as plain text
            clean_reply, _ = parse_buttons_tag(reply)
            parse_mode = None

    parts = split_telegram_reply(clean_reply)
    for i, reply_part in enumerate(parts):
        # Send inline keyboard only with the last part
        markup = inline_markup if (i == len(parts) - 1) else None
        result = send_telegram_message(
            bot_token,
            customer_key,
            reply_part,
            reply_markup=markup,
            parse_mode=parse_mode,
        )
        # If formatted send fails, retry as plain text (Telegram rejects bad MarkdownV2)
        if result is None and parse_mode:
            logging.warning("Telegram MarkdownV2 send failed, retrying as plain text")
            send_telegram_message(
                bot_token,
                customer_key,
                reply_part,
                reply_markup=markup,
                parse_mode=None,
            )


    save_message(
        conversation_id=conversation["id"],
        sender_type="bot",
        message_text=reply,
        message_type="text",
        delivery_status="sent",
        ai_generated=True,
    )

    save_processed_telegram_update(telegram_channel_id, update_id)

    # Try sending any configured media attachments that match the user's message
    dispatch_media_after_reply(message_text, chatbot_id, "telegram", channel, customer_key)