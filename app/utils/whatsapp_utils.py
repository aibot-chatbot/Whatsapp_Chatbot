import logging
from flask import current_app, jsonify
import json
import requests
import os
from dotenv import load_dotenv
import google.generativeai as genai
# from app.services.openai_service import generate_response
import re
import shelve

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def is_message_processed(message_id):
    with shelve.open("processed_messages_db") as db:
        return db.get(message_id, False)


def mark_message_processed(message_id):
    with shelve.open("processed_messages_db", writeback=True) as db:
        db[message_id] = True

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


def generate_response(message):
    try:
        prompt = f"""
You are a helpful WhatsApp business assistant.
Reply clearly, naturally, and briefly.
User message: {message}
"""
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return "Sorry, I’m having trouble replying right now."


def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }

    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"

    try:
        response = requests.post(
            url, data=data, headers=headers, timeout=10
        )
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
    wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]

    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message_id = message["id"]
    message_body = message["text"]["body"]

    if is_message_processed(message_id):
        logging.info(f"Duplicate message ignored: {message_id}")
        return

    mark_message_processed(message_id)

    response = generate_response(message_body)
    response = process_text_for_whatsapp(response)

    data = get_text_message_input(current_app.config["RECIPIENT_WAID"], response)
    send_message(data)

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