import logging
import requests
import re
import threading

from app.services.ai_router import generate_response
from app.services import follow_up_service
from app.services.channel_delivery_service import (
    ConsentPersistenceError,
    handle_marketing_reply,
    marketing_reply_kind,
    maybe_ask_marketing_consent,
    save_inbound_with_consent_evidence,
)
from app.services.billing_guard import BillingLimitError
from app.database.bot_repository import get_bot_by_id
from app.database.conversation_repository import (
    get_or_create_platform_conversation,
    update_conversation_phone_by_platform,
)
from app.database.message_repository import save_message
from app.database.telegram_channel_repository import get_telegram_channel_by_secret
from app.database.processed_telegram_update_repository import (
    claim_telegram_update,
    release_telegram_update_claim,
)
from app.services.media_send_service import dispatch_media_after_reply
from app.services.channel_delivery_service import channel_identity, validate_channel, get_bound_channel, delivery_accepted, automatic_reply_allowed, resume_ai_after_staff_idle
from app.database.agent_action_repository import is_conversation_escalated
from app.services.turn_cache import turn_cache
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.utils.message_style_utils import parse_buttons_tag, format_for_telegram_markdown


BILLING_LIMIT_CUSTOMER_REPLY = (
    "This chatbot is temporarily unavailable. Please try again later."
)


class TelegramChannelNotReadyError(RuntimeError):
    """Tell Telegram to retain an update until channel activation completes."""


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
        # Request exceptions can include the bot token from the Telegram URL.
        logging.error("Failed to send Telegram message (%s)", type(e).__name__)
        if e.response is not None and 400 <= e.response.status_code < 500:
            try:
                error = e.response.json()
                description = str(error.get("description", "")).lower()
                if e.response.status_code == 400 and ("parse entities" in description or "parse entity" in description):
                    return {"ok": False, "format_rejected": True}
                if error.get("ok") is False:
                    return {"ok": False}
            except (ValueError, TypeError, AttributeError):
                pass
        return None


