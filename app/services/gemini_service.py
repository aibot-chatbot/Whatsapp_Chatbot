import logging
import os
import re
import json
import fitz  # PyMuPDF
from dotenv import load_dotenv
from google import genai
import glob
from app.services.settings_service import (
    get_settings,
    generate_greeting,
    generate_fallback,
    get_deployed_runtime,
)
from app.services.profile_service import get_profile_by_name
from app.database.chat_history_repository import get_recent_chat_history
from app.database.conversation_repository import get_or_create_conversation
from app.database.knowledge_chunk_repository import search_similar_chunks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

load_dotenv()

# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# model = genai.GenerativeModel("gemini-3-flash-preview")

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
model_id="gemini-2.5-flash"

MAX_HISTORY = 6

KNOWLEDGE_STATE_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "knowledge_state.json")
)


def save_active_pdf_state(pdf_path):
    state = {
        "active_pdf": pdf_path
    }

    with open(KNOWLEDGE_STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=4, ensure_ascii=False)


def load_active_pdf_state():
    if not os.path.exists(KNOWLEDGE_STATE_FILE):
        return None

    try:
        with open(KNOWLEDGE_STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data.get("active_pdf")
    except Exception:
        return None


def get_latest_pdf():
    pdf_files = glob.glob(os.path.join("data", "*.pdf"))
    if pdf_files:
        return max(pdf_files, key=os.path.getmtime)
    return "data/Speedbot.pdf"


def get_initial_pdf_path(chatbot_id=1):
    deployed = get_deployed_runtime(chatbot_id)
    deployed_pdf_path = deployed.get("deployed_pdf_path", "")

    if deployed_pdf_path and os.path.exists(deployed_pdf_path):
        logging.info(f"Loaded deployed PDF from chatbot runtime: {deployed_pdf_path}")
        return deployed_pdf_path

    logging.info("No deployed PDF found. No live PDF will be loaded.")
    return ""

def get_deployed_settings(chatbot_id=1):
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
            }

    return get_settings()


PDF_PATH = get_initial_pdf_path(1)

STOPWORDS = {
    "is", "am", "are", "the", "a", "an", "of", "to", "for", "and", "or", "in",
    "on", "at", "by", "with", "do", "does", "did", "what", "when", "how", "can",
    "i", "you", "we", "it", "this", "that", "my", "your", "our", "please"
}

ALIASES = {}

def load_pdf_text():
    if not PDF_PATH or not os.path.exists(PDF_PATH):
        logging.info("No active PDF found when loading PDF text.")
        return ""

    doc = fitz.open(PDF_PATH)
    lines = []

    for page in doc:
        blocks = page.get_text("blocks")
        blocks = sorted(blocks, key=lambda b: (b[1], b[0]))

        for block in blocks:
            text = block[4].strip()
            if text:
                for line in text.splitlines():
                    clean_line = " ".join(line.split())
                    if clean_line:
                        lines.append(clean_line)

    return "\n".join(lines)


def normalize_text(text):
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def normalize_for_search(text):
    text = normalize_text(text).lower()
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_query_words(text):
    words = re.findall(r"[a-z0-9]+", normalize_for_search(text))
    return [
        word for word in words
        if word not in STOPWORDS and len(word) > 1
    ]


def expand_query_words(query_words):
    expanded = set(query_words)

    for word in list(query_words):
        if word in ALIASES:
            expanded.update(ALIASES[word])

    for key, values in ALIASES.items():
        for value in values:
            if value in " ".join(query_words):
                expanded.update(values)

    return list(expanded)


def split_text_into_sections(text, max_chunk_length=900):
    text = normalize_text(text)

    if not text:
        return []

    # Best for FAQ documents like:
    # 1 Q: ...
    # A: ...
    if re.search(r"\b\d+\s+Q:", text, re.IGNORECASE):
        raw_sections = re.split(r"(?=\b\d+\s+Q:)", text)

    # Best for menu/code documents like:
    # A. Competitions
    # B. Books
    else:
        raw_sections = re.split(r'(?=\b[A-E](?:\d+(?:\.\d+)*)?\b\s*[:.])', text)

    chunks = []

    for section in raw_sections:
        section = section.strip()
        if not section:
            continue

        if len(section) <= max_chunk_length:
            chunks.append(section)
        else:
            parts = re.split(r'(?<=[.!?])\s+', section)
            current_chunk = ""

            for part in parts:
                part = part.strip()
                if not part:
                    continue

                if len(current_chunk) + len(part) + 1 <= max_chunk_length:
                    current_chunk += (" " if current_chunk else "") + part
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = part

            if current_chunk:
                chunks.append(current_chunk.strip())

    return chunks

