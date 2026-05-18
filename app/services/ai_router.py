import logging
from app.services import gemini_service
from app.services import deepseek_service
from app.services import groq_service
from app.services import grok_service
from app.services import cloudflare_service
from app.database.bot_repository import get_bot_by_id


ERROR_REPLY_PATTERNS = [
    "encountered an error while processing your request",
    "having trouble replying right now",
    "having trouble connecting",
    "not sure how to answer that right now",
]


def is_error_reply(reply):
    if not reply:
        return True

    reply_lower = reply.lower()

    return any(pattern in reply_lower for pattern in ERROR_REPLY_PATTERNS)


def call_provider(provider, message, wa_id, chatbot_id, model_name=None, temperature=0.7):
    provider = provider.lower()

    if provider == "deepseek":
        model = model_name if model_name else "deepseek-chat"
        return deepseek_service.generate_response(
            message,
            wa_id,
            chatbot_id,
            model=model,
            temperature=temperature
        )

    if provider == "groq":
        model = model_name if model_name else "llama-3.3-70b-versatile"
        return groq_service.generate_response(
            message,
            wa_id,
            chatbot_id,
            model=model,
            temperature=temperature
        )

    if provider == "grok":
        model = model_name if model_name else "grok-beta"
        return grok_service.generate_response(
            message,
            wa_id,
            chatbot_id,
            model=model,
            temperature=temperature
        )

    if provider == "cloudflare":
        model = model_name if model_name else "@cf/meta/llama-3.1-8b-instruct"
        return cloudflare_service.generate_response(
            message,
            wa_id,
            chatbot_id,
            model=model,
            temperature=temperature
        )

    # Default Gemini
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


def generate_response(message, wa_id, chatbot_id=1):
    """
    Routes the request to the selected AI provider.
    If selected provider fails, fallback to another working provider.
    """
    try:
        bot = get_bot_by_id(chatbot_id)

        if not bot:
            logging.warning(f"Bot {chatbot_id} not found. Using Gemini fallback.")
            return call_provider(
                "gemini",
                message,
                wa_id,
                chatbot_id,
                model_name=None,
                temperature=0.7
            )

        selected_provider = bot.get("ai_provider", "Gemini").lower()
        model_name = bot.get("model_name")
        temperature = bot.get("temperature", 0.7)

        logging.info(f"Routing request for Bot {chatbot_id} to provider: {selected_provider}")

        # Try selected provider first
        try:
            reply = call_provider(
                selected_provider,
                message,
                wa_id,
                chatbot_id,
                model_name=model_name,
                temperature=temperature
            )

            if not is_error_reply(reply):
                return reply

            logging.warning(
                f"Provider {selected_provider} returned an error reply. Trying fallback provider."
            )

        except Exception as provider_error:
            logging.error(f"Provider {selected_provider} failed: {provider_error}")

        # Fallback order
        # Do not include Grok because it may require paid credit.
        fallback_providers = ["gemini", "deepseek", "groq", "cloudflare"]

        for fallback_provider in fallback_providers:
            if fallback_provider == selected_provider:
                continue

            try:
                logging.info(f"Trying fallback provider: {fallback_provider}")

                fallback_reply = call_provider(
                    fallback_provider,
                    message,
                    wa_id,
                    chatbot_id,
                    model_name=None,
                    temperature=temperature
                )

                if not is_error_reply(fallback_reply):
                    logging.info(f"Fallback provider {fallback_provider} succeeded.")
                    return fallback_reply

                logging.warning(f"Fallback provider {fallback_provider} returned error reply.")

            except Exception as fallback_error:
                logging.error(f"Fallback provider {fallback_provider} failed: {fallback_error}")

        return "Sorry, I’m having trouble replying right now. Please try again later."

    except Exception as e:
        logging.error(f"AI Router Error: {e}")
        return "Sorry, I’m having trouble replying right now. Please try again later."
