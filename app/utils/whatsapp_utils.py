import logging
from flask import current_app, jsonify
import json
import requests
import re

from app.services.gemini_service import generate_response
from app.database.conversation_repository import get_or_create_conversation
from app.database.message_repository import save_message
from app.database.processed_message_repository import is_processed, save_processed


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


def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }

    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"

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

    wa_id = value["contacts"][0]["wa_id"]
    customer_name = value["contacts"][0].get("profile", {}).get("name")

    message = value["messages"][0]
    message_id = message["id"]
    message_body = message["text"]["body"]

    # TEMP: use chatbot_id = 1 first
    # Later we will detect which bot based on phone_number_id or channel
    chatbot_id = 1

    if is_processed(chatbot_id, message_id):
        logging.info(f"Duplicate message ignored: {message_id}")
        return

    conversation = get_or_create_conversation(
        chatbot_id=chatbot_id,
        customer_phone=wa_id,
        customer_name=customer_name,
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

    response = generate_response(message_body, wa_id, chatbot_id)
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
    send_message(data)

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