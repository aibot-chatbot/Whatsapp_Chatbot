import logging
import os
import re
import shelve
import fitz  #PyMuPDF
from dotenv import load_dotenv
import google.generativeai as genai
import glob

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

CHAT_HISTORY_DB = "chat_history_db"
MAX_HISTORY = 6

def get_latest_pdf():
    # Automatically find the most recently uploaded PDF in the data folder
    pdf_files = glob.glob(os.path.join("data", "*.pdf"))
    if pdf_files:
        return max(pdf_files, key=os.path.getmtime)
    return "data/Speedbot.pdf"

PDF_PATH = get_latest_pdf()

def update_pdf_path(new_path):
    global PDF_PATH
    PDF_PATH = new_path
    logging.info(f"Updated global PDF_PATH to: {PDF_PATH}")

STOPWORDS = {
    "is", "am", "are", "the", "a", "an", "of", "to", "for", "and", "or", "in",
    "on", "at", "by", "with", "do", "does", "did", "what", "when", "how", "can",
    "i", "you", "we", "it", "this", "that", "my", "your", "our", "please"
}

ALIASES = {
    "tmc": ["tmc", "tiger maths competition"],
    "asmo": ["asmo", "asian science & maths olympiad", "asian science and maths olympiad"],
    "kpm": ["kpm", "moe", "ministry of education"],
    "register": ["register", "registration", "sign up", "join", "enroll", "enrol"],
    "fee": ["fee", "fees", "price", "cost", "charges", "admin fee", "administration fee"],
    "result": ["result", "results", "announcement", "announced"],
    "date": ["date", "competition date", "schedule", "when"],
    "approved": ["approved", "approval", "moe", "kpm"],
}


# ===== LOAD PDF =====
def load_pdf_text():
    doc = fitz.open(PDF_PATH)
    lines = []

    for page in doc:
        blocks = page.get_text("blocks")
        blocks = sorted(blocks, key=lambda b: (b[1], b[0]))  # top → bottom

        for block in blocks:
            text = block[4].strip()
            if text:
                for line in text.splitlines():
                    clean_line = " ".join(line.split())
                    if clean_line:
                        lines.append(clean_line)

    return "\n".join(lines)


# ===== CLEAN TEXT =====
def normalize_text(text):
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_query_words(text):
    words = re.findall(r"[A-Za-z0-9.]+", text.lower())
    return [word for word in words if word not in STOPWORDS]


def expand_query_words(query_words):
    expanded = set(query_words)

    for word in list(query_words):
        if word in ALIASES:
            expanded.update(ALIASES[word])

    # cross-add related aliases when query contains one of the values
    for key, values in ALIASES.items():
        for value in values:
            if value in " ".join(query_words):
                expanded.update(values)

    return list(expanded)


# ===== SPLIT INTO BETTER CHUNKS =====
def split_text_into_sections(text, max_chunk_length=900):
    text = normalize_text(text)

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


# ===== DIRECT CODE MATCH =====
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


# ===== IMPROVED RETRIEVAL =====
def score_chunk(query, query_words, chunk):
    chunk_lower = chunk.lower()
    score = 0

    for word in query_words:
        if word in chunk_lower:
            score += 2

    # exact phrase bonus
    if query.lower() in chunk_lower:
        score += 6

    # strong FAQ signal boosts
    if "register" in query_words or "registration" in query_words or "sign up" in query.lower():
        if "register" in chunk_lower or "registration" in chunk_lower:
            score += 8

    if "tmc" in query_words or "tiger maths competition" in query.lower():
        if "tmc" in chunk_lower or "tiger maths competition" in chunk_lower:
            score += 5

    if "asmo" in query_words:
        if "asmo" in chunk_lower:
            score += 5

    if "approved" in query_words or "kpm" in query_words or "moe" in query_words:
        if "approved" in chunk_lower or "kpm" in chunk_lower or "moe" in chunk_lower:
            score += 7

    if "fee" in query_words or "fees" in query_words or "price" in query_words or "cost" in query_words:
        if "fee" in chunk_lower or "fees" in chunk_lower or "price" in chunk_lower or "cost" in chunk_lower:
            score += 7

    return score


def retrieve_relevant_chunks(query, top_k=3):
    direct_matches = find_code_matches(query)
    if direct_matches:
        logging.info("Using direct code match retrieval.")
        return direct_matches

    base_words = clean_query_words(query)
    query_words = expand_query_words(base_words)

    scored_chunks = []

    for chunk in PDF_CHUNKS:
        score = score_chunk(query, query_words, chunk)
        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)

    selected = [chunk for score, chunk in scored_chunks[:top_k]]

    if not selected:
        logging.info("No strong chunk match found, using fallback chunk.")
        return PDF_CHUNKS[:1]

    logging.info(f"Top chunk score: {scored_chunks[0][0] if scored_chunks else 0}")
    return selected


# ===== CHAT HISTORY =====
def load_chat_history(wa_id):
    with shelve.open(CHAT_HISTORY_DB) as db:
        return db.get(wa_id, [])


