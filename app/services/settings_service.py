import json
import os


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
            "additional_instructions": ""
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
        return f"Hello! Welcome to {company_name}. How may I assist you today?"
    elif tone.lower() == "formal":
        return f"Good day. Welcome to {company_name}. How may I assist you?"
    else:
        return f"Hi there! Welcome to {company_name} 😊 How can I help you today?"

def generate_fallback(settings):
    business_description = settings.get("business_description", "our services")

    short_desc = business_description.split(".")[0].strip()

    prefixes = [
        "we provide ",
        "we help ",
        "we offer ",
        "our business covers ",
        "our company provides "
    ]

    short_desc_lower = short_desc.lower()
    for prefix in prefixes:
        if short_desc_lower.startswith(prefix):
            short_desc = short_desc[len(prefix):]
            break

    return f"Sorry, I can only help with questions related to {short_desc}."