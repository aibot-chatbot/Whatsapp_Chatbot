from app.database.bot_repository import (
    get_all_bots,
    get_bot_by_id,
    create_bot,
    update_bot,
    delete_bot,
)

from app.services.model_catalog import normalize_model_selection


def list_bots(company_id):
    return get_all_bots(company_id)


def get_bot(bot_id, company_id):
    bot = get_bot_by_id(bot_id, company_id)

    if not bot:
        raise ValueError("Bot not found")

    return bot


def add_bot(data, company_id):
    bot_name = data.get("bot_name", "").strip()

    if not bot_name:
        raise ValueError("Bot name is required")

    data["bot_name"] = bot_name

    provider, model_name = normalize_model_selection(
        data.get("ai_provider"),
        data.get("model_name")
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
        provider, model_name = normalize_model_selection(
            data.get("ai_provider") or existing_bot.get("ai_provider"),
            data.get("model_name") or existing_bot.get("model_name")
        )

        data["ai_provider"] = provider
        data["model_name"] = model_name

    bot = update_bot(bot_id, data, company_id)

    if not bot:
        raise ValueError("Failed to update bot")

    return bot


def remove_bot(bot_id, company_id):
    existing_bot = get_bot_by_id(bot_id, company_id)

    if not existing_bot:
        raise ValueError("Bot not found")

    return delete_bot(bot_id, company_id)
