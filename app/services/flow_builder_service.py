import json
import logging

from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot
from app.database.bot_repository import get_bot_by_id
from app.services.ai_router import generate_system_response, OPERATION_WELCOME_MENU


def auto_generate_welcome_menu(chatbot_id):
    """
    Scans the active PDF for the chatbot, extracts the text, and asks the AI
    to generate a welcome message and up to 3 interactive button options.
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
    
    # Limit text to roughly 15000 characters to stay well within token limits and keep it fast
    pdf_text = pdf_text[:15000]
    
    company_name = bot.get("bot_name", "our business")

    prompt = f"""
    You are an expert conversational designer. Based on the following PDF knowledge base for '{company_name}', generate a friendly 'Welcome Message' for a WhatsApp chatbot, and exactly 1 to 3 short options (interactive buttons) that represent the main services, products, or most common questions.
    
    CRITICAL: Format your response EXACTLY as a JSON object with two keys:
    1. "welcome_text" (string)
    2. "buttons" (array of strings, max 3 items, max 20 characters per item)
    
    Example output format:
    {{
        "welcome_text": "Hello! Welcome to {company_name}. How can I help you today?",
        "buttons": ["Our Services", "Pricing", "Support"]
    }}
    
    PDF Content:
    {pdf_text}
    """
    
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
        
        # Ensure it meets WhatsApp limits
        buttons = data.get("buttons", [])[:3]
        clean_buttons = [str(btn)[:20].strip() for btn in buttons]
        
        return {
            "welcome_text": data.get("welcome_text", f"Hello! Welcome to {company_name}."),
            "buttons": clean_buttons
        }

    except Exception as e:
        logging.error(f"[AutoGenerate] AI Error: {e}")
        raise ValueError("Failed to generate menu using AI. The service might be temporarily unavailable.")