PDF_TEXT = load_pdf_text()
PDF_CHUNKS = split_text_into_sections(PDF_TEXT)


def update_pdf_path(new_path):
    global PDF_PATH
    PDF_PATH = new_path or ""
    # save_active_pdf_state(PDF_PATH)  # no longer needed, Supabase handles active PDF
    logging.info(f"Updated global PDF_PATH to: {PDF_PATH}")
    reload_pdf()


def find_code_matches(query):
    query_upper = query.upper()
    codes = re.findall(r"\b[A-E](?:\d+(?:\.\d+)*)?\b", query_upper)

    if not codes:
        return []

    matched_chunks = []

    for code in codes:
        pattern = rf"\b{re.escape(code)}\b"
        for chunk in PDF_CHUNKS:
            if re.search(pattern, chunk.upper()):
                matched_chunks.append(chunk)

    unique_chunks = []
    seen = set()

    for chunk in matched_chunks:
        if chunk not in seen:
            unique_chunks.append(chunk)
            seen.add(chunk)

    return unique_chunks[:3]


def score_chunk(query, query_words, chunk):
    query_normalized = normalize_for_search(query)
    chunk_normalized = normalize_for_search(chunk)

    if not query_normalized or not chunk_normalized:
        return 0

    score = 0

    # Exact full question / phrase match
    if query_normalized in chunk_normalized:
        score += 10

    important_words = [word for word in query_words if len(word) >= 3]

    for word in important_words:
        if re.search(rf"\b{re.escape(word)}\b", chunk_normalized):
            score += 3
        elif word in chunk_normalized:
            score += 1

    # Bonus if most important words are inside the same chunk
    if important_words:
        matched_count = sum(1 for word in important_words if word in chunk_normalized)
        match_ratio = matched_count / len(important_words)

        if match_ratio >= 0.75:
            score += 8
        elif match_ratio >= 0.5:
            score += 4

    # FAQ bonus
    if " q " in f" {chunk_normalized} " and " a " in f" {chunk_normalized} ":
        score += 2

    return score

def generate_embedding(text):
    if not text:
        return []
    try:
        response = client.models.embed_content(
            model='gemini-embedding-2',
            contents=text,
            config={"output_dimensionality": 768}
        )
        return response.embeddings[0].values
    except Exception as e:
        logging.error(f"Error generating embedding: {e}")
        return []

def retrieve_relevant_chunks(query, chatbot_id=1, top_k=3):
    # 1. Generate embedding for the question
    query_embedding = generate_embedding(query)
    if not query_embedding:
        logging.warning("Could not generate embedding for query.")
        return []

    # 2. Search Supabase for similar chunks
    # match_threshold controls how strict the match should be (0.0 to 1.0)
    # usually 0.5 is a good starting point for cosine similarity
    try:
        results = search_similar_chunks(chatbot_id, query_embedding, match_threshold=0.5, match_count=top_k)
        if not results:
            logging.info("No strong chunk match found via vector search.")
            return []
        
        logging.info(f"Top chunk similarity: {results[0].get('similarity')}")
        return [res.get("content") for res in results]
    except Exception as e:
        logging.error(f"Vector search failed: {e}")
        return []

def build_prompt(history, message, context_chunks, chatbot_id=1):
    settings = get_deployed_settings(chatbot_id)

    bot_name = settings.get("bot_name") or "AI Assistant"
    company_name = settings.get("company_name") or "the company"
    business_description = settings.get("business_description") or "No business description provided."
    tone = settings.get("tone") or "Friendly"
    additional_instructions = settings.get("additional_instructions") or ""
    fallback_message = generate_fallback(settings)

    conversation = ""

    for item in history:
        if item["role"] == "user":
            conversation += f"User: {item['content']}\n"
        else:
            conversation += f"Assistant: {item['content']}\n"

    context = "\n\n".join(context_chunks)
    prompt_template = settings.get("custom_prompt", "").strip()

    if prompt_template:
        return prompt_template.format(
            bot_name=bot_name,
            company_name=company_name,
            business_description=business_description,
            tone=tone,
            additional_instructions=additional_instructions,
            fallback_message=fallback_message,
            context=context,
            conversation=conversation,
            message=message
        )

    prompt = f"""
You are {bot_name}, an AI assistant for {company_name}.

Company / business information:
{business_description}

Tone:
Reply in a {tone.lower()} tone.

Additional company instructions:
{additional_instructions if additional_instructions else "None"}

Knowledge provided:
{context if context else "No relevant knowledge was found."}

Recent conversation:
{conversation if conversation else "No recent conversation."}

User question:
{message}

Important rules:
1. Answer using the provided Knowledge first.
2. If the Knowledge contains the answer, answer directly.
3. If the question is related to the bot's business/domain but the Knowledge is incomplete, you may still provide a helpful general answer that fits the business context.
4. Do not invent exact company-specific facts, prices, policies, or guarantees that are not supported by the Knowledge.
5. For general domain questions, give a practical and helpful answer instead of refusing too quickly.
6. Keep the reply short, clear, and useful.
7. Do not mention internal words like "context", "chunks", "database", or "PDF".

Fallback style if the answer is not available:
{fallback_message}

Assistant:
"""
    return prompt


