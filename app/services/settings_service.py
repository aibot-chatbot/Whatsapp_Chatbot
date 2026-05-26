from datetime import datetime, timezone

from app.database.db import supabase
from app.services.profile_service import get_profile_by_name

TABLE_NAME = "bot_configs"
CHATBOTS_TABLE = "chatbots"

DEFAULT_SETTINGS = {
    "bot_name": "AI Assistant",
    "company_name": "Your Company",
    "business_description": "No business description provided.",
    "tone": "Friendly",
    "additional_instructions": "",
    "custom_prompt": "",
    "active_profile": "",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row_to_settings(row):
    if not row:
        return DEFAULT_SETTINGS.copy()

    return {
        "bot_name": row.get("bot_name") or "",
        "company_name": row.get("company_name") or "",
        "business_description": row.get("business_description")
        or row.get("business_objective")
        or "",
        "tone": row.get("tone") or row.get("response_style") or "",
        "additional_instructions": row.get("additional_instructions") or "",
        "custom_prompt": row.get("custom_prompt") or row.get("prompt_text") or "",
        "active_profile": row.get("profile_name") or "",
    }


def _get_active_config_row():
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        return None

    return rows[0]


def _get_chatbot_row(chatbot_id):
    response = (
        supabase
        .table(CHATBOTS_TABLE)
        .select("*")
        .eq("id", chatbot_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        return None

    return rows[0]


def update_chatbot_runtime(data, chatbot_id):
    payload = dict(data)
    payload["updated_at"] = _now_iso()

    response = (
        supabase
        .table(CHATBOTS_TABLE)
        .update(payload)
        .eq("id", chatbot_id)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to update chatbot runtime")

    return rows[0]


def get_draft_runtime(chatbot_id):
    row = _get_chatbot_row(chatbot_id) or {}

    return {
        "draft_profile_name": row.get("draft_profile_name") or "",
        "draft_pdf_file_name": row.get("draft_pdf_file_name") or "",
        "draft_pdf_path": row.get("draft_pdf_path") or "",
        "last_match_result": row.get("last_match_result"),
        "last_match_reason": row.get("last_match_reason") or "",
    }


def get_deployed_runtime(chatbot_id):
    row = _get_chatbot_row(chatbot_id) or {}

    return {
        "deployed_profile_name": row.get("deployed_profile_name") or "",
        "deployed_pdf_file_name": row.get("deployed_pdf_file_name") or "",
        "deployed_pdf_path": row.get("deployed_pdf_path") or "",
    }


def get_settings():
    active_row = _get_active_config_row()
    return _row_to_settings(active_row)


def update_settings(new_data, chatbot_id):
    current_settings = DEFAULT_SETTINGS.copy()

    existing_active_response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    existing_active_rows = existing_active_response.data or []

    if existing_active_rows:
        current_settings = _row_to_settings(existing_active_rows[0])

    current_settings.update(new_data)

    active_profile = current_settings.get("active_profile", "")

    if not active_profile:
        active_profile = "Default Profile"
        current_settings["active_profile"] = active_profile

    row_data = {
        "chatbot_id": chatbot_id,
        "profile_name": active_profile,
        "bot_name": current_settings.get("bot_name", ""),
        "company_name": current_settings.get("company_name", ""),
        "business_description": current_settings.get("business_description", ""),
        "tone": current_settings.get("tone", ""),
        "additional_instructions": current_settings.get("additional_instructions", ""),
        "custom_prompt": current_settings.get("custom_prompt", ""),
        "prompt_text": current_settings.get("custom_prompt", ""),
        "business_objective": current_settings.get("business_description", ""),
        "response_style": current_settings.get("tone", ""),
        "updated_at": _now_iso(),
        "is_active": True,
    }

    existing_response = (
        supabase
        .table(TABLE_NAME)
        .select("id")
        .eq("chatbot_id", chatbot_id)
        .eq("profile_name", active_profile)
        .limit(1)
        .execute()
    )

    existing_rows = existing_response.data or []

    if existing_rows:
        config_id = existing_rows[0]["id"]

        response = (
            supabase
            .table(TABLE_NAME)
            .update(row_data)
            .eq("id", config_id)
            .execute()
        )
    else:
        response = (
            supabase
            .table(TABLE_NAME)
            .insert(row_data)
            .execute()
        )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to update settings")

    return _row_to_settings(rows[0])


# =========================
# AUTO-GENERATED MESSAGES
# =========================

def generate_greeting(settings):
    company_name = settings.get("company_name", "our service")
    tone = settings.get("tone", "Friendly")

    if tone.lower() == "professional":
        return f"Hello! Welcome to {company_name}. How can I assist you today?"
    elif tone.lower() == "formal":
        return f"Good day. Welcome to {company_name}. How may I assist you today?"
    else:
        return f"Hi there! Welcome to {company_name} 😊 How can I help you today?"


def generate_fallback(settings):
    business_description = settings.get("business_description", "our services")

    short_desc = business_description.split(".")[0].strip().lower()

    prefixes = [
        "we provide ",
        "we help ",
        "we help guests with ",
        "we help customers with ",
        "we offer ",
        "our business covers ",
        "our company provides ",
    ]

    for prefix in prefixes:
        if short_desc.startswith(prefix):
            short_desc = short_desc[len(prefix):]
            break

    tone = settings.get("tone", "Friendly")

    if tone.lower() == "professional":
        return f"I'm here to assist with topics related to {short_desc}. Please feel free to ask about those."
    elif tone.lower() == "formal":
        return f"I can only assist with matters related to {short_desc}. Kindly provide a relevant inquiry."
    else:
        return f"Sorry, I can help with things like {short_desc} 😊 Try asking about those!"


def set_active_profile(profile_name, chatbot_id):
    if not profile_name:
        raise ValueError("Profile name is required")

    profile = get_profile_by_name(profile_name, chatbot_id)

    if not profile:
        raise ValueError("Profile not found")

    update_chatbot_runtime({
        "draft_profile_name": profile_name,
        "last_match_result": None,
        "last_match_reason": "",
    }, chatbot_id)

    return {
        "active_profile": profile_name,
        "bot_name": profile.get("bot_name", ""),
        "company_name": profile.get("company_name", ""),
        "business_description": profile.get("business_description", ""),
        "tone": profile.get("tone", ""),
        "additional_instructions": profile.get("additional_instructions", ""),
        "custom_prompt": profile.get("custom_prompt", ""),
    }


def apply_profile_to_settings(profile_name, chatbot_id):
    if not profile_name:
        raise ValueError("Profile name is required")

    profile = get_profile_by_name(profile_name, chatbot_id)

    if not profile:
        raise ValueError("Profile not found")

    draft_runtime = get_draft_runtime(chatbot_id)

    deployed_pdf_file_name = draft_runtime.get("draft_pdf_file_name", "")
    deployed_pdf_path = draft_runtime.get("draft_pdf_path", "")

    update_chatbot_runtime({
        "deployed_profile_name": profile_name,
        "deployed_pdf_file_name": deployed_pdf_file_name,
        "deployed_pdf_path": deployed_pdf_path,
        "last_match_result": draft_runtime.get("last_match_result"),
        "last_match_reason": draft_runtime.get("last_match_reason", ""),
    }, chatbot_id)

    return {
        "active_profile": profile_name,
        "bot_name": profile.get("bot_name", ""),
        "company_name": profile.get("company_name", ""),
        "business_description": profile.get("business_description", ""),
        "tone": profile.get("tone", ""),
        "additional_instructions": profile.get("additional_instructions", ""),
        "custom_prompt": profile.get("custom_prompt", ""),
        "deployed_pdf_file_name": deployed_pdf_file_name,
        "deployed_pdf_path": deployed_pdf_path,
    }

def get_deployed_settings_summary(chatbot_id):
    deployed = get_deployed_runtime(chatbot_id)
    deployed_profile_name = deployed.get("deployed_profile_name", "")

    if deployed_profile_name:
        profile = get_profile_by_name(deployed_profile_name, chatbot_id)
        if profile:
            return {
                "bot_name": profile.get("bot_name", ""),
                "company_name": profile.get("company_name", ""),
                "business_description": profile.get("business_description", ""),
                "tone": profile.get("tone", ""),
                "additional_instructions": profile.get("additional_instructions", ""),
                "custom_prompt": profile.get("custom_prompt", ""),
                "active_profile": deployed_profile_name,
                "active_pdf": deployed.get("deployed_pdf_file_name", ""),
            }

    return {
        "bot_name": "",
        "company_name": "",
        "business_description": "",
        "tone": "",
        "additional_instructions": "",
        "custom_prompt": "",
        "active_profile": "None",
        "active_pdf": deployed.get("deployed_pdf_file_name", "") or "None",
    }