def post_telegram_typing(bot_token: str, chat_id):
    """Show "typing..." in the chat. Cosmetic, so a failure is logged, never raised."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception as error:
        # Type name only: the request URL, and so the exception message, embeds the bot token.
        logging.info("Telegram typing indicator failed (%s)", type(error).__name__)


def show_telegram_typing(bot_token: str, chat_id):
    """Start the typing indicator without delaying the reply it covers.

    On the reply thread the round trip to api.telegram.org would add to the very
    wait it is meant to soften. Telegram clears the status after ~5 s or when the
    bot's message arrives.
    """
    threading.Thread(
        target=post_telegram_typing,
        args=(bot_token, chat_id),
        name="telegram-typing",
        daemon=True,
    ).start()


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
        logging.error("Failed to send Telegram contact request (%s)", type(e).__name__)
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


def assert_telegram_channel_ready(webhook_secret: str) -> dict | None:
    """Raise if the channel is reserved but not yet activated; otherwise return it.

    Split out of :func:`process_telegram_update` so the route can resolve this
    on the request thread. The resulting 409 is load-bearing: it makes Telegram
    RETAIN the update and redeliver it while a new setup is still pending, so a
    failed setup does not answer alongside the old bot. Acknowledging with 200
    first would discard that update permanently.

    An unknown secret is NOT a readiness failure -- process_telegram_update
    logs and drops it, and asking Telegram to retry forever on a retired
    webhook is the behaviour this check exists to avoid.

    Returns the channel (None for an unknown secret) so the route can queue the
    update in the lane of the company that owns the channel.
    """
    channel = get_telegram_channel_by_secret(webhook_secret)

    if not channel:
        return None

    if channel.get("connection_status") in {"pending", "failed", "disconnected"}:
        raise TelegramChannelNotReadyError("Telegram channel is not ready to receive updates")

    return channel


def process_telegram_update(update: dict, webhook_secret: str):
    """
    Process incoming Telegram webhook update.
    """
    channel = get_telegram_channel_by_secret(webhook_secret)

    if not channel:
        logging.error("No active Telegram channel found for webhook")
        return

    if channel.get("connection_status") in {"pending", "failed", "disconnected"}:
        # Retain Telegram's update for retry while the provider is reserved but
        # not activated. A failed new setup must not answer alongside the old bot.
        raise TelegramChannelNotReadyError("Telegram channel is not ready to receive updates")

    telegram_channel_id = channel["id"]
    chatbot_id = channel["chatbot_id"]
    bot_token = channel["bot_token"]

    from app.services.company_status_service import (
        CompanyOperationalStatusError,
        ensure_company_operational,
    )

    try:
        ensure_company_operational(channel.get("company_id"))
    except CompanyOperationalStatusError as status_error:
        # A suspended company and a Supabase outage used to produce the same INFO
        # line. The code separates them, and anything this function does not
        # raise now propagates instead of being read as "not operational".
        logging.warning(
            "Telegram webhook ignored: company status check failed (code=%s)",
            status_error.code,
        )
        return

    update_id = update.get("update_id")

    validate_channel(channel, "telegram", chatbot_id)
    if update_id is None:
        raise ValueError("Telegram update_id is required")
    if not claim_telegram_update(telegram_channel_id, update_id):
        logging.info("Duplicate Telegram update ignored")
        return
    progress = {"started": False}
    try:
        with turn_cache():
            return _process_claimed_telegram_update(update, channel, progress)
    except Exception as error:
        # A consent-only retry reuses the saved customer row before any provider call.
        # Once AI billing or delivery starts, a replay could duplicate its effects.
        if not progress["started"] or isinstance(error, ConsentPersistenceError):
            release_telegram_update_claim(telegram_channel_id, update_id)
        raise


def _process_claimed_telegram_update(update, channel, progress):
    chatbot_id = channel["chatbot_id"]
    bot_token = channel["bot_token"]
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

    elif message:
        chat = message.get("chat", {})
        from_user = message.get("from", {})
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        message_text = message.get("text")
        contact = message.get("contact")
    else:
        logging.info("Telegram update has no message or callback_query. Ignored.")
        return

    chat_type = chat.get("type")
    if (isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id == 0
            or chat_type not in {"private", "group", "supergroup"}):
        logging.warning("Telegram message has no supported chat context. Ignored.")
        return

    is_private = chat_type == "private"
    sender_id = from_user.get("id")
    if is_private and (isinstance(sender_id, bool) or not isinstance(sender_id, int)
                       or sender_id <= 0 or sender_id != chat_id):
        logging.warning("Telegram private message has an invalid sender context. Ignored.")
        return

    # A user's private chat and every group are separate conversations. The
    # sender identifies the author, never the history or delivery destination.
    customer_key = str(chat_id)
    platform_user_id = customer_key
    customer_name = (get_telegram_customer_name(from_user) if is_private
                     else chat.get("title") or "Telegram group")

    conversation = get_or_create_platform_conversation(
        chatbot_id=chatbot_id,
        platform_user_id=platform_user_id,
        customer_name=customer_name,
        source_channel="telegram",
        **channel_identity(channel, "telegram"),
        customer_phone=None,
    )
    follow_up_service.stop_for_customer_reply(conversation, channel.get("company_id"))

    if callback_query:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_query.get("id")},
            timeout=5
        ).json()
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5
        )

    kind = marketing_reply_kind(message_text) if not contact else None

    def save_customer_text():
        # Different taps may share the inline keyboard's Telegram message ID.
        event_id = "callback:" + callback_query["id"] if kind and callback_query else str(message_id)
        return save_inbound_with_consent_evidence(
            kind, channel.get("company_id"), save_message,
            conversation_id=conversation["id"],
            sender_type="customer",
            message_text=message_text,
            message_type="text",
            platform_message_id=event_id,
            delivery_status="received",
            ai_generated=False,
        )

    if kind:
        progress["started"] = True
        customer_message = save_customer_text()
        if handle_marketing_reply(conversation, channel.get("company_id"), kind, customer_message):
            return

    if resume_ai_after_staff_idle(conversation, chatbot_id):
        progress["started"] = True
    paused = is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation)
    progress["started"] = True

    from app.services.tuition_telegram_service import handle_tuition_update, is_tuition_update
    trial_update = is_tuition_update(update)

    # Human service pauses every automatic response, including contact prompts.
    if paused:
        if trial_update or kind:
            # Buttons/commands are deterministic controls, not observation input.
            # In particular, never save bearer confirmation tokens as transcript.
            return
        save_message(conversation_id=conversation["id"], sender_type="customer",
                     message_text=message_text or "[Customer attachment]", message_type="text",
                     platform_message_id=str(message_id), delivery_status="received", ai_generated=False)
        return

    # Explicit customer booking controls bypass phone capture and model billing.
    # The adapter rechecks scope, plan, channel and handoff before writes/sends.
    if trial_update and handle_tuition_update(update, conversation=conversation, channel=channel):
        return

    # A participant's contact card is not the group's customer profile.
    if contact and not is_private:
        save_message(conversation_id=conversation["id"], sender_type="customer",
                     message_text="[Contact shared in group]", message_type="contact",
                     platform_message_id=str(message_id), delivery_status="received", ai_generated=False)
        return

    # Telegram's contact request button is a private-chat workflow.
    if contact:
        phone_number = contact.get("phone_number")
        contact_user_id = contact.get("user_id")

        if (isinstance(contact_user_id, bool) or not isinstance(contact_user_id, int)
                or contact_user_id != sender_id):
            reply = "Please share your own phone number using the button."

            _send_recorded_telegram_reply(conversation, channel, customer_key, reply, ai_generated=False)
            _send_recorded_telegram_reply(conversation, channel, customer_key, "Please share your phone number using the button.", contact_request=True)
            return

        if not phone_number:
            reply = "I could not read your phone number. Please tap Share Phone Number again."

            _send_recorded_telegram_reply(conversation, channel, customer_key, reply, ai_generated=False)
            _send_recorded_telegram_reply(conversation, channel, customer_key, "Please share your phone number using the button.", contact_request=True)
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
            **channel_identity(channel, "telegram"),
        )

        reply = "Thanks, your phone number has been saved. How can I help you today?"

        _send_recorded_telegram_reply(conversation, channel, customer_key, reply, ai_generated=False)
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

        _send_recorded_telegram_reply(conversation, channel, customer_key, reply, ai_generated=True)
        return

    if not kind:
        customer_message = save_customer_text()

    # Private customers can share a profile phone; groups have no single phone.
    if is_private and not conversation.get("customer_phone"):
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
                **channel_identity(channel, "telegram"),
            )
            
            reply = "Thanks, your phone number has been saved. How can I help you today?"
            _send_recorded_telegram_reply(conversation, channel, customer_key, reply, ai_generated=False)
            return

        reply = (
            "Please tap the 'Share Phone Number' button below, or type your phone number manually to continue."
        )

        _send_recorded_telegram_reply(conversation, channel, customer_key, reply, contact_request=True)
        return

    # Button taps already showed it above; plain text has waited in silence until now.
    if not callback_query:
        show_telegram_typing(bot_token, chat_id)

    try:
        reply = generate_response(
            message_text,
            customer_key,
            chatbot_id,
            source_channel="telegram",
            conversation_id=conversation["id"],
            **({"message_id": customer_message["id"]}
               if isinstance(customer_message, dict) and customer_message.get("id") is not None else {}),
        )
    except BillingLimitError as billing_error:
        # generate_response re-raises this deliberately. Unguarded it reaches the
        # webhook's generic handler, so Telegram gets a 500, the update is never
        # marked processed, and Telegram retries the same message forever while
        # the customer sees nothing at all.
        logging.warning(
            "Telegram reply blocked by billing guard (chatbot_id=%s, code=%s)",
            chatbot_id,
            billing_error.code,
        )

        # Never leak the company's billing state to a Telegram customer.
        _send_recorded_telegram_reply(conversation, channel, customer_key, BILLING_LIMIT_CUSTOMER_REPLY, ai_generated=False)
        return

    if reply == "<SILENT_BOT_RESPONSE>":
        logging.info("AI is silenced (conversation escalated to human).")
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
    send_ok = True
    for i, reply_part in enumerate(parts):
        with conversation_delivery_lock(conversation["id"]):
            current_channel = get_bound_channel(conversation)
            if not automatic_reply_allowed(conversation, reply, paused=is_conversation_escalated(
                    conversation["id"], chatbot_id, conversation=conversation)):
                if i == 0:
                    return
                send_ok = False
                break
            markup = inline_markup if (i == len(parts) - 1) else None
            result = send_telegram_message(current_channel["bot_token"], customer_key, reply_part,
                                           reply_markup=markup, parse_mode=parse_mode)
        # A timeout is ambiguous; only a confirmed formatting rejection is safe
        # to resend. Never retry an accepted or uncertain delivery.
        if isinstance(result, dict) and result.get("format_rejected") and parse_mode:
            with conversation_delivery_lock(conversation["id"]):
                current_channel = get_bound_channel(conversation)
                if not automatic_reply_allowed(conversation, reply, paused=is_conversation_escalated(
                        conversation["id"], chatbot_id, conversation=conversation)):
                    send_ok = False
                    break
                result = send_telegram_message(current_channel["bot_token"], customer_key, reply_part,
                                               reply_markup=markup, parse_mode=None)
        if not delivery_accepted("telegram", result):
            send_ok = False
            break
    save_message(conversation_id=conversation["id"], sender_type="bot", message_text=reply,
                 message_type="text", delivery_status="sent" if send_ok else "failed",
                 ai_generated=True, last_error=None if send_ok else "Provider did not confirm delivery; review before retrying.")
    if send_ok and not is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
        if bot_record.get("followups_enabled") is True and isinstance(customer_message, dict):
            follow_up_service.schedule_after_reply(conversation, channel.get("company_id"), customer_message.get("id"))
        maybe_ask_marketing_consent(conversation, channel.get("company_id"), bot_record, message_text)
        dispatch_media_after_reply(message_text, chatbot_id, "telegram", get_bound_channel(conversation), customer_key,
                                   conversation=conversation)


def _send_recorded_telegram_reply(conversation, channel, recipient, text, ai_generated=False, contact_request=False):
    with conversation_delivery_lock(conversation["id"]):
        channel = get_bound_channel(conversation)
        if is_conversation_escalated(conversation["id"], channel["chatbot_id"], conversation=conversation):
            return False
        result = (send_telegram_contact_request(channel["bot_token"], recipient) if contact_request
                  else send_telegram_message(channel["bot_token"], recipient, text))
    accepted = delivery_accepted("telegram", result)
    save_message(conversation_id=conversation["id"], sender_type="bot", message_text=text,
                 message_type="text", delivery_status="sent" if accepted else "failed", ai_generated=ai_generated,
                 last_error=None if accepted else "Provider did not confirm delivery; review before retrying.")
    return accepted
