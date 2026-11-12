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
                "label": "Gemini 3.8 Flash Preview",
                "value": "google/gemini-3.8-flash-preview",
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
    'google/gemini-3.8-flash-preview': 'standard',
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

# The free trial runs on DeepSeek's own API; every paid plan runs on OpenRouter.
# No plan runs on Cloudflare now; its entries remain for saved-config recognition.
# Exact plan membership is authoritative.
CLOUDFLARE_PROVIDER = "cloudflare"
CLOUDFLARE_QWEN_MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"
CLOUDFLARE_MODELS = (
    {"label": "Qwen3 30B - Low", "value": CLOUDFLARE_QWEN_MODEL, "tier": "economy"},
    {"label": "GPT-OSS 20B - Medium", "value": "@cf/openai/gpt-oss-20b", "tier": "standard"},
    {"label": "Llama 3.3 70B - High", "value": "@cf/meta/llama-3.3-70b-instruct-fp8-fast", "tier": "premium"},
    {"label": "GPT-5.6 Sol", "value": "openai/gpt-5.6-sol", "tier": "premium"},
    {"label": "Claude Sonnet 5", "value": "anthropic/claude-sonnet-5", "tier": "premium"},
    {"label": "Gemini 3.8 Flash", "value": "google/gemini-3.8-flash", "tier": "premium"},
)
CLOUDFLARE_PLAN_MODELS = {}


def _paid(provider, label, value, tier):
    return {"provider": provider, "label": label, "value": value, "tier": tier}


_GPT_6_LUNA = _paid("openai", "GPT-6 Luna", "openai/gpt-6-luna", "standard")
_GEMINI_FLASH = _paid("google", "Gemini 3.8 Flash", "google/gemini-3.8-flash", "standard")
_CLAUDE_HAIKU = _paid("anthropic", "Claude Haiku 4.5", "anthropic/claude-haiku-4.5", "standard")
# Owner decision 2026-10-03: a famous brand on every paid tier. The first model of
# each plan is its default. IDs were checked against OpenRouter's live catalogue.
_PAID_CHOICES = {
    "essential": (_GPT_6_LUNA, _GEMINI_FLASH),
    "advanced": (_GPT_6_LUNA, _GEMINI_FLASH, _CLAUDE_HAIKU),
    "pro": (
        _paid("openai", "GPT-6.1 Sol", "openai/gpt-6.1-sol", "premium"),
        _paid("anthropic", "Claude Sonnet 5.5", "anthropic/claude-sonnet-5.5", "premium"),
        _paid("google", "Gemini 3.1 Pro", "google/gemini-3.1-pro-preview", "premium"),
    ),
}
# Each paid model carries every plan that offers it; the frontend gates on this list.
OPENROUTER_PLAN_MODELS = {
    plan: tuple(dict(m, plans=[p for p, choices in _PAID_CHOICES.items() if m in choices]) for m in models)
    for plan, models in _PAID_CHOICES.items()
}
PRO_MODELS = OPENROUTER_PLAN_MODELS["pro"]
# Owner decision 2026-10-16: the trial's one fixed model is back on DeepSeek's own API.
TRIAL_PLAN_MODELS = {
    "free": ({"provider": "deepseek", "label": "DeepSeek V4 Flash", "value": "deepseek-v4-flash",
              "tier": "economy", "plans": ["free"]},),
}
PLAN_CHOICES = dict(TRIAL_PLAN_MODELS, **OPENROUTER_PLAN_MODELS)
PLAN_MODELS = dict(
    CLOUDFLARE_PLAN_MODELS,
    **{plan: tuple(m["value"] for m in models) for plan, models in PLAN_CHOICES.items()},
)
for _models in OPENROUTER_PLAN_MODELS.values():
    for _model in _models:
        if not any(m["value"] == _model["value"] for m in MODEL_CATALOG[_model["provider"]]["models"]):
            MODEL_CATALOG[_model["provider"]]["models"].append(dict(_model))

for _model in CLOUDFLARE_MODELS:
    _model["plans"] = [plan for plan, models in CLOUDFLARE_PLAN_MODELS.items() if _model["value"] in models]

