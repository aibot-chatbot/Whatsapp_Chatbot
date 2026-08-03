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


# ---------------------------------------------------------------------------
# Model-tier classification for subscription plan enforcement (Phase 2B-2B)
# ---------------------------------------------------------------------------

MODEL_TIER_RANK = {
    'economy': 0,
    'standard': 1,
    'premium': 2,
}

MODEL_TIER_MAP = {
    # Economy
    'google/gemini-3.5-flash': 'economy',
    'google/gemini-3.1-flash-lite': 'economy',
    'qwen/qwen3.6-35b-a3b': 'economy',
    'qwen/qwen3.6-27b': 'economy',
    'mistralai/devstral-small': 'economy',
    # Standard
    'openai/gpt-4.1': 'standard',
    'openai/gpt-chat-latest': 'standard',
    'google/gemini-3.1-pro-preview': 'standard',
    'google/gemini-2.5-pro': 'standard',
    'anthropic/claude-sonnet-4': 'standard',
    'qwen/qwen3.7-max': 'standard',
    'qwen/qwen3.6-max-preview': 'standard',
    'mistralai/mistral-medium-3-5': 'standard',
    'mistralai/devstral-medium': 'standard',
    'mistralai/mistral-large-2411': 'standard',
    # Premium
    'openai/gpt-5.5': 'premium',
    'openai/gpt-5.5-pro': 'premium',
    'anthropic/claude-sonnet-4.6': 'premium',
    'anthropic/claude-opus-4.7': 'premium',
    'anthropic/claude-opus-4.7-fast': 'premium',
    'x-ai/grok-4.3': 'premium',
    'x-ai/grok-4.20': 'premium',
    'x-ai/grok-build-0.1': 'premium',
}

# Default provider and model for paid plan chatbot creation.
# Must exist in MODEL_CATALOG and be classified as economy.
DEFAULT_PAID_PROVIDER = 'google'
DEFAULT_PAID_MODEL = 'google/gemini-3.5-flash'


def get_model_tier(model_name):
    return MODEL_TIER_MAP.get(model_name)


def get_model_provider(model_name):
    for provider_key, config in MODEL_CATALOG.items():
        for m in config.get('models', []):
            if m.get('value') == model_name:
                return provider_key
    return None


def is_openrouter_model(model_name):
    provider = get_model_provider(model_name)
    return provider is not None and provider in OPENROUTER_PROVIDER_KEYS


def is_model_allowed_for_tier(model_name, maximum_tier):
    model_tier = get_model_tier(model_name)
    if model_tier is None:
        return False
    max_rank = MODEL_TIER_RANK.get(maximum_tier)
    if max_rank is None:
        return False
    return MODEL_TIER_RANK.get(model_tier, -1) <= max_rank


def validate_provider_model_pair(provider, model_name):
    provider = provider.lower().strip() if provider else provider
    if not provider or not model_name:
        raise ValueError('Both provider and model must be specified.')
    if not is_valid_provider(provider):
        raise ValueError(f'Unsupported AI provider: {provider}')
    if not is_valid_model(provider, model_name):
        raise ValueError(f"Model '{model_name}' is not valid for provider '{provider}'.")
    return provider, model_name



def get_default_model(provider):
    provider_config = MODEL_CATALOG.get(provider)

    if not provider_config:
        return None

    models = provider_config.get("models", [])

    if not models:
        return None

    return models[0].get("value")


def get_fallback_model(primary_provider, max_model_tier):
    """Select the best available model from an alternative provider that fits the user's tier."""
    if max_model_tier is None:
        return None, None
        
    if primary_provider == "deepseek":
        fallback_providers = ["openai", "google", "anthropic"]
    else:
        fallback_providers = [p for p in OPENROUTER_PROVIDER_KEYS if p != primary_provider]
        
    for provider in fallback_providers:
        config = MODEL_CATALOG.get(provider)
        if not config:
            continue
            
        models = config.get("models", [])
        best_model = None
        best_rank = -1
        
        for m in models:
            model_val = m.get("value")
            if is_model_allowed_for_tier(model_val, max_model_tier):
                model_tier = get_model_tier(model_val)
                model_rank = MODEL_TIER_RANK.get(model_tier, -1)
                if model_rank > best_rank:
                    best_rank = model_rank
                    best_model = model_val
                    
        if best_model:
            return provider, best_model
            
    return None, None


def is_valid_provider(provider):
    return provider in MODEL_CATALOG


def is_valid_model(provider, model_name):
    provider_config = MODEL_CATALOG.get(provider)

    if not provider_config:
        return False

    models = provider_config.get("models", [])

    return any(model.get("value") == model_name for model in models)



def get_models_with_tiers():
    """Return MODEL_CATALOG augmented with tier metadata per model.

    Each OpenRouter model dict receives a 'tier' key (economy/standard/premium).
    DeepSeek models receive 'access': 'trial_only'.
    Unknown models leave tier as None.
    This is backward compatible: existing fields are preserved.
    """
    result = {}
    for provider_key, config in MODEL_CATALOG.items():
        provider_entry = {
            'label': config['label'],
            'models': [],
        }
        for m in config.get('models', []):
            model_value = m['value']
            entry = dict(m)
            if model_value in MODEL_TIER_MAP:
                entry['tier'] = MODEL_TIER_MAP[model_value]
                entry['access'] = 'paid'
            elif provider_key in ('deepseek',):
                entry['tier'] = None
                entry['access'] = 'trial_only'
            else:
                entry['tier'] = None
                entry['access'] = 'paid'
            provider_entry['models'].append(entry)
        result[provider_key] = provider_entry
    return result



def normalize_model_selection(provider, model_name):
    provider = (provider or "default").lower().strip()

    if provider in ["default", "none", "null", ""]:
        provider = "openai"

    if not is_valid_provider(provider):
        raise ValueError(f"Unsupported AI provider: {provider}")

    if not model_name or not is_valid_model(provider, model_name):
        model_name = get_default_model(provider)

    return provider, model_name