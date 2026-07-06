import json
import logging

from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot
from app.database.bot_repository import get_bot_by_id
from app.services.ai_router import generate_system_response, OPERATION_WELCOME_MENU


def auto_generate_welcome_menu(chatbot_id):
    """
    Scans the active PDF for the chatbot, extracts the text, and asks the AI
    to generate a welcome message and up to 3 interactive button options with reasons.
    All AI calls go through ai_router.generate_system_response for billing enforcement.
    """
    bot = get_bot_by_id(chatbot_id)
    if not bot:
        raise ValueError("Chatbot not found.")

    active_pdf = get_active_pdf_knowledge_file(chatbot_id)
    if not active_pdf:
        raise ValueError("No active PDF found for this chatbot. Please upload and deploy a PDF in the Training Data tab first.")
        
    file_id = active_pdf.get("id")
    chunks = get_chunks_by_file_for_chatbot(chatbot_id, file_id)
    
    if not chunks:
        raise ValueError("No text data found in the active PDF. It might be empty or still processing.")
        
    # Combine chunks
    pdf_text = "\n\n".join([chunk.get("content", "") for chunk in chunks])
    
    # Limit text to roughly 15000 characters to stay well within token limits
    pdf_text = pdf_text[:15000]
    
    company_name = bot.get("bot_name", "our business")

    prompt = (
        f"You are an expert conversational designer. Based on the following PDF knowledge base for '{company_name}', generate:\n"
        f"1. A friendly 'Welcome Message' for a WhatsApp chatbot.\n"
        f"2. Exactly 1 to 3 short interactive button options representing the main services, products, or most common questions.\n\n"
        f"For each button you MUST also provide:\n"
        f"- \"label\": The short button text shown to the customer (max 20 characters)\n"
        f"- \"reason\": A short explanation (1-2 sentences) of why this button was chosen and what topic or section of the PDF it covers.\n\n"
        f"CRITICAL: Format your response EXACTLY as valid JSON:\n"
        f'{{\n'
        f'    "welcome_text": "Hello! Welcome to {company_name}. How can I help you today?",\n'
        f'    "buttons": [\n'
        f'        {{\n'
        f'            "label": "Our Services",\n'
        f'            "reason": "Chosen because the PDF covers the services offered in detail. This is the most common customer inquiry."\n'
        f'        }},\n'
        f'        {{\n'
        f'            "label": "Pricing",\n'
        f'            "reason": "The PDF has a dedicated pricing section. Pricing questions are top queries for most businesses."\n'
        f'        }}\n'
        f'    ]\n'
        f'}}\n\n'
        f"PDF Content:\n{pdf_text}"
    )
    
    logging.info(f"[AutoGenerate] Querying AI for chatbot {chatbot_id}")

    try:
        reply = generate_system_response(
            prompt=prompt,
            chatbot_id=chatbot_id,
            temperature=0.3,
            json_response=True,
            operation_type=OPERATION_WELCOME_MENU,
        )
        
        data = json.loads(reply)
        
        raw_buttons = data.get("buttons", [])[:3]
        
        # Support both old format (strings) and new format (objects with label+reason)
        buttons_detail = []
        plain_buttons = []
        for btn in raw_buttons:
            if isinstance(btn, dict):
                label = str(btn.get("label", ""))[:20].strip()
                reason = str(btn.get("reason", "")).strip()
                buttons_detail.append({"label": label, "reason": reason})
                plain_buttons.append(label)
            else:
                label = str(btn)[:20].strip()
                buttons_detail.append({"label": label, "reason": ""})
                plain_buttons.append(label)
        
        return {
            "welcome_text": data.get("welcome_text", f"Hello! Welcome to {company_name}."),
            "buttons": plain_buttons,
            "buttons_detail": buttons_detail,
        }

    except Exception as e:
        logging.error(f"[AutoGenerate] AI Error: {e}")
        raise ValueError("Failed to generate menu using AI. The service might be temporarily unavailable.")
