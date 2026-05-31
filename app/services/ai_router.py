import logging

from app.services import deepseek_service
from app.services import openrouter_service
from app.services.chat_pipeline_service import prepare_chat_prompt
from app.services.model_catalog import (
    OPENROUTER_PROVIDER_KEYS,
    normalize_model_selection,
    get_default_model,
)
from app.services.response_formatter import clean_ai_reply
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


def call_provider(
    provider,
    message,
    customer_id,
    chatbot_id,
    model_name=None,
    temperature=0.7,
    source_channel="whatsapp",
):
    provider = provider.lower().strip()

    if provider in OPENROUTER_PROVIDER_KEYS:
        pipeline = prepare_chat_prompt(
            message=message,
            customer_id=customer_id,
            chatbot_id=chatbot_id,
            source_channel=source_channel,
        )

        if pipeline.get("direct_reply"):
            return pipeline["direct_reply"]

        prompt = pipeline.get("prompt")

        if not prompt:
            raise ValueError("Prompt could not be prepared for OpenRouter provider.")

        model = model_name if model_name else get_default_model(provider)

        if not model:
            raise ValueError(f"No default model found for provider: {provider}")

        return openrouter_service.generate_response(
            prompt=prompt,
            model=model,
            temperature=temperature,
        )

    if provider == "deepseek":
        model = model_name if model_name else get_default_model("deepseek")

        return deepseek_service.generate_response(
            message,
            customer_id,
            chatbot_id,
            model=model,
            temperature=temperature,
            source_channel=source_channel,
        )

    raise ValueError(f"Unsupported AI provider: {provider}")


def generate_response(message, customer_id, chatbot_id, source_channel="whatsapp"):
    try:
        bot = get_bot_by_id(chatbot_id)

        if not bot:
            logging.warning(f"Bot {chatbot_id} not found. Using DeepSeek fallback.")

            reply = call_provider(
                "deepseek",
                message,
                customer_id,
                chatbot_id,
                model_name=get_default_model("deepseek"),
                temperature=0.7,
                source_channel=source_channel,
            )

            return clean_ai_reply(reply)

        selected_provider = bot.get("ai_provider", "deepseek")
        model_name = bot.get("model_name")
        temperature = bot.get("temperature", 0.7)

        selected_provider, model_name = normalize_model_selection(
            selected_provider,
            model_name,
        )

        logging.info(
            f"Routing request for Bot {chatbot_id} to provider: {selected_provider}, model: {model_name}"
        )

        try:
            reply = call_provider(
                selected_provider,
                message,
                customer_id,
                chatbot_id,
                model_name=model_name,
                temperature=temperature,
                source_channel=source_channel,
            )

            if not is_error_reply(reply):
                return clean_ai_reply(reply)

            logging.warning(
                f"Provider {selected_provider} returned an error reply. Trying fallback provider."
            )

        except Exception as provider_error:
            logging.error(f"Provider {selected_provider} failed: {provider_error}")

        fallback_providers = ["deepseek", "google", "openai"]

        for fallback_provider in fallback_providers:
            if fallback_provider == selected_provider:
                continue

            try:
                fallback_provider, fallback_model = normalize_model_selection(
                    fallback_provider,
                    None,
                )

                logging.info(
                    f"Trying fallback provider: {fallback_provider}, model: {fallback_model}"
                )

                fallback_reply = call_provider(
                    fallback_provider,
                    message,
                    customer_id,
                    chatbot_id,
                    model_name=fallback_model,
                    temperature=temperature,
                    source_channel=source_channel,
                )

                if not is_error_reply(fallback_reply):
                    logging.info(f"Fallback provider {fallback_provider} succeeded.")
                    return clean_ai_reply(fallback_reply)

                logging.warning(f"Fallback provider {fallback_provider} returned error reply.")

            except Exception as fallback_error:
                logging.error(f"Fallback provider {fallback_provider} failed: {fallback_error}")

        return "Sorry, I’m having trouble replying right now. Please try again later."

    except Exception as e:
        logging.error(f"AI Router Error: {e}")
        return "Sorry, I’m having trouble replying right now. Please try again later."
