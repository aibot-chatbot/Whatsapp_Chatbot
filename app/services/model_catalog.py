# Providers listed here will be routed through OpenRouter.
# Do not include "gemini", "groq", "grok", or "cloudflare" here,
# because those are used for your old direct API services.

OPENROUTER_PROVIDER_KEYS = [
    "openai",
    "google",
    "anthropic",
    "xai",
    "qwen",
    "mistral",
]


MODEL_CATALOG = {
    "deepseek": {
        "label": "DeepSeek",
        "models": [
            {
                "label": "DeepSeek V4 Flash",
                "value": "deepseek-v4-flash",
            },
            {
                "label": "DeepSeek V4 Pro",
                "value": "deepseek-v4-pro",
            },
        ],
    },

    "openai": {
        "label": "ChatGPT / OpenAI",
        "models": [
            {
                "label": "GPT-5.5",
                "value": "openai/gpt-5.5",
            },
            {
                "label": "GPT-5.5 Pro",
                "value": "openai/gpt-5.5-pro",
            },
            {
                "label": "GPT Chat Latest",
                "value": "openai/gpt-chat-latest",
            },
            {
                "label": "GPT-4.1",
                "value": "openai/gpt-4.1",
            },
        ],
    },

    "google": {
        "label": "Google Gemini",
        "models": [
            {
                "label": "Gemini 3.5 Flash",
                "value": "google/gemini-3.5-flash",
            },
            {
                "label": "Gemini 3.1 Pro Preview",
                "value": "google/gemini-3.1-pro-preview",
            },
            {
                "label": "Gemini 3.1 Flash Lite",
                "value": "google/gemini-3.1-flash-lite",
            },
            {
                "label": "Gemini 2.5 Pro",
                "value": "google/gemini-2.5-pro",
            },
        ],
    },

    "anthropic": {
        "label": "Claude",
        "models": [
            {
                "label": "Claude Opus 4.7 Fast",
                "value": "anthropic/claude-opus-4.7-fast",
            },
            {
                "label": "Claude Opus 4.7",
                "value": "anthropic/claude-opus-4.7",
            },
            {
                "label": "Claude Sonnet 4.6",
                "value": "anthropic/claude-sonnet-4.6",
            },
            {
                "label": "Claude Sonnet 4",
                "value": "anthropic/claude-sonnet-4",
            },
        ],
    },

    "xai": {
        "label": "Grok",
        "models": [
            {
                "label": "Grok 4.3",
                "value": "x-ai/grok-4.3",
            },
            {
                "label": "Grok 4.20",
                "value": "x-ai/grok-4.20",
            },
            {
                "label": "Grok Build 0.1",
                "value": "x-ai/grok-build-0.1",
            },
        ],
    },

    "qwen": {
        "label": "Qwen",
        "models": [
            {
                "label": "Qwen3.7 Max",
                "value": "qwen/qwen3.7-max",
            },
            {
                "label": "Qwen3.6 Max Preview",
                "value": "qwen/qwen3.6-max-preview",
            },
            {
                "label": "Qwen3.6 35B A3B",
                "value": "qwen/qwen3.6-35b-a3b",
            },
            {
                "label": "Qwen3.6 27B",
                "value": "qwen/qwen3.6-27b",
            },
        ],
    },

    "mistral": {
        "label": "Mistral",
        "models": [
            {
                "label": "Mistral Medium 3.5",
                "value": "mistralai/mistral-medium-3-5",
            },
            {
                "label": "Devstral Medium",
                "value": "mistralai/devstral-medium",
            },
            {
                "label": "Devstral Small",
                "value": "mistralai/devstral-small",
            },
            {
                "label": "Mistral Large 2411",
                "value": "mistralai/mistral-large-2411",
            },
        ],
    },
}

def get_default_model(provider):
    provider_config = MODEL_CATALOG.get(provider)

    if not provider_config:
        return None

    models = provider_config.get("models", [])

    if not models:
        return None

    return models[0].get("value")


def is_valid_provider(provider):
    return provider in MODEL_CATALOG


def is_valid_model(provider, model_name):
    provider_config = MODEL_CATALOG.get(provider)

    if not provider_config:
        return False

    models = provider_config.get("models", [])

    return any(model.get("value") == model_name for model in models)


def normalize_model_selection(provider, model_name):
    provider = (provider or "deepseek").lower().strip()

    if not is_valid_provider(provider):
        provider = "deepseek"

    if not model_name or not is_valid_model(provider, model_name):
        model_name = get_default_model(provider)

    return provider, model_name