def detect_intent(message):
    msg = message.lower().strip()

    if msg in ["main", "main page", "menu", "home"]:
        return "main_menu"

    greeting_words = ["hi", "hello", "hey", "morning", "afternoon", "salam"]
    if msg in greeting_words:
        return "greeting"

    if re.fullmatch(r"[A-E](\d+(\.\d+)*)?", message.strip().upper()):
        return "code_input"

    registration_keywords = [
        "register", "registration", "sign up", "enroll", "enrol"
    ]

    registration_phrases = [
        "how do i join", "how to join", "how can i join",
        "how do i register", "how to register",
        "where do i register", "where can i register"
    ]

    registration_requirement_keywords = [
        "prerequisite", "pre-requisite", "requirement", "requirements",
        "eligibility", "eligible", "criteria", "condition"
    ]

    if any(phrase in msg for phrase in registration_phrases):
        return "registration"

    if any(word in msg for word in registration_keywords):
        return "registration"

    if any(word in msg for word in registration_requirement_keywords) and (
        "join" in msg or "register" in msg or "registration" in msg
    ):
        return "registration"

    approval_keywords = ["approved", "approval", "kpm", "moe", "ministry of education", "pajsk"]
    if any(word in msg for word in approval_keywords):
        return "approval"

    fee_keywords = ["fee", "fees", "price", "cost", "charges", "admin fee", "administration fee", "how much"]
    if any(word in msg for word in fee_keywords):
        return "fee"

    return "general"


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
        "recipe", "cooking", "food delivery"
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


def handle_greeting(chatbot_id=1):
    settings = get_deployed_settings(chatbot_id)
    base_greeting = generate_greeting(settings)

    return base_greeting + "\n\nFeel free to ask me any questions based on our provided information."


def format_structured_reply(main_text, extra_text=None, link=None):
    reply = main_text.strip()

    if extra_text:
        reply += f"\n\n{extra_text.strip()}"

    if link:
        reply += f"\n\n{link.strip()}"

    reply += "\n\nLet me know if there’s anything else I can help you with! 😊"
    return reply


def handle_registration(message, context_chunks):
    context = "\n\n".join(context_chunks)
    msg = message.lower()

    reply_parts = []

    if "olympicmaths.com" in context.lower():
        reply_parts.append(
            "You can register for TMC online through the official website:\n\nhttp://www.olympicmaths.com"
        )
    else:
        reply_parts.append(
            "You can register for TMC online through the official website."
        )

    if any(word in msg for word in [
        "prerequisite", "pre-requisite", "requirement", "requirements",
        "eligibility", "eligible", "criteria", "condition", "age"
    ]):
        reply_parts.append(
            "Based on the available information, there isn’t a specific prerequisite or eligibility requirement stated here. "
            "For exact requirements, it would be best to confirm with the admin."
        )

    return format_structured_reply("\n\n".join(reply_parts))


def handle_approval(context_chunks):
    context = "\n\n".join(context_chunks)

    if "approved" in context.lower() and ("moe" in context.lower() or "kpm" in context.lower()):
        links = re.findall(r'https?://\S+', context)
        extra = "Yes, we’re happy to share that this competition has been approved by the Ministry of Education (KPM/MOE)."

        if links:
            return format_structured_reply(
                extra,
                extra_text="You can refer to the approval documents here:",
                link="\n".join(links[:2])
            )

        return format_structured_reply(extra)

    return None


def handle_fee(context_chunks):
    context = "\n\n".join(context_chunks)

    sentences = re.split(r'(?<=[.!?])\s+', context)
    fee_sentences = [
        s for s in sentences
        if any(word in s.lower() for word in ["rm", "fee", "fees", "price", "cost", "administration fee"])
    ]

    if fee_sentences:
        return format_structured_reply("Here’s the fee information I found:", extra_text=" ".join(fee_sentences[:2]))

    return None


