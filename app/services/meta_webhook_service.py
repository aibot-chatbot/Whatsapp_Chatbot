"""Normalize Meta webhook changes at the provider boundary."""

from datetime import datetime, timezone

from app.database import (agent_action_repository, conversation_repository, message_repository,
                          processed_message_repository, whatsapp_channel_repository)
from app.services.channel_delivery_service import channel_identity
from app.services.company_status_service import CompanyOperationalStatusError, ensure_company_operational
from app.services.conversation_delivery_lock import conversation_delivery_lock


def objects(items):
    return (item for item in items if isinstance(item, dict)) if isinstance(items, list) else ()


def inbound_messages(value):
    metadata = value.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("phone_number_id"), str):
        return
    contacts = {contact["wa_id"]: contact for contact in objects(value.get("contacts"))
                if isinstance(contact.get("wa_id"), str)}
    for message in objects(value.get("messages")):
        wa_id = message.get("from")
        if not isinstance(wa_id, str) or not wa_id or not isinstance(message.get("id"), str) or not message["id"]:
            continue
        kind = message.get("type")
        if not isinstance(kind, str):
            continue
        if kind == "text" and (not isinstance(message.get("text"), dict)
                               or not isinstance(message["text"].get("body"), str)):
            continue
        if kind == "interactive":
            interactive = message.get("interactive")
            if not isinstance(interactive, dict):
                continue
            selection = interactive.get("type")
            if selection in ("button_reply", "list_reply") and not isinstance(interactive.get(selection), dict):
                continue
        profile = contacts.get(wa_id, {}).get("profile")
        contact = {"wa_id": wa_id}
        if isinstance(profile, dict) and isinstance(profile.get("name"), str):
            contact["profile"] = {"name": profile["name"]}
        yield {"metadata": metadata, "contacts": [contact], "messages": [message]}


def _number_channel(waba_id, value):
    metadata = value.get("metadata")
    phone_id = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
    if not isinstance(phone_id, str) or not phone_id:
        return None
    channel = whatsapp_channel_repository.get_whatsapp_channel_by_phone_number_id(phone_id)
    if not channel or not channel.get("verified_at"):
        return None
    if waba_id is not None and (channel.get("whatsapp_business_account_id") or channel.get("waba_id")) != waba_id:
        return None
    return channel


def record_statuses(waba_id, value):
    if not value.get("statuses"):
        return
    channel = _number_channel(waba_id, value)
    if not channel:
        return
    for receipt in objects(value.get("statuses")):
        status = receipt.get("status")
        if isinstance(receipt.get("id"), str) and receipt["id"] and status in ("sent", "delivered", "read", "failed"):
            message_repository.advance_whatsapp_delivery_status(channel, receipt["id"], status)


def record_echoes(waba_id, value):
    channel = _number_channel(waba_id, value)
    if not channel or channel.get("onboarding_type") != "coexistence":
        return
    try:
        ensure_company_operational(channel["company_id"])
    except CompanyOperationalStatusError as error:
        if error.status_code == 403:
            return
        raise
    chatbot_id = channel["chatbot_id"]
    for echo in objects(value.get("message_echoes")):
        customer, message_id, kind = echo.get("to"), echo.get("id"), echo.get("type")
        if not all(isinstance(field, str) and field for field in (customer, message_id, kind)):
            continue
        content = echo.get(kind)
        if kind == "text":
            text = content.get("body") if isinstance(content, dict) else None
            if not isinstance(text, str):
                continue
        else:
            caption = content.get("caption") if isinstance(content, dict) else None
            text = caption if isinstance(caption, str) and caption else f"[{kind}]"
        if not processed_message_repository.claim_processed_message(chatbot_id, message_id):
            continue
        try:
            conversation = conversation_repository.get_or_create_conversation(
                chatbot_id=chatbot_id, customer_phone=customer, source_channel="whatsapp",
                **channel_identity(channel, "whatsapp"))
            conversation_id = conversation["id"]
            with conversation_delivery_lock(conversation_id):
                # A lost DB response may have committed the transcript before the retry.
                if message_repository.get_whatsapp_outbound_message(channel, message_id):
                    continue
                if not agent_action_repository.get_open_conversation_escalations(conversation_id, chatbot_id):
                    action = agent_action_repository.save_agent_action(
                        company_id=channel["company_id"], chatbot_id=chatbot_id, conversation_id=conversation_id,
                        intent="handoff_request", action_type="request_handoff",
                        reason="Staff replied from the WhatsApp Business app.", payload={"trigger": "smb_message_echoes"})
                    if not action:
                        raise RuntimeError("WhatsApp staff handoff was not saved")
                saved = message_repository.save_message(
                    conversation_id=conversation_id, sender_type="bot", message_text=text, message_type="smb_message_echo",
                    platform_message_id=message_id, delivery_status="sent", ai_generated=False)
                if not saved:
                    raise RuntimeError("WhatsApp staff transcript was not saved")
        except Exception:
            processed_message_repository.release_processed_message_claim(chatbot_id, message_id)
            raise


def _verified_after(channel, sent_at):
    """True when this connection was verified after Meta sent the event (a late or redelivered removal)."""
    if type(sent_at) not in (int, float):
        return False
    try:
        verified = datetime.fromisoformat(str(channel.get("verified_at")))
    except ValueError:
        return False
    if verified.tzinfo is None:
        verified = verified.replace(tzinfo=timezone.utc)
    return verified > datetime.fromtimestamp(sent_at, timezone.utc)


def partner_removed(waba_id, value, sent_at=None):
    # Meta can report removal for an entire WABA without any phone metadata.
    if "metadata" in value and (not isinstance(value["metadata"], dict) or "phone_number_id" in value["metadata"]):
        channel = _number_channel(waba_id, value)
        channels = [channel] if channel else []
    elif isinstance(waba_id, str) and waba_id:
        info = value.get("waba_info")
        if isinstance(info, dict) and info.get("waba_id", waba_id) != waba_id:
            return
        channels = whatsapp_channel_repository.get_connected_whatsapp_channels_by_waba_id(waba_id)
    else:
        return
    for channel in channels:
        if _verified_after(channel, sent_at):
            continue
        if not whatsapp_channel_repository.disconnect_whatsapp_channel(channel["id"]):
            raise RuntimeError("WhatsApp disconnect was not saved")