def save_chat_history(wa_id, history):
    with shelve.open(CHAT_HISTORY_DB, writeback=True) as db:
        db[wa_id] = history

# ===== BUILD PROMPT =====
def build_prompt(history, message, context_chunks):
    conversation = ""

    for item in history:
        if item["role"] == "user":
            conversation += f"User: {item['content']}\n"
        else:
            conversation += f"Assistant: {item['content']}\n"

    context = "\n\n".join(context_chunks)

    prompt = f"""
You are OlympicEdu, a helpful WhatsApp assistant for Tiger Maths Competition.

Follow these rules strictly:
- Be warm, friendly, and natural.
- Sound like a real human assistant, not like a copied FAQ page.
- Keep replies clear, short, and helpful.
- Do not use asterisks.
- Do not mention that you are an AI unless necessary.
- Use ONLY the provided knowledge below as the factual source.
- Do not invent facts, policies, requirements, dates, fees, eligibility, links, or promises that are not supported by the knowledge.
- If the answer is clearly found in the knowledge, answer naturally in your own words.
- If the user asks a related question but the answer is not stated directly, give a careful and helpful general reply based on the available knowledge.
- When information is incomplete, say "based on the available information" or similar natural wording.
- Start by mentioning what is known before saying what is not known.
- Do not start too quickly with "I’m not sure" or "I don’t know" if there is still useful related information in the knowledge.
- Suggest contacting admin only when the answer truly needs confirmation or is not available in the knowledge.
- Do not promise actions you cannot actually perform.
- Do not say things like "I can check for you", "I can guide you better", or "I can recommend the best option" unless that is clearly supported by the knowledge and system.
- If a link is provided in the knowledge and is relevant, include it.
- Keep the answer focused on the user’s exact question.
- Do not repeat the full main menu unless the user is asking for the menu, main page, home, or available options.
- If the user asks something unrelated to Tiger Maths Competition, books, training, business opportunities, or the live streaming portal, politely explain that you can help only with the provided company-related information and invite the user to choose a menu option.
- For related questions about suitability, difficulty, age, or general learning concerns, give a careful, general answer based on the available information without making unsupported claims.
- If the knowledge does not clearly answer a related question, do not guess. Give a safe, helpful response and suggest admin only if necessary.
- Avoid sounding too formal, repetitive, robotic, or defensive.

Preferred answer style:
- First, answer the user’s question directly.
- Second, mention any important limitation naturally if needed.
- Third, suggest the next step only if it is useful.
- Keep most replies to one short paragraph or two short paragraphs.

Knowledge:
{context}

Recent conversation:
{conversation}

User: {message}
Assistant:
"""
    return prompt

def detect_intent(message):
    msg = message.lower().strip()

    greeting_words = ["hi", "hello", "hey", "morning", "afternoon", "salam"]
    if msg in greeting_words:
        return "greeting"

    if re.fullmatch(r"[A-E](\d+(\.\d+)*)?", message.strip().upper()):
        return "code_input"

    registration_keywords = [
        "register", "registration", "sign up", "join", "enroll", "enrol",
        "prerequisite", "pre-requisite", "requirement", "requirements",
        "eligibility", "eligible", "criteria", "condition"
    ]
    if any(word in msg for word in registration_keywords):
        return "registration"

    approval_keywords = ["approved", "approval", "kpm", "moe", "ministry of education", "pajsk"]
    if any(word in msg for word in approval_keywords):
        return "approval"

    fee_keywords = ["fee", "fees", "price", "cost", "charges", "admin fee", "administration fee", "how much"]
    if any(word in msg for word in fee_keywords):
        return "fee"

    return "general"

def is_out_of_scope(message):
    msg = message.lower()

    out_keywords = [
        "weather", "temperature", "rain",
        "football", "soccer", "match", "score",
        "movie", "film", "actor",
        "music", "song",
        "news", "politics",
        "stock", "crypto", "bitcoin",
        "joke", "funny"
    ]

    return any(word in msg for word in out_keywords)

def handle_greeting():
    base_greeting = "Hello! Thank you for reaching out. I’m your AI assistant, here to help you with anything you need. How can I assist you today? 😊\n\n"
    
    top_level_codes = [pair for pair in CODE_TITLE_PAIRS if re.fullmatch(r'[A-E]', pair[0])]
    
    if top_level_codes:
        menu = "Please reply with the appropriate code based on your inquiry:\n"
        for code, title in top_level_codes:
            menu += f"{code}. {title}\n"
        return base_greeting + menu.strip()
    
    return base_greeting + "Feel free to ask me any questions based on our provided information."

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

    # Safely print without crashing Windows console
    logging.info(f"PDF_TEXT length: {len(PDF_TEXT)}")
    
    pattern = re.compile(r'^([A-E](?:\d+(?:\.\d+)*)?)[\.:]?\s*(.+)$')

    for line in lines:
        match = pattern.match(line)
        if match:
            code = match.group(1).upper()
            title = normalize_text(match.group(2))

            # ✅ ADD THIS FILTER
            if not re.match(r'^[A-E](?:\d+(?:\.\d+)*)?[\.:]', line):
                continue

            raw_code_part = match.group(1)
            raw_title_part = match.group(2)

            # skip obvious fake matches from normal words like Examples, Avoid, ChatbotResponse
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

    return unique_pairs


