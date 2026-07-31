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
        f"1. A friendly 'Welcome Message' for a WhatsApp chatbot (include a short footer sentence at the end offering human customer service, e.g. '💬 Or reply AGENT to connect with human staff', in the PDF's language).\n"
        f"2. Exactly 1 to 3 short interactive button options representing the main services, products, or most common questions.\n\n"

        f"CRITICAL: Format your response EXACTLY as valid JSON:\n"
        f'{{\n'
        f'    "welcome_text": "Hello! Welcome to {company_name}. How can I help you today?\\n\\n💬 Reply AGENT anytime to speak with human staff.",\n'
        f'    "buttons": [\n'
        f'        {{\n'
        f'            "label": "Our Services",\n'
        f'            "reason": "Chosen because the PDF covers the services offered in detail. This is the most common customer inquiry.",\n'
        f'            "data_points": ["Service A: premium package", "Service B: basic plan", "24/7 support included"]\n'
        f'        }},\n'
        f'        {{\n'
        f'            "label": "Pricing",\n'
        f'            "reason": "The PDF has a dedicated pricing section. Pricing questions are top queries for most businesses.",\n'
        f'            "data_points": ["Basic plan: RM49/month", "Pro plan: RM99/month", "Annual discount: 20%"]\n'
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
        
        # Support both old format (strings) and new format (objects with label+reason+data_points)
        buttons_detail = []
        plain_buttons = []
        for btn in raw_buttons:
            if isinstance(btn, dict):
                label = str(btn.get("label", ""))[:20].strip()
                reason = str(btn.get("reason", "")).strip()
                raw_dp = btn.get("data_points", [])
                data_points = [str(p).strip() for p in raw_dp if str(p).strip()] if isinstance(raw_dp, list) else []
                buttons_detail.append({"label": label, "reason": reason, "data_points": data_points})
                plain_buttons.append(label)
            else:
                label = str(btn)[:20].strip()
                buttons_detail.append({"label": label, "reason": "", "data_points": []})
                plain_buttons.append(label)
        
        return {
            "welcome_text": data.get("welcome_text", f"Hello! Welcome to {company_name}."),
            "buttons": plain_buttons,
            "buttons_detail": buttons_detail,
        }

    except ValueError:
        raise
    except Exception as e:
        logging.error(f"[AutoGenerate] AI Error: {e}")
        raise ValueError("Failed to generate menu using AI. The service might be temporarily unavailable.")


_EXTRACTION_CACHE = {}


def extract_pdf_data_points(chatbot_id, force_refresh=False):
    """
    Scans the active PDF for the chatbot and asks the AI to extract facts
    grouped into logical business categories. Cached per (chatbot_id, file_id)
    for instant 0-second responses.
    """
    bot = get_bot_by_id(chatbot_id)
    if not bot:
        raise ValueError("Chatbot not found.")

    active_pdf = get_active_pdf_knowledge_file(chatbot_id)
    if not active_pdf:
        raise ValueError("No active PDF found for this chatbot. Please upload and deploy a PDF in the Training Data tab first.")

    file_id = active_pdf.get("id")
    cache_key = (chatbot_id, file_id)

    if not force_refresh and cache_key in _EXTRACTION_CACHE:
        logging.info(f"[ExtractDataPoints] Returning cached extraction for chatbot {chatbot_id}, file {file_id}")
        return _EXTRACTION_CACHE[cache_key]

    chunks = get_chunks_by_file_for_chatbot(chatbot_id, file_id)

    if not chunks:
        raise ValueError("No text data found in the active PDF. It might be empty or still processing.")

    pdf_text = "\n\n".join([chunk.get("content", "") for chunk in chunks])
    pdf_text = pdf_text[:15000]

    company_name = bot.get("bot_name", "our business")

    prompt = (
        f"You are a business intelligence analyst. Analyze the following document for '{company_name}' and dynamically organize its contents into 3 to 6 custom business categories tailored specifically to what this document is about.\n\n"
        f"IMPORTANT: Do NOT use fixed or hardcoded category names. Dynamically invent the most fitting category titles based on the actual topics found in the uploaded document (for example: if it's a restaurant document use menu categories; if real estate use property categories; if education/events use event/course categories).\n\n"
        f"Each category title should begin with a fitting emoji (e.g. 🍕, 🏠, 💰, 📅, 🏆, 📦, 📞) followed by a short descriptive category name.\n"
        f"Each category must contain 3 to 8 short, concrete factual bullet points extracted directly from the document text.\n\n"
        f"Each fact must:\n"
        f"- Be a single short sentence or phrase (under 100 characters)\n"
        f"- State a concrete fact, price, date, rule, feature, item, contact, or policy\n"
        f"- Come DIRECTLY from the text — do NOT invent or assume\n\n"
        f"CRITICAL: Format your response EXACTLY as valid JSON:\n"
        f'{{\n'
        f'    "categories": [\n'
        f'        {{\n'
        f'            "category_name": "Emoji & Suitable Category Name Based On Document",\n'
        f'            "data_points": [\n'
        f'                "Fact bullet point 1",\n'
        f'                "Fact bullet point 2"\n'
        f'            ]\n'
        f'        }}\n'
        f'    ]\n'
        f'}}\n\n'
        f"Document Content:\n{pdf_text}"
    )

    logging.info(f"[ExtractDataPoints] Querying AI for chatbot {chatbot_id}")

    try:
        reply = generate_system_response(
            prompt=prompt,
            chatbot_id=chatbot_id,
            temperature=0.2,
            json_response=True,
            operation_type=OPERATION_WELCOME_MENU,
        )

        data = json.loads(reply)
        raw_cats = data.get("categories", [])

        categories = []
        flat_chips = []

        if isinstance(raw_cats, list) and len(raw_cats) > 0:
            for cat in raw_cats:
                if isinstance(cat, dict):
                    name = str(cat.get("category_name", "General Info")).strip()
                    dps = [str(p).strip() for p in cat.get("data_points", []) if isinstance(p, str) and str(p).strip()][:8]
                    if dps:
                        categories.append({
                            "category_name": name,
                            "data_points": dps
                        })
                        flat_chips.extend(dps)

        # Fallback if flat data_points array returned
        if not categories:
            raw_flat = data.get("data_points", [])
            flat_chips = [str(p).strip() for p in raw_flat if isinstance(p, str) and str(p).strip()][:15]
            if flat_chips:
                categories = [{
                    "category_name": "📋 Key Extracted Facts",
                    "data_points": flat_chips
                }]

        result = {
            "categories": categories,
            "data_points": flat_chips
        }

        _EXTRACTION_CACHE[cache_key] = result
        return result

    except ValueError:
        raise
    except Exception as e:
        logging.error(f"[ExtractDataPoints] AI Error: {e}")
        raise ValueError("Failed to extract data points using AI. The service might be temporarily unavailable.")
