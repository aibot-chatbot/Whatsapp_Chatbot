import logging
import re
import requests
import os
from contextlib import nullcontext
from app.database.bot_media_attachment_repository import get_active_attachments
from app.database.agent_action_repository import is_conversation_escalated
from app.services.channel_delivery_service import get_bound_channel
from app.services.conversation_delivery_lock import conversation_delivery_lock

def find_matching_attachment(message_text, attachments):
    """
    Finds the first attachment whose keywords appear in the message text.
    Matching is case-insensitive and checks for whole words if possible.
    """
    if not message_text or not attachments:
        return None
        
    text_lower = message_text.lower()
    
    for attachment in attachments:
        keywords = attachment.get("keywords", [])
        if not keywords:
            continue
            
        for keyword in keywords:
            kw_lower = str(keyword).lower().strip()
            if not kw_lower:
                continue
                
            # Basic whole-word or substring match depending on keyword format
            # Using simple regex for whole word boundary match if it's alphanumeric
            if kw_lower.isalnum():
                pattern = r'\b' + re.escape(kw_lower) + r'\b'
                if re.search(pattern, text_lower):
                    return attachment
            else:
                if kw_lower in text_lower:
                    return attachment
                    
    return None

def send_wasender_media(api_key, to, attachment):
    """
    Sends media through Wasender API.
    """
    try:
        from app.services.wasender_service import WASENDER_BASE_URL, normalize_wasender_recipient
        
        recipient = normalize_wasender_recipient(to)
        if not recipient:
            return False
            
        url = f"{WASENDER_BASE_URL.rstrip('/')}/api/send-message"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        media_url = attachment.get("media_url")
        media_type = attachment.get("media_type", "image")
        caption = attachment.get("caption", "")
        
        # Wasender uses mediaUrl and mediaType
        payload = {
            "to": recipient,
            "mediaUrl": media_url,
            "mediaType": media_type
        }
        
        if caption:
            payload["caption"] = caption
            
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        
        if response.status_code >= 400:
            logging.error("Wasender media send failed: %s", response.status_code)
            return False
            
        logging.info(f"Wasender media send success: {response.status_code}")
        return True
    except Exception as e:
        logging.error("Failed to send Wasender media (%s)", type(e).__name__)
        return False

def send_telegram_media(bot_token, chat_id, attachment):
    """
    Sends media through Telegram Bot API.
    """
    try:
        media_type = attachment.get("media_type", "image")
        media_url = attachment.get("media_url")
        caption = attachment.get("caption", "")
        
        # Determine correct endpoint and field based on media type
        if media_type == "video":
            endpoint = "sendVideo"
            field = "video"
        elif media_type == "document":
            endpoint = "sendDocument"
            field = "document"
        else: # Default to photo
            endpoint = "sendPhoto"
            field = "photo"
            
        url = f"https://api.telegram.org/bot{bot_token}/{endpoint}"
        
        payload = {
            "chat_id": chat_id,
            field: media_url
        }
        
        if caption:
            payload["caption"] = caption
            
        response = requests.post(url, json=payload, timeout=20)
        
        if response.status_code >= 400:
            logging.error("Telegram media send failed: %s", response.status_code)
            return False
            
        logging.info(f"Telegram media send success: {response.status_code}")
        return True
    except Exception as e:
        logging.error("Failed to send Telegram media (%s)", type(e).__name__)
        return False

def send_meta_media_template(channel, attachment, to):
    """
    Sends media template through Meta WhatsApp Graph API.
    Meta API requires pre-approved templates for sending media if outside 24h window,
    so we only use it if a template name is explicitly configured.
    """
    try:
        template_name = attachment.get("meta_template_name")
        if not template_name:
            logging.info("Meta media template skip: No template name configured for this attachment.")
            return False
            
        from app.routes.whatsapp_routes import get_graph_api_version
        
        access_token = channel.get("access_token")
        phone_number_id = channel.get("phone_number_id")
        
        if not access_token or not phone_number_id:
            logging.error("Meta media template failed: Missing access token or phone number ID.")
            return False
            
        # Clean recipient
        recipient = str(to).strip()
        if recipient.startswith("+"):
            recipient = recipient[1:]
            
        version = get_graph_api_version()
        url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        media_url = attachment.get("media_url")
        media_type = attachment.get("media_type", "image")
        lang_code = attachment.get("meta_language_code", "en_US")
        
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": lang_code
                },
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {
                                "type": media_type,
                                media_type: {
                                    "link": media_url
                                }
                            }
                        ]
                    }
                ]
            }
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        
        if response.status_code >= 400:
            logging.error("Meta media template send failed: %s", response.status_code)
            return False
            
        logging.info(f"Meta media template send success: {response.status_code}")
        return True
    except Exception as e:
        logging.error("Failed to send Meta media template (%s)", type(e).__name__)
        return False

def dispatch_media_after_reply(message_text, chatbot_id, channel_type, channel, recipient, *, conversation=None):
    """
    Main entry point to be called after a standard text reply is sent.
    Evaluates if the user's message matches any media attachment triggers,
    and if so, dispatches the media through the appropriate channel.
    """
    try:
        if not message_text or not chatbot_id or not recipient:
            return False
            
        attachments = get_active_attachments(chatbot_id)
        if not attachments:
            return False
            
        matched = find_matching_attachment(message_text, attachments)
        if not matched:
            return False

        with conversation_delivery_lock(conversation["id"]) if conversation is not None else nullcontext():
            if conversation is not None:
                channel = get_bound_channel(conversation)
                if is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
                    return False

            logging.info(f"Found matching media attachment '{matched.get('label')}' for chatbot_id={chatbot_id}")

            if channel_type == "wasender":
                api_key = channel.get("api_key")
                return send_wasender_media(api_key, recipient, matched)

            elif channel_type == "whatchimp":
                from app.services.whatchimp_client import send_whatchimp_file
                return send_whatchimp_file(channel.get("api_token"), channel.get("phone_number_id"), recipient,
                                           matched.get("media_url"), matched.get("media_type", "image"),
                                           matched.get("caption", ""))["success"]

            elif channel_type == "telegram":
                bot_token = channel.get("bot_token")
                return send_telegram_media(bot_token, recipient, matched)

            elif channel_type == "meta":
                return send_meta_media_template(channel, matched, recipient)

            else:
                logging.warning(f"Unsupported channel type for media dispatch: {channel_type}")
                return False
            
    except Exception as e:
        logging.error(f"Media dispatch failed: {e}")
        return False
