import logging

from app.database.bot_repository import (
    get_all_bots,
    get_archived_bots,
    get_bot_by_id,
    create_bot,
    update_bot,
    archive_bot,
    restore_bot,
    permanently_delete_archived_chatbot_rpc,
)

from app.services.model_catalog import (
    normalize_model_selection,
    is_model_allowed_for_tier,
    validate_provider_model_pair,
    get_model_tier,
    DEFAULT_PAID_PROVIDER,
    DEFAULT_PAID_MODEL,
)
from app.services.ai_access_policy import (
    resolve_ai_access,
    ROUTE_DIRECT_DEEPSEEK,
    ROUTE_OPENROUTER,
    OPENROUTER_PROVIDER_FAMILIES,
    TRIAL_PROVIDER,
    TRIAL_MODEL,
)
from app.services.profile_service import get_tones_for_chatbots

#: Key the API exposes for the tone that actually reaches the model. Kept
#: distinct from the legacy ``tone`` column on ``chatbots``, which nothing in
#: the reply pipeline reads and which no code writes any more.
CONFIG_TONE_FIELD = "config_tone"


class PermanentBotDeleteError(ValueError):
    def __init__(self, message, code="permanent_delete_failed"):
        super().__init__(message)
        self.code = code


def _with_config_tone(bots: list) -> list:
    """Attach the authoritative ``bot_configs`` tone to each bot row.

    One batched query for the whole page, not one per bot: the bot list is
    unbounded per company, so a per-row lookup would be an N+1 on the most
    frequently loaded screen.

    A tone lookup failure degrades to a blank tone rather than failing the
    list; the bots themselves are still worth showing.
    """
    if not bots:
        return bots

    deployed_profile_names = {
        bot.get("id"): bot.get("deployed_profile_name") or ""
        for bot in bots
    }

    try:
        tones = get_tones_for_chatbots(
            [bot.get("id") for bot in bots],
            deployed_profile_names,
        )
    except Exception as e:
        logging.error("Failed to resolve bot_configs tones for the bot list: %s", e)
        tones = {}

    return [
        {**bot, CONFIG_TONE_FIELD: tones.get(bot.get("id"), "")}
        for bot in bots
    ]


def list_bots(company_id):
    return _with_config_tone(get_all_bots(company_id))


def list_archived_bots(company_id):
    # Same card renderer as the active list, so it needs the same tone field.
    # Without this every archived bot would claim "Tone not set".
    return _with_config_tone(get_archived_bots(company_id))


def get_bot(bot_id, company_id):
    bot = get_bot_by_id(bot_id, company_id)

    if not bot:
        raise ValueError("Bot not found")

    return _with_config_tone([bot])[0]


def add_bot(data, company_id):
    bot_name = data.get("bot_name", "").strip()

    if not bot_name:
        raise ValueError("Bot name is required")

    data["bot_name"] = bot_name

    # Resolve AI access policy
    # Chatbot creation is NOT blocked by AI access denial.
    # It uses the policy only to determine the forced provider/model.
    # The actual AI generation is blocked at runtime.
    policy = resolve_ai_access(company_id)

    requested_provider = data.get("ai_provider")
    requested_model = data.get("model_name")

    if policy.api_route == ROUTE_DIRECT_DEEPSEEK:
        # Trial: force approved DeepSeek configuration
        if requested_provider is not None and requested_provider != TRIAL_PROVIDER:
            from app.services.billing_guard import BillingLimitError
            raise BillingLimitError(
                "During your trial period, only the DeepSeek AI provider is available.",
                code="trial_provider_restricted",
            )
        if requested_model is not None and requested_model != TRIAL_MODEL:
            from app.services.billing_guard import BillingLimitError
            raise BillingLimitError(
                "During your trial period, only the default DeepSeek model is available.",
                code="trial_model_restricted",
            )
        provider = TRIAL_PROVIDER
        model_name = TRIAL_MODEL
    elif policy.api_route == ROUTE_OPENROUTER:
        # Paid: reject DeepSeek, accept only OpenRouter provider families
        if requested_provider is not None and requested_provider not in OPENROUTER_PROVIDER_FAMILIES:
            from app.services.billing_guard import BillingLimitError
            raise BillingLimitError(
                "The selected AI provider is not available on your plan. "
                "Only OpenRouter-compatible providers are supported.",
                code="provider_not_available",
            )
        provider, model_name = normalize_model_selection(
            requested_provider,
            requested_model,
        )
        # Validate model tier against plan
        if not is_model_allowed_for_tier(model_name, policy.max_model_tier):
            from app.services.billing_guard import BillingLimitError
            raise BillingLimitError(
                "The selected model is not available on your plan. "
                "Please choose a model within your plan's allowed tier.",
                code="model_tier_denied",
            )
    else:
        from app.services.billing_guard import BillingLimitError
        raise BillingLimitError(
            policy.denial_reason or "AI access is not available.",
            code="ai_access_denied",
        )

    data["ai_provider"] = provider
    data["model_name"] = model_name

    bot = create_bot(data, company_id)

    if not bot:
        raise ValueError("Failed to create bot")

    return bot


