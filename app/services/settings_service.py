import json
import os


SETTINGS_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "settings_data.json")
)


def get_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {
            "bot_name": "OlympicEdu",
            "greeting_message": "Hello! Thank you for reaching out. I’m your AI assistant, here to help you with anything you need. How can I assist you today? 😊",
            "fallback_message": "Sorry, I can only help with questions related to our programs, competitions, and services."
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