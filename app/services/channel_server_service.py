"""Private linked-device transport. Provider responses may contain private data."""
import logging
import os
import re

import requests

from app.database.agent_action_repository import is_conversation_escalated
from app.database import channel_server_repository
from app.database.conversation_repository import find_open_conversation, get_or_create_conversation
from app.database.message_repository import get_latest_bot_message_text, save_message
from app.services.ai_router import generate_response
from app.services.channel_delivery_service import automatic_reply_allowed, channel_identity
from app.services.conversation_delivery_lock import conversation_delivery_lock
from app.services.turn_cache import turn_cache
from app.utils.message_style_utils import parse_buttons_tag

logger = logging.getLogger(__name__)
SOURCE = "whatsapp_link"
TEXT_ONLY_REPLY = ("I received your message, but I can only reply to text messages for now. "
                   "Please type your question and I'll help you.")


class ChannelServerError(Exception):
    pass


def available():
    return all(os.environ.get(key, "").strip() for key in
               ("CHANNEL_SERVER_URL", "CHANNEL_SERVER_API_KEY", "CHANNEL_SERVER_HMAC_KEY", "PUBLIC_BASE_URL"))


def require_available():
    if not available():
        raise ChannelServerError("WhatsApp (linked device) is unavailable.")


def _request(method, path, data=None, *, allow_missing=False):
    require_available()
    try:
        response = requests.request(method, os.environ["CHANNEL_SERVER_URL"].rstrip("/") + path,
                                    headers={"X-Api-Key": os.environ["CHANNEL_SERVER_API_KEY"],
                                             "Accept": "application/json"},
                                    json=data, timeout=(3, 12), allow_redirects=False)
        if allow_missing and response.status_code == 404:
            return {}
        if not 200 <= response.status_code < 300:
            raise ChannelServerError("Channel Server could not complete the request.")
        if response.status_code == 204 or not response.content:
            return {}
        value = response.json()
        return value if isinstance(value, dict) else {}
    except (requests.RequestException, ValueError):
        raise ChannelServerError("Channel Server did not confirm the request.") from None


def _webhook_config():
    require_available()
    webhook = {"url": os.environ["PUBLIC_BASE_URL"].rstrip("/") + "/api/channel-server/webhook",
               "events": ["message", "session.status", "poll.vote"], "hmac": {"key": os.environ["CHANNEL_SERVER_HMAC_KEY"]}}
    return {"webhooks": [webhook]}


def create_session(name):
    _request("POST", "/api/sessions", {"name": name, "start": True, "config": _webhook_config()})


def ensure_session_webhooks(name):
    _request("PUT", f"/api/sessions/{name}", {"config": _webhook_config()})


def pairing_code(name, phone):
    result = _request("POST", f"/api/{name}/auth/request-code", {"phoneNumber": phone})
    code = result.get("code")
    # whatsmeow (GOWS) returns XXXX-XXXX; WhatsApp shows the same dashed form.
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}", code):
        raise ChannelServerError("Pairing code is unavailable. Request a new code.")
    return code


QR_MAX_BASE64 = 200_000  # a WhatsApp QR PNG is a few KB