CODE_TITLE_PAIRS = extract_code_title_pairs()

def reload_pdf():
    global PDF_TEXT, PDF_CHUNKS, CODE_TITLE_PAIRS
    logging.info("Reloading PDF into memory...")
    PDF_TEXT = load_pdf_text()
    PDF_CHUNKS = split_text_into_sections(PDF_TEXT)
    CODE_TITLE_PAIRS = extract_code_title_pairs()
    logging.info("PDF reloaded successfully!")

print("Total code-title pairs:", len(CODE_TITLE_PAIRS))
print("First 30 code-title pairs:", CODE_TITLE_PAIRS[:30])
print("A-related pairs:", [item for item in CODE_TITLE_PAIRS if str(item[0]).startswith("A")])

def get_child_codes(parent_code):
    parent_code = parent_code.upper().strip()
    children = []
    seen_codes = set()

    print("Checking children for parent_code:", parent_code)

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

    print("Matched children:", children)
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

    # Prefer the detailed section with chatbot response
    for chunk in matches:
        lower_chunk = chunk.lower()
        if "chatbot response" in lower_chunk or "chatbotresponse" in lower_chunk:
            return chunk

    # Otherwise return the longest exact match
    return max(matches, key=len)

def clean_code_answer(chunk, code):
    if not chunk:
        return None

    text = " ".join(chunk.split())

    # try to extract only chatbot response first
    match = re.search(r'Chatbot\s*Response\s*:\s*["“]?(.*?)(["”]?$)', text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r'ChatbotResponse\s*:\s*["“]?(.*?)(["”]?$)', text, flags=re.IGNORECASE)

    if match:
        text = match.group(1)
    else:
        # fallback cleanup if response label is not found
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
    code = message.strip().upper()

    child_items = get_child_codes(code)
    print("Code input received:", code)
    print("Child items for code:", child_items)

    exact_chunk = get_exact_code_chunk(code)
    print("Exact chunk for code:", exact_chunk)

    cleaned = clean_code_answer(exact_chunk, code)
    print("Cleaned answer for code:", cleaned)
    if child_items:
        if re.fullmatch(r'[A-E]', code):
            return format_menu_reply(f"Here are the options for {code}:", child_items)

        if re.fullmatch(r'[A-E]\d+', code):
            return format_menu_reply(f"Here are the available options under {code}:", child_items)

    exact_chunk = get_exact_code_chunk(code)
    cleaned = clean_code_answer(exact_chunk, code)

    if cleaned:
        if "need update by admin" in cleaned.lower():
            return format_structured_reply(
                "The detailed information for this item is not available yet.",
                extra_text="Please contact the admin staff for the latest update."
            )

        return format_structured_reply(cleaned)

    if context_chunks:
        return format_structured_reply(context_chunks[0])

    return "Sorry, I couldn’t find that menu option clearly. Please try another code."

# ===== MAIN FUNCTION =====
def generate_response(message, wa_id):
    try:
        history = load_chat_history(wa_id)

        intent = detect_intent(message)
        logging.info(f"Detected intent: {intent}")

        msg = message.strip().lower()

        show_code_match = re.fullmatch(r'(show|open|see|list)\s+([A-E](?:\d+(?:\.\d+)*)?)', msg, re.IGNORECASE)
        if show_code_match:
            normalized_code = show_code_match.group(2).upper()
            reply = handle_code_input(normalized_code, retrieve_relevant_chunks(normalized_code))

        elif msg in ["main", "main page", "menu", "home"]:
            reply = handle_greeting()

        elif intent == "greeting":
            reply = handle_greeting()

        else:
            if is_out_of_scope(message):
                return format_structured_reply(
                    "I’m here to help with information related to our programs and competitions.",
                    extra_text="Please reply with A, B, C, D, or E to explore available options."
                )

            context_chunks = retrieve_relevant_chunks(message)
            logging.info(f"Retrieved chunks: {len(context_chunks)}")
            logging.info(f"User message: {message}")

            if intent == "registration":
                reply = handle_registration(message, context_chunks)

            elif intent == "approval":
                reply = handle_approval(context_chunks)

            elif intent == "fee":
                reply = handle_fee(context_chunks)

            elif intent == "code_input":
                reply = handle_code_input(message, context_chunks)

            else:
                reply = None

            if not reply:
                prompt = build_prompt(history, message, context_chunks)
                response = model.generate_content(prompt)
                reply = response.text.strip() if response.text else "Sorry, I’m not sure how to answer that right now."

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})

        history = history[-MAX_HISTORY:]
        save_chat_history(wa_id, history)

        return reply

    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return "Sorry, I’m having trouble replying right now."