MODEL_CATALOG[CLOUDFLARE_PROVIDER] = {
    "label": "Cloudflare AI", "models": list(CLOUDFLARE_MODELS),
}
MODEL_TIER_MAP.update({m["value"]: m["tier"] for m in CLOUDFLARE_MODELS})
# After the Cloudflare entries: a model ID both lists share takes its paid-plan tier.
MODEL_TIER_MAP.update({m["value"]: m["tier"] for models in OPENROUTER_PLAN_MODELS.values() for m in models})
DEFAULT_PAID_PROVIDER = CLOUDFLARE_PROVIDER
DEFAULT_PAID_MODEL = CLOUDFLARE_QWEN_MODEL


def plan_code_for_policy(policy):
    state = policy.access_state
    if state in ("active_trial", "expired_trial", "free_no_trial"):
        return "free"
    return state if state in PLAN_MODELS else None


def default_model_for_plan(plan_code):
    models = PLAN_MODELS.get(plan_code, ())
    return models[0] if models else None


def default_provider_for_plan(plan_code):
    models = PLAN_CHOICES.get(plan_code)
    return models[0]["provider"] if models else CLOUDFLARE_PROVIDER


def plan_target_for(plan_code, current_provider):
    """Where a bot lands on this plan: its current brand's first model when the plan
    offers that brand (a Claude bot stays on Claude), otherwise the plan default."""
    same_brand = next((m for m in PLAN_CHOICES.get(plan_code, ())
                       if m["provider"] == current_provider), None)
    if same_brand:
        return same_brand["provider"], same_brand["value"]
    return default_provider_for_plan(plan_code), default_model_for_plan(plan_code)


def is_plan_selection(plan_code, provider, model):
    """True when this exact provider and model pair is offered on the plan."""
    return any(m["provider"] == provider and m["value"] == model
               for m in PLAN_CHOICES.get(plan_code, ()))


def validate_plan_selection(provider, model, policy):
    plan_code = plan_code_for_policy(policy)
    if plan_code not in PLAN_CHOICES:
        return validate_cloudflare_selection(provider, model, policy)
    from app.services.billing_guard import BillingLimitError
    # Customer-facing: name neither the provider nor the route that serves the model.
    if not is_plan_selection(plan_code, provider, model):
        raise BillingLimitError(
            "The selected model is not available on your plan. Choose an available model.",
            code="model_tier_denied",
        )
    return provider, model


def validate_cloudflare_selection(provider, model, policy):
    """Reject unsupported selections without replacing the requested model."""
    from app.services.billing_guard import BillingLimitError

    if provider != CLOUDFLARE_PROVIDER:
        raise BillingLimitError(
            "Choose a model available on your plan.",
            code="provider_not_available",
        )
    if model not in CLOUDFLARE_PLAN_MODELS.get(plan_code_for_policy(policy), ()):
        raise BillingLimitError(
            "The selected model is not available on your plan. Choose an available model.",
            code="model_tier_denied",
        )
    return provider, model


def get_models_for_plan(plan_code):
    grouped = {}
    for m in PLAN_CHOICES.get(plan_code, ()):
        group = grouped.setdefault(
            m["provider"], {"label": MODEL_CATALOG[m["provider"]]["label"], "models": []})
        group["models"].append(dict(m, access="trial_only" if plan_code == "free" else "paid"))
    return grouped


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


def is_valid_provider(provider):
    return provider in MODEL_CATALOG


def is_valid_model(provider, model_name):
    provider_config = MODEL_CATALOG.get(provider)

    if not provider_config:
        return False

    models = provider_config.get("models", [])

    return any(model.get("value") == model_name for model in models)



def get_models_with_tiers():
    """Return every enabled choice across plans; tenant routes must filter by exact plan."""
    merged = {}
    for plan in PLAN_MODELS:
        for provider, entry in get_models_for_plan(plan).items():
            group = merged.setdefault(provider, {"label": entry["label"], "models": []})
            group["models"].extend(m for m in entry["models"]
                                   if all(seen["value"] != m["value"] for seen in group["models"]))
    return merged



def normalize_model_selection(provider, model_name):
    provider = (provider or "default").lower().strip()

    if provider in ["default", "none", "null", ""]:
        provider = "openai"

    if not is_valid_provider(provider):
        raise ValueError(f"Unsupported AI provider: {provider}")

    if not model_name or not is_valid_model(provider, model_name):
        model_name = get_default_model(provider)

    return provider, model_name
