import logging
from app.services import gemini_service
from app.services import deepseek_service
from app.services import groq_service
from app.services import grok_service
from app.services import cloudflare_service
from app.database.bot_repository import get_bot_by_id

def generate_response(message, wa_id, chatbot_id=1):
    """
    Routes the request to the appropriate AI provider based on chatbot settings.
    """
    try:
        # Fetch bot configuration to get provider
        bot = get_bot_by_id(chatbot_id)
        
        if not bot:
            logging.warning(f"Bot {chatbot_id} not found, falling back to Gemini.")
            return gemini_service.generate_response(message, wa_id, chatbot_id)

        provider = bot.get("ai_provider", "Gemini").lower()
        model_name = bot.get("model_name")
        temperature = bot.get("temperature", 0.7)

        logging.info(f"Routing request for Bot {chatbot_id} to provider: {provider}")

        if provider == "deepseek":
            # Use specific model if provided, else default to deepseek-chat
            model = model_name if model_name else "deepseek-chat"
            return deepseek_service.generate_response(
                message, wa_id, chatbot_id, 
                model=model, 
                temperature=temperature
            )
        elif provider == "groq":
            # Use specific model if provided, else default to llama-3.1-70b-versatile
            model = model_name if model_name else "llama-3.3-70b-versatile"
            return groq_service.generate_response(
                message, wa_id, chatbot_id, 
                model=model, 
                temperature=temperature
            )
        elif provider == "grok":
            # Use specific model if provided, else default to grok-beta
            model = model_name if model_name else "grok-beta"
            return grok_service.generate_response(
                message, wa_id, chatbot_id, 
                model=model, 
                temperature=temperature
            )
        elif provider == "cloudflare":
            # Use specific model if provided, else default to llama-3.1-8b-instruct
            model = model_name if model_name else "@cf/meta/llama-3.1-8b-instruct"
            return cloudflare_service.generate_response(
                message, wa_id, chatbot_id, 
                model=model, 
                temperature=temperature
            )
        else:
            model = model_name if model_name else "gemini-2.5-flash"

            if model == "gemini-2.0-flash":
                model = "gemini-2.5-flash"

            return gemini_service.generate_response(
                message,
                wa_id,
                chatbot_id,
                model=model,
                temperature=temperature
            )

    except Exception as e:
        logging.error(f"AI Router Error: {e}")
        # Fallback to Gemini if anything fails
        return gemini_service.generate_response(
            message,
            wa_id,
            chatbot_id
        )