def edit_bot(bot_id, data, company_id):
    existing_bot = get_bot_by_id(bot_id, company_id)

    if not existing_bot:
        raise ValueError("Bot not found")

    if "bot_name" in data:
        data["bot_name"] = data.get("bot_name", "").strip()

        if not data["bot_name"]:
            raise ValueError("Bot name cannot be empty")

    if "ai_provider" in data or "model_name" in data:
        # Resolve AI access policy
        policy = resolve_ai_access(company_id)

        if not policy.allowed:
            from app.services.billing_guard import BillingLimitError
            raise BillingLimitError(
                policy.denial_reason or "AI access is not available on your current plan.",
                code="ai_access_denied",
            )

        requested_provider = data.get("ai_provider") or existing_bot.get("ai_provider")
        requested_model = data.get("model_name") or existing_bot.get("model_name")

        # If the submitted values exactly match the enforced trial config
        # there is no real change - allow the save through.
        requested_is_trial_match = (
            requested_provider == TRIAL_PROVIDER
            and requested_model == TRIAL_MODEL
        )

        if not policy.model_editable and not requested_is_trial_match:
            from app.services.billing_guard import BillingLimitError
            raise BillingLimitError(
                "AI provider and model cannot be changed during your trial period.",
                code="trial_model_locked",
            )

        if policy.api_route == ROUTE_DIRECT_DEEPSEEK:
            if requested_provider != TRIAL_PROVIDER:
                from app.services.billing_guard import BillingLimitError
                raise BillingLimitError(
                    "During your trial period, only the DeepSeek AI provider is available.",
                    code="trial_provider_restricted",
                )
            provider = TRIAL_PROVIDER
            model_name = TRIAL_MODEL
        elif policy.api_route == ROUTE_OPENROUTER:
            if requested_provider not in OPENROUTER_PROVIDER_FAMILIES:
                from app.services.billing_guard import BillingLimitError
                raise BillingLimitError(
                    "The selected AI provider is not available on your plan. "
                    "Only OpenRouter-compatible providers are supported.",
                    code="provider_not_available",
                )
            provider, model_name = normalize_model_selection(
                requested_provider, requested_model,
            )
            # Validate model tier against plan
            if not is_model_allowed_for_tier(model_name, policy.max_model_tier):
                from app.services.billing_guard import BillingLimitError
                raise BillingLimitError(
                    "The selected model is not available on your plan. "
                    "Please choose a model within your plan's allowed tier.",
                    code="model_tier_denied",
                )
        else:
            from app.services.billing_guard import BillingLimitError
            raise BillingLimitError(
                policy.denial_reason or "AI access is not available.",
                code="ai_access_denied",
            )

        data["ai_provider"] = provider
        data["model_name"] = model_name

    bot = update_bot(bot_id, data, company_id)

    if not bot:
        raise ValueError("Failed to update bot")

    return bot


def remove_bot(bot_id, company_id):
    existing_bot = get_bot_by_id(bot_id, company_id, include_archived=True)

    if not existing_bot:
        raise ValueError("Bot not found")

    archived_bot = archive_bot(bot_id, company_id)

    if not archived_bot:
        raise ValueError("Bot not found")

    return archived_bot


def restore_archived_bot(bot_id, company_id):
    existing_bot = get_bot_by_id(bot_id, company_id, include_archived=True)

    if not existing_bot or existing_bot.get("status") != "archived":
        raise ValueError("Archived bot not found")

    from app.services.billing_guard import can_create_chatbot
    can_create_chatbot(company_id)

    restored_bot = restore_bot(bot_id, company_id)

    if not restored_bot:
        raise ValueError("Archived bot not found")

    return restored_bot


def permanently_delete_archived_bot(bot_id, company_id, confirm_bot_name):
    result = permanently_delete_archived_chatbot_rpc(
        bot_id,
        company_id,
        confirm_bot_name,
    )

    if not result:
        raise PermanentBotDeleteError(
            "Unable to permanently delete bot",
            code="empty_rpc_response",
        )

    if result.get("status") != "success":
        code = result.get("code") or "permanent_delete_failed"
        message = result.get("message") or "Unable to permanently delete bot"

        if code == "not_found":
            raise LookupError(message)

        raise PermanentBotDeleteError(message, code=code)

    return result
