import logging
from flask import current_app, jsonify
import json
import requests
import re

from app.services.ai_router import generate_response
from app.database.conversation_repository import get_or_create_conversation
from app.database.message_repository import save_message
from app.database.processed_message_repository import is_processed, save_processed
from app.database.whatsapp_channel_repository import get_whatsapp_channel_by_phone_number_id


def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")


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


def send_message(data, channel=None):
    access_token = channel.get("access_token") if channel else None
    phone_number_id = channel.get("phone_number_id") if channel else None

    if not access_token or not phone_number_id:
        logging.warning(
            "Using global WhatsApp credentials as development fallback. "
            "Connected SaaS channels should provide access_token and phone_number_id."
        )
        access_token = current_app.config["ACCESS_TOKEN"]
        phone_number_id = current_app.config["PHONE_NUMBER_ID"]

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
        logging.error(f"Request failed due to: {e}")
        return jsonify({"status": "error", "message": "Failed to send message"}), 500
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

    wa_id = value["contacts"][0]["wa_id"]
    customer_name = value["contacts"][0].get("profile", {}).get("name")

    message = value["messages"][0]
    message_id = message["id"]

    if is_processed(chatbot_id, message_id):
        logging.info(f"Duplicate message ignored: {message_id}")
        return

    # Step 5: Handle non-text messages safely
    if message.get("type") != "text":
        logging.info(f"Unsupported WhatsApp message type: {message.get('type')}")

        conversation = get_or_create_conversation(
            chatbot_id=chatbot_id,
            customer_phone=wa_id,
            customer_name=customer_name,
            source_channel="whatsapp",
        )

        save_message(
            conversation_id=conversation["id"],
            sender_type="customer",
            message_text=f"[Unsupported message type: {message.get('type')}]",
            message_type=message.get("type", "unknown"),
            platform_message_id=message_id,
            delivery_status="received",
            ai_generated=False,
        )

        message_type = message.get("type", "unknown")

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

        save_message(
            conversation_id=conversation["id"],
            sender_type="bot",
            message_text=reply,
            message_type="text",
            delivery_status="sent",
            ai_generated=True,
        )

        data = get_text_message_input(wa_id, reply)
        send_message(data, channel)

        save_processed(chatbot_id, message_id)
        return

    message_body = message["text"]["body"]

    conversation = get_or_create_conversation(
        chatbot_id=chatbot_id,
        customer_phone=wa_id,
        customer_name=customer_name,
        source_channel="whatsapp",
    )

    save_message(
        conversation_id=conversation["id"],
        sender_type="customer",
        message_text=message_body,
        message_type="text",
        platform_message_id=message_id,
        delivery_status="received",
        ai_generated=False,
    )

    response = generate_response(
        message_body,
        wa_id,
        chatbot_id,
        source_channel="whatsapp",
    )
    response = process_text_for_whatsapp(response)

    save_message(
        conversation_id=conversation["id"],
        sender_type="bot",
        message_text=response,
        message_type="text",
        delivery_status="sent",
        ai_generated=True,
    )

    data = get_text_message_input(wa_id, response)
    send_message(data, channel)

    save_processed(chatbot_id, message_id)


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