def qr_image(name):
    # WAHA answers Accept: application/json with {"mimetype", "data"} (base64 PNG).
    result = _request("GET", f"/api/{name}/auth/qr?format=image")
    data = result.get("data")
    if (result.get("mimetype") != "image/png" or not isinstance(data, str)
            or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", data) or len(data) > QR_MAX_BASE64):
        raise ChannelServerError("QR code is unavailable. Try again.")
    return "data:image/png;base64," + data


def status(name):
    return _request("GET", f"/api/sessions/{name}").get("status")


def disconnect(name):
    # DELETE is authoritative and also removes sessions that never completed login.
    try:
        _request("POST", f"/api/sessions/{name}/logout", allow_missing=True)
    except ChannelServerError:
        # A pending or already logged-out session can still be deleted.
        pass
    _request("DELETE", f"/api/sessions/{name}", allow_missing=True)


def _chat_id(recipient):
    recipient = str(recipient)
    if re.fullmatch(r"[0-9]{8,15}@c\.us|[0-9]{1,30}@lid", recipient):
        return recipient  # an @lid chat may hide a reply sent to the phone JID
    if re.fullmatch(r"[0-9]{8,15}", recipient.removeprefix("+")):
        return recipient.removeprefix("+") + "@c.us"
    raise ChannelServerError("The conversation has no valid WhatsApp recipient.")


def send_text(name, recipient, text):
    result = _request("POST", "/api/sendText", {"session": name, "chatId": _chat_id(recipient), "text": text})
    return bool(result.get("id"))


def send_poll(name, recipient, question, options):
    result = _request("POST", "/api/sendPoll", {"session": name, "chatId": _chat_id(recipient),
                      "poll": {"name": question, "options": options, "multipleAnswers": False}})
    return bool(result.get("id"))


def _phone_digits(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([0-9]{8,15})(?::[0-9]+)?(?:@s\.whatsapp\.net|@c\.us)?", value)
    return match.group(1) if match else None


def _resolve_lid(session_name, lid, payload):
    data = payload.get("_data")
    info = data.get("Info") if isinstance(data, dict) else None
    if isinstance(info, dict):
        digits = _phone_digits(info.get("SenderAlt"))
        if digits:
            return digits
    try:
        result = _request("GET", f"/api/{session_name}/lids/{lid}", allow_missing=True)
    except ChannelServerError:
        return None
    return _phone_digits(result.get("pn"))


def _sender_phone(channel, sender, payload):
    if re.fullmatch(r"[0-9]{8,15}@c\.us", sender):
        return "+" + sender.removesuffix("@c.us")
    if re.fullmatch(r"[0-9]{1,30}@lid", sender):
        digits = _resolve_lid(channel["session_name"], sender, payload)
        if digits:
            return "+" + digits
    return None


def _ignore_vote(reason):
    logger.info("[ChannelServer] linked-device vote skipped: %s", reason)


def process_poll_vote(channel, payload, claim):
    vote = payload.get("vote")
    if not isinstance(vote, dict) or vote.get("fromMe") is not False:
        return _ignore_vote("invalid_vote")
    sender, vote_id, options = vote.get("from"), vote.get("id"), vote.get("selectedOptions")
    if (not isinstance(sender, str) or not isinstance(vote_id, str) or not vote_id.strip()
            or len("poll:") + len(vote_id) > 512):
        return _ignore_vote("invalid_identity")
    if not isinstance(options, list) or len(options) != 1 or not isinstance(options[0], str):
        return _ignore_vote("invalid_selection")
    label = options[0].strip()
    if not label or len(label) > 20:
        return _ignore_vote("invalid_selection")
    phone = _sender_phone(channel, sender, payload)
    if not phone:
        return _ignore_vote("invalid_sender")
    chat = find_open_conversation(chatbot_id=channel["chatbot_id"], customer_phone=phone, source_channel=SOURCE,
                                  **channel_identity(channel, SOURCE))
    if not chat:
        return _ignore_vote("no_open_conversation")
    _, offered = parse_buttons_tag(get_latest_bot_message_text(chat["id"]))
    if not any(label == option.strip() for option in offered):
        return _ignore_vote("not_offered")
    process_message(channel, {"id": "poll:" + vote_id, "from": sender, "fromMe": False, "body": label},
                    claim, open_chat=chat)


def process_message(channel, payload, claim, *, open_chat=None):
    from app.services.channel_delivery_service import send_linked_reply

    sender = payload.get("from")
    message_id = payload.get("id")
    if (payload.get("fromMe") is not False or not isinstance(sender, str)
            or not isinstance(message_id, str) or not 0 < len(message_id.strip()) <= 512):
        return
    text = payload.get("body")
    media = payload.get("hasMedia") is True
    if not media and (not isinstance(text, str) or not text.strip()):
        return
    phone = open_chat["customer_phone"] if open_chat is not None else _sender_phone(channel, sender, payload)
    if not phone:
        if sender.endswith("@lid"):
            logger.warning("[ChannelServer] linked-device message skipped: lid_unresolved")
        return
    if not claim(message_id):
        if open_chat is not None:
            _ignore_vote("duplicate")
        return
    # Category only (no number, LID or text): shows which WhatsApp addressing reached us.
    logger.info("[ChannelServer] linked-device message received addressing=%s",
                "lid" if sender.endswith("@lid") else "pn")
    chatbot_id = channel["chatbot_id"]
    with turn_cache():
        try:
            chat = open_chat
            if chat is None:
                chat = get_or_create_conversation(chatbot_id=chatbot_id, customer_phone=phone, source_channel=SOURCE,
                                                  **channel_identity(channel, SOURCE))
            # A tap answers our poll; only a typed message may move the reply chat (a wrong one hides replies).
            if open_chat is None and chat.get("platform_user_id") != sender:
                # Automatic, staff and held replies all go back to the chat WhatsApp used.
                channel_server_repository.set_reply_chat_id(chat["id"], sender)
                chat = {**chat, "platform_user_id": sender}
        except Exception:
            # No transcript write, AI charge or outbound request has started.
            channel_server_repository.release(message_id)
            raise
        received = save_message(conversation_id=chat["id"], sender_type="customer", ai_generated=False,
                                message_text="[Unsupported attachment]" if media else text,
                                message_type="unsupported" if media else "text",
                                platform_message_id=message_id, delivery_status="received")
        if is_conversation_escalated(chat["id"], chatbot_id, conversation=chat):
            return
        reply = TEXT_ONLY_REPLY if media else generate_response(
            text, phone, chatbot_id, source_channel=SOURCE, conversation_id=chat["id"],
            **({"message_id": received["id"]} if isinstance(received, dict) and received.get("id") else {}))
        if not reply or reply == "<SILENT_BOT_RESPONSE>":
            return
        with conversation_delivery_lock(chat["id"]):
            paused = is_conversation_escalated(chat["id"], chatbot_id, conversation=chat)
            if not automatic_reply_allowed(chat, reply, paused=paused):
                return
            accepted = False
            try:
                send_linked_reply(chat, reply)
                accepted = True
            finally:
                save_message(conversation_id=chat["id"], sender_type="bot", message_text=reply,
                             message_type="text", delivery_status="sent" if accepted else "failed", ai_generated=True)