def extract_code_title_pairs():
    pairs = []
    lines = [line.strip() for line in PDF_TEXT.splitlines() if line.strip()]

    logging.info(f"PDF_TEXT length: {len(PDF_TEXT)}")

    pattern = re.compile(r'^([A-E](?:\d+(?:\.\d+)*)?)[\.:]?\s*(.+)$')

    for line in lines:
        match = pattern.match(line)
        if match:
            code = match.group(1).upper()
            title = normalize_text(match.group(2))

            if not re.match(r'^[A-E](?:\d+(?:\.\d+)*)?[\.:]', line):
                continue

            raw_title_part = match.group(2)

            if len(code) == 1 and not raw_title_part:
                continue

            if raw_title_part.lower().startswith("xamples"):
                continue
            if raw_title_part.lower().startswith("void"):
                continue
            if raw_title_part.lower().startswith("hatbotresponse"):
                continue
            if raw_title_part.lower().startswith("g:"):
                continue
            if raw_title_part.lower().startswith("iassistant"):
                continue
            if raw_title_part.lower().startswith("lwaysreply"):
                continue

            if title.lower().startswith("trigger keyword"):
                continue
            if title.lower().startswith("chatbot response"):
                continue
            if title.lower().startswith("please reply"):
                continue
            if title.lower().startswith("eg"):
                continue

            pairs.append((code, title))

    unique_pairs = []
    seen = set()

    for code, title in pairs:
        key = (code, title)
        if key not in seen:
            unique_pairs.append((code, title))
            seen.add(key)

    # Check for invalid menu structures (e.g., Q&A documents where every answer starts with 'A.')
    code_counts = {}
    for code, _ in unique_pairs:
        code_counts[code] = code_counts.get(code, 0) + 1

    # If any top-level code has multiple different titles, it's not a real structured menu
    for code, count in code_counts.items():
        if count > 3 and re.fullmatch(r'[A-E]', code):
            logging.info(f"Detected invalid menu structure (code {code} repeated {count} times). Disabling menu extraction.")
            return []

    return unique_pairs


CODE_TITLE_PAIRS = extract_code_title_pairs()


def reload_pdf():
    global PDF_TEXT, PDF_CHUNKS, CODE_TITLE_PAIRS
    logging.info("Reloading PDF into memory...")
    PDF_TEXT = load_pdf_text()
    PDF_CHUNKS = split_text_into_sections(PDF_TEXT)
    CODE_TITLE_PAIRS = extract_code_title_pairs()
    logging.info("PDF reloaded successfully!")


logging.info(f"Total code-title pairs: {len(CODE_TITLE_PAIRS)}")
logging.info(f"First 30 code-title pairs: {CODE_TITLE_PAIRS[:30]}")
logging.info(f"A-related pairs: {[item for item in CODE_TITLE_PAIRS if str(item[0]).startswith('A')]}")


def get_child_codes(parent_code):
    parent_code = parent_code.upper().strip()
    children = []
    seen_codes = set()

    logging.info(f"Checking children for parent_code: {parent_code}")

    for code, title in CODE_TITLE_PAIRS:
        if re.fullmatch(r'[A-E]', parent_code):
            if re.fullmatch(rf'{re.escape(parent_code)}\d+', code):
                if code not in seen_codes:
                    children.append((code, title))
                    seen_codes.add(code)

        elif re.fullmatch(r'[A-E]\d+', parent_code):
            if re.fullmatch(rf'{re.escape(parent_code)}\.\d+', code):
                if code not in seen_codes:
                    children.append((code, title))
                    seen_codes.add(code)

    logging.info(f"Matched children: {children}")
    return children


def get_exact_code_chunk(code):
    code = code.upper().strip()
    lines = [line.strip() for line in PDF_TEXT.splitlines() if line.strip()]

    start_pattern = re.compile(rf'^{re.escape(code)}(?=[\s:.]|$)', re.IGNORECASE)
    next_code_pattern = re.compile(r'^[A-E](?:\d+(?:\.\d+)*)\b', re.IGNORECASE)

    matches = []

    for i, line in enumerate(lines):
        if start_pattern.match(line):
            collected = [line]

            for j in range(i + 1, len(lines)):
                if next_code_pattern.match(lines[j]):
                    break
                collected.append(lines[j])

            matches.append(" ".join(collected))

    if not matches:
        return None

    for chunk in matches:
        lower_chunk = chunk.lower()
        if "chatbot response" in lower_chunk or "chatbotresponse" in lower_chunk:
            return chunk

    return max(matches, key=len)


