import logging
import re

from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot
from app.database.knowledge_file_repository import get_active_knowledge_file
from app.services.settings_service import generate_greeting
from app.services.rag_service import get_deployed_settings

MAX_HISTORY = 6
MAX_GREETING_MENU_LENGTH = 1000

MENU_PHRASES = [
    "please reply with the appropriate code",
    "based on your inquiry",
    "select one of the following",
    "choose an option",
    "choose one of the following",
]

MENU_STOP_RE = re.compile(
    r"^(eg|example|trigger keyword|chatbot response|preset answers?)\s*[:：]",
    re.IGNORECASE,
)
OPTION_LINE_RE = re.compile(r"^\s*[A-Z][\.\)]\s+\S+")


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

    if msg in ["main", "main page", "menu", "home", "start"]:
        return "main_menu"

    greeting_words = ["hi", "hello", "hey", "morning", "afternoon", "salam", "hai"]
    if msg in greeting_words:
        return "greeting"

    if is_out_of_scope(message):
        return "out_of_scope"

    return "general"


def _prepare_menu_text(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+(?=[A-Z][\.\)]\s+)", "\n", text)
    text = re.sub(
        r"\s+(?=(?:Eg|Example|Trigger Keyword|Chatbot Response|Preset Answers?)\s*[:：])",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_menu_lines(lines):
    cleaned = []
    option_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            if cleaned and cleaned[-1]:
                cleaned.append("")
            continue

        if MENU_STOP_RE.match(line) and option_count >= 2:
            break

        if OPTION_LINE_RE.match(line):
            option_count += 1
        elif option_count >= 3:
            break

        cleaned.append(line)

    while cleaned and not cleaned[-1]:
        cleaned.pop()

    return "\n".join(cleaned).strip()[:MAX_GREETING_MENU_LENGTH].strip()


def _extract_menu_from_chunk(content):
    text = _prepare_menu_text(content)
    if not text:
        return ""

    lower_text = text.lower()
    phrase_positions = [
        lower_text.find(phrase)
        for phrase in MENU_PHRASES
        if lower_text.find(phrase) >= 0
    ]

    if phrase_positions:
        menu_start = min(phrase_positions)
        menu_text = text[menu_start:]
        menu = _clean_menu_lines(menu_text.splitlines())
        if len(re.findall(r"(?m)^\s*[A-Z][\.\)]\s+\S+", menu)) >= 2:
            return menu

    lines = text.splitlines()
    for index in range(len(lines)):
        option_block = []
        for line in lines[index:]:
            if OPTION_LINE_RE.match(line):
                option_block.append(line.strip())
                continue
            break

        if len(option_block) >= 3:
            return "\n".join(option_block).strip()[:MAX_GREETING_MENU_LENGTH].strip()

    return ""


def get_primary_pdf_greeting_menu(chatbot_id):
    try:
        active_pdf = get_active_knowledge_file(chatbot_id)
        if not active_pdf:
            return ""

        file_id = active_pdf.get("id")
        if not file_id:
            return ""

        chunks = get_chunks_by_file_for_chatbot(chatbot_id, file_id)
        for chunk in chunks or []:
            menu = _extract_menu_from_chunk(chunk.get("content", ""))
            if menu:
                logging.info(
                    "[GreetingMenu] Found menu in active PDF file_id=%s chunk_id=%s",
                    file_id,
                    chunk.get("id"),
                )
                return menu

    except Exception as e:
        logging.warning(
            "[GreetingMenu] Failed to extract greeting menu for chatbot_id=%s: %s",
            chatbot_id,
            e,
        )

    return ""


def handle_greeting(chatbot_id):
    from app.database.bot_repository import get_bot_by_id

    bot = get_bot_by_id(chatbot_id)
    menu = get_primary_pdf_greeting_menu(chatbot_id)
    
    welcome_buttons = bot.get("welcome_menu_labels", []) if bot else []

    if bot and bot.get("welcome_message"):
        greeting = bot.get("welcome_message")
        if menu:
            greeting = f"{greeting}\n\n{menu}"
    else:
        settings = get_deployed_settings(chatbot_id)
        greeting = generate_greeting(settings)
        if menu:
            greeting = f"{greeting}\n\n{menu}"
            
    if welcome_buttons and isinstance(welcome_buttons, list):
        # Format the buttons tag to be picked up by telegram/whatsapp utils
        labels = " | ".join(welcome_buttons)
        greeting = f"{greeting}\n\n[BUTTONS: {labels}]"

    return greeting



def handle_out_of_scope(chatbot_id):
    settings = get_deployed_settings(chatbot_id)
    company_name = settings.get("company_name") or "the company"

    return (
        f"I'm here to help with {company_name}-related questions. "
        "Could you ask something related to our services or information?"
    )
