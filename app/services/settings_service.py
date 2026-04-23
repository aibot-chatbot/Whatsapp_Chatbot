import json
import os
from app.services.profile_service import get_profile_by_name

SETTINGS_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "settings_data.json")
)


def get_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {
            "bot_name": "OlympicEdu Assistant",
            "company_name": "Olympic Edu Sdn Bhd",
            "business_description": "We provide mathematics competitions, training programs, books, and educational services.",
            "tone": "Friendly",
            "additional_instructions": "",
            "custom_prompt": "",
            "active_profile": ""
        }

    with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def update_settings(new_data):
    current_settings = get_settings()

    # update only provided fields
    current_settings.update(new_data)

    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(current_settings, file, indent=4, ensure_ascii=False)

    return current_settings


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

    # Remove leading phrases
    prefixes = [
        "we provide ",
        "we help ",
        "we help guests with ",
        "we help customers with ",
        "we offer ",
        "our business covers ",
        "our company provides "
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
    current_settings = get_settings()
    current_settings["active_profile"] = profile_name or ""

    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(current_settings, file, indent=4, ensure_ascii=False)

    return current_settings

def apply_profile_to_settings(profile_name):
    if not profile_name:
        raise ValueError("Profile name is required")

    profile = get_profile_by_name(profile_name)
    if not profile:
        raise ValueError("Profile not found")

    current_settings = get_settings()

    current_settings["bot_name"] = profile.get("bot_name", "")
    current_settings["company_name"] = profile.get("company_name", "")
    current_settings["business_description"] = profile.get("business_description", "")
    current_settings["tone"] = profile.get("tone", "")
    current_settings["additional_instructions"] = profile.get("additional_instructions", "")
    current_settings["custom_prompt"] = profile.get("custom_prompt", "")
    current_settings["active_profile"] = profile.get("name", "")

    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(current_settings, file, indent=4, ensure_ascii=False)

    return current_settings