def clean_code_answer(chunk, code):
    if not chunk:
        return None

    text = " ".join(chunk.split())

    match = re.search(r'Chatbot\s*Response\s*:\s*["“]?(.*?)(["”]?$)', text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r'ChatbotResponse\s*:\s*["“]?(.*?)(["”]?$)', text, flags=re.IGNORECASE)

    if match:
        text = match.group(1)
    else:
        text = re.sub(r'^.*?\b' + re.escape(code) + r'\b\s*[:.]?\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Trigger\s*Keyword\s*:.*?(?=Chatbot\s*Response\s*:|ChatbotResponse\s*:|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'TriggerKeyword\s*:.*?(?=Chatbot\s*Response\s*:|ChatbotResponse\s*:|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Chatbot\s*Response\s*:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'ChatbotResponse\s*:\s*', '', text, flags=re.IGNORECASE)

    text = re.sub(r'Please\s*reply\s*with\s*the\s*appropriate\s*code.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Eg\s*:.*', '', text, flags=re.IGNORECASE)
    text = text.strip().strip('"“”')

    return text.strip()


def format_menu_reply(title, items, max_items=12):
    clean_items = []
    seen_codes = set()

    for code, item_title in items:
        if code in seen_codes:
            continue

        item_title = normalize_text(item_title)

        if len(item_title) > 120:
            item_title = item_title[:117] + "..."

        clean_items.append((code, item_title))
        seen_codes.add(code)

    clean_items = clean_items[:max_items]

    lines = [title, ""]

    for code, item_title in clean_items:
        lines.append(f"{code}. {item_title}")

    lines.append("")
    lines.append("Please reply with the code you’d like to continue with 😊")

    reply = "\n".join(lines)

    if len(reply) > 3500:
        reply = reply[:3400] + "\n\nPlease reply with the code you’d like to continue with 😊"

    return reply


def handle_code_input(message, context_chunks=None):
    if context_chunks:
        return format_structured_reply(context_chunks[0])

    return "Sorry, I couldn’t find that information clearly. Please try asking in a different way."


def generate_response(message, wa_id, chatbot_id=1):
    try:
        conversation = get_or_create_conversation(
            chatbot_id=chatbot_id,
            customer_phone=wa_id,
            customer_name=None,
        )
        history = get_recent_chat_history(conversation["id"], limit=MAX_HISTORY)

        intent = detect_intent(message)
        logging.info(f"Detected intent: {intent}")

        msg = message.strip().lower()

        show_code_match = re.fullmatch(r'(show|open|see|list)\s+([A-E](?:\d+(?:\.\d+)*)?)', msg, re.IGNORECASE)
        if show_code_match:
            normalized_code = show_code_match.group(2).upper()
            reply = handle_code_input(normalized_code, retrieve_relevant_chunks(normalized_code, chatbot_id=chatbot_id))

        elif intent == "main_menu":
            reply = handle_greeting(chatbot_id)

        elif intent == "greeting":
            reply = handle_greeting(chatbot_id)


        else:

            context_chunks = retrieve_relevant_chunks(message, chatbot_id=chatbot_id)

            logging.info(f"Retrieved chunks: {len(context_chunks)}")

            logging.info(f"User message: {message}")

            if intent == "code_input":
                reply = handle_code_input(message, context_chunks)

            elif not context_chunks:
                settings = get_deployed_settings(chatbot_id)

                prompt = f"""
            You are a helpful AI assistant for {settings.get("company_name", "the company")}.

            Business description:
            {settings.get("business_description", "")}

            Tone:
            {settings.get("tone", "Friendly")}

            Additional instructions:
            {settings.get("additional_instructions", "")}

            User question:
            {message}

            Rules:
            1. The question is related to the business/domain, but there is no strong matching knowledge snippet.
            2. Give a helpful general answer that fits the business/domain.
            3. Do not invent exact company-specific facts, pricing, policies, or guarantees.
            4. Keep the answer practical, natural, and concise.
            5. Do not mention missing PDF, database, or internal system details.

            Assistant:
            """

                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt
                )

                reply = response.text.strip() if response.text else "Sorry, I’m not sure how to answer that right now."

            else:
                prompt = build_prompt(history, message, context_chunks, chatbot_id)

                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt
                )

                reply = response.text.strip() if response.text else "Sorry, I’m not sure how to answer that right now."

        return reply

    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return "Sorry, I’m having trouble replying right now."