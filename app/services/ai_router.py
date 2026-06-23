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
from app.services.billing_guard import can_send_ai_message, BillingLimitError


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


def _check_billing_for_bot(chatbot_id):
    """Check billing limit for a given chatbot_id. Returns company_id or None."""
    bot = get_bot_by_id(chatbot_id)
    if bot:
        company_id = bot.get("company_id")
        if company_id:
            try:
                can_send_ai_message(company_id)
                return company_id
            except BillingLimitError as e:
                logging.warning(
                    "AI message limit reached for company %s (chatbot %s): %s",
                    company_id, chatbot_id, e,
                )
                raise
    return None


def generate_response(message, customer_id, chatbot_id, source_channel="whatsapp"):
    try:
        try:
            _check_billing_for_bot(chatbot_id)
        except BillingLimitError:
            return "Your account has reached its monthly AI message limit. Please upgrade your plan to continue."

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

        return "Sorry, I'm having trouble replying right now. Please try again later."

    except Exception as e:
        logging.error(f"AI Router Error: {e}")
        return "Sorry, I'm having trouble replying right now. Please try again later."


def _call_deepseek_direct(prompt, model, temperature, json_response=False):
    """Call DeepSeek directly with a plain prompt (no chat pipeline)."""
    from openai import OpenAI
    import os

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is missing.")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    kwargs = {
        "model": model or "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "stream": False,
    }
    if json_response:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    reply = response.choices[0].message.content
    if reply:
        return reply.strip()
    raise RuntimeError("DeepSeek returned an empty response.")


def _call_gemini_direct(prompt, model, temperature):
    """Call Google Gemini directly with a plain prompt."""
    from google import genai
    import os

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is missing.")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model or "gemini-2.5-flash",
        contents=prompt,
    )
    return response.text.strip()


def _call_openrouter_direct(prompt, model, temperature):
    """Call OpenRouter directly with a plain prompt (no chat pipeline)."""
    import os
    import requests

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is missing.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-OpenRouter-Title": "AI Chatbot System",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def generate_system_response(prompt, chatbot_id, provider=None, model=None, temperature=None, json_response=False):
    """Generate an AI response for system/background tasks (non-chat).

    This is the ONLY authorized function for system AI calls. It enforces
    billing limits centrally.

    Args:
        prompt: The prompt string to send to the LLM
        chatbot_id: The chatbot ID (for billing check and provider lookup)
        provider: Optional provider override (defaults to bot's provider)
        model: Optional model override (defaults to bot's model)
        temperature: Optional temperature override (defaults to 0.3 for system)
        json_response: Whether to request JSON mode (DeepSeek supports this natively)

    Returns:
        The LLM response text, or raises RuntimeError on failure
    """
    try:
        _check_billing_for_bot(chatbot_id)
    except BillingLimitError:
        raise  # Let caller handle billing limit errors

    bot = get_bot_by_id(chatbot_id)

    selected_provider = provider or (bot.get("ai_provider", "deepseek") if bot else "deepseek")
    selected_model = model or (bot.get("model_name") if bot else None)
    selected_temperature = temperature if temperature is not None else (bot.get("temperature", 0.3) if bot else 0.3)

    selected_provider, selected_model = normalize_model_selection(
        selected_provider,
        selected_model,
    )

    if not selected_model:
        selected_model = get_default_model(selected_provider)

    logging.info(
        "System AI call for chatbot %s -> provider: %s, model: %s",
        chatbot_id, selected_provider, selected_model,
    )

    if selected_provider == "deepseek":
        return _call_deepseek_direct(prompt, selected_model, selected_temperature, json_response)

    if selected_provider in OPENROUTER_PROVIDER_KEYS:
        return _call_openrouter_direct(prompt, selected_model, selected_temperature)

    if selected_provider == "google":
        return _call_gemini_direct(prompt, selected_model, selected_temperature)

    logging.warning("Unsupported system AI provider: %s, falling back to deepseek", selected_provider)
    return _call_deepseek_direct(prompt, get_default_model("deepseek"), selected_temperature, json_response)
