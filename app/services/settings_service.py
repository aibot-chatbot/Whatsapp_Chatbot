from datetime import datetime, timezone

from app.database.db import supabase
from app.services.profile_service import get_profile_by_name


TABLE_NAME = "bot_configs"


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


def get_settings():
    active_row = _get_active_config_row()
    return _row_to_settings(active_row)


def update_settings(new_data):
    current_settings = get_settings()
    current_settings.update(new_data)

    active_profile = current_settings.get("active_profile", "")

    if not active_profile:
        active_profile = "Default Profile"
        current_settings["active_profile"] = active_profile

    row_data = {
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


def set_active_profile(profile_name):
    if not profile_name:
        raise ValueError("Profile name is required")

    profile = get_profile_by_name(profile_name)

    if not profile:
        raise ValueError("Profile not found")

    (
        supabase
        .table(TABLE_NAME)
        .update({
            "is_active": False,
            "updated_at": _now_iso(),
        })
        .neq("id", 0)
        .execute()
    )

    response = (
        supabase
        .table(TABLE_NAME)
        .update({
            "is_active": True,
            "updated_at": _now_iso(),
        })
        .eq("profile_name", profile_name)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to set active profile")

    return _row_to_settings(rows[0])


def apply_profile_to_settings(profile_name):
    if not profile_name:
        raise ValueError("Profile name is required")

    return set_active_profile(profile_name)