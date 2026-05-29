from app.services.settings_service import generate_greeting
from app.services.rag_service import get_deployed_settings

MAX_HISTORY = 6


def is_out_of_scope(message):
    msg = message.lower().strip()

    out_keywords = [
        "weather", "temperature", "rain", "forecast",
        "football", "soccer", "match", "score", "basketball", "badminton",
        "movie", "film", "actor", "actress", "drama",
        "music", "song", "singer",
        "news", "politics", "election",
        "stock", "crypto", "bitcoin", "ethereum",
        "joke", "funny", "meme",
    ]

    out_phrases = [
        "tell me a joke",
        "who won",
        "what's the weather",
        "what is the weather",
        "latest news",
        "tell me something funny"
    ]

    if any(phrase in msg for phrase in out_phrases):
        return True

    return any(word in msg for word in out_keywords)


def format_structured_reply(main_text, extra_text=None, link=None):
    reply = main_text.strip()

    if extra_text:
        reply += f"\n\n{extra_text.strip()}"

    if link:
        reply += f"\n\n{link.strip()}"

    return reply


def detect_intent(message):
    msg = message.lower().strip()

    if msg in ["main", "main page", "menu", "home"]:
        return "main_menu"

    greeting_words = ["hi", "hello", "hey", "morning", "afternoon", "salam", "hai"]
    if msg in greeting_words:
        return "greeting"

    if is_out_of_scope(message):
        return "out_of_scope"

    return "general"


def handle_greeting(chatbot_id):
    settings = get_deployed_settings(chatbot_id)
    return generate_greeting(settings)


def handle_out_of_scope(chatbot_id):
    settings = get_deployed_settings(chatbot_id)
    company_name = settings.get("company_name") or "the company"

    return (
        f"I'm here to help with {company_name}-related questions. "
        "Could you ask something related to our services or information?"
    )
