import logging
import os
import re
from dotenv import load_dotenv
from google import genai

from app.services.settings_service import (
    DEFAULT_SETTINGS,
    generate_fallback,
    get_deployed_runtime,
)
from app.services.profile_service import get_profile_by_name
from app.database.knowledge_chunk_repository import search_similar_chunks, get_chunks_by_file
from app.database.knowledge_file_repository import get_active_knowledge_file

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

STOPWORDS = {
    "is", "am", "are", "the", "a", "an", "of", "to", "for", "and", "or", "in",
    "on", "at", "by", "with", "do", "does", "did", "what", "when", "how", "can",
    "i", "you", "we", "it", "this", "that", "my", "your", "our", "please"
}

def get_deployed_settings(chatbot_id):
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

    return DEFAULT_SETTINGS.copy()


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


def clean_text_for_chunking(text):
    """
    Clean PDF text while keeping line breaks.
    This is important because Q:, A:, headings, and sections often depend on line structure.
    """
    if not text:
        return ""

    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")

    # Remove parsed page markers if they appear from any PDF parser/debug output
    text = re.sub(r"<PARSED TEXT FOR PAGE:\s*\d+\s*/\s*\d+>", "\n", text)

    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def is_probable_heading(line):
    """
    Generic heading detector.
    Not travel-specific. Works for sections like:
    1. PRODUCT FAQ
    2. PRICING
    COMPANY POLICY
    A. RETURN POLICY
    """
    line = line.strip()

    if not line or len(line) > 120:
        return False

    # Numbered uppercase headings, e.g. "3. ACCOMMODATION & BOOKING"
    if re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z0-9][A-Z0-9 &,/+\-()]{4,}$", line):
        return True

    # Lettered / uppercase headings, e.g. "A. REFUND POLICY"
    if re.match(r"^[A-Z](?:\d+(?:\.\d+)*)?[\).]\s+[A-Z0-9][A-Z0-9 &,/+\-()]{4,}$", line):
        return True

    # Plain uppercase heading, e.g. "PAYMENT METHODS"
    letters = re.sub(r"[^A-Za-z]", "", line)
    if len(letters) >= 5 and line.upper() == line:
        if not line.startswith(("Q:", "A:")):
            return True

    return False


def get_last_heading(before_text):
    """
    Finds the nearest heading before a Q&A section.
    This lets the bot become category-aware based on the PDF content,
    without hardcoding travel, hotel, booking, etc.
    """
    lines = [line.strip() for line in before_text.splitlines() if line.strip()]

    for line in reversed(lines):
        if is_probable_heading(line):
            return re.sub(r"\s+", " ", line).strip()

    return ""


def split_long_text(text, max_chunk_length=1400, overlap=150):
    """
    Splits long chunks safely.
    Uses sentences first. If a sentence is too long, splits by characters.
    """
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return []

    if len(text) <= max_chunk_length:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        if len(current_chunk) + len(sentence) + 1 <= max_chunk_length:
            current_chunk += (" " if current_chunk else "") + sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())

            if len(sentence) > max_chunk_length:
                step = max_chunk_length - overlap
                for i in range(0, len(sentence), step):
                    chunks.append(sentence[i:i + max_chunk_length].strip())
                current_chunk = ""
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def clean_qa_section(raw_section):
    """
    Removes trailing headings that appear between one Q&A and the next Q&A.
    Example:
    Q: ...
    A: ...
    4. NEXT SECTION
    """
    lines = [line.strip() for line in raw_section.splitlines() if line.strip()]

    while lines and is_probable_heading(lines[-1]):
        lines.pop()

    return " ".join(lines).strip()


def split_general_sections(text, max_chunk_length=1400):
    """
    Fallback splitter for non-Q&A PDFs.
    This keeps the system general for company profiles, policies, product docs,
    restaurant menus, school guides, clinic FAQs, property brochures, etc.
    """
    text = clean_text_for_chunking(text)

    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    chunks = []
    current_title = ""
    current_lines = []

    def flush_chunk():
        nonlocal current_lines, current_title, chunks

        if not current_lines:
            return

        body = " ".join(current_lines)
        body = re.sub(r"\s+", " ", body).strip()

        if current_title:
            chunk = f"Section: {current_title}\n{body}"
        else:
            chunk = body

        chunks.extend(split_long_text(chunk, max_chunk_length=max_chunk_length))
        current_lines = []

    for line in lines:
        if is_probable_heading(line):
            flush_chunk()
            current_title = re.sub(r"\s+", " ", line).strip()
        else:
            current_lines.append(line)

            current_length = sum(len(item) for item in current_lines)
            if current_length >= max_chunk_length:
                flush_chunk()

    flush_chunk()

    return [chunk for chunk in chunks if len(chunk) > 30]


def split_text_into_sections(text, max_chunk_length=1400):
    """
    General PDF chunking strategy.

    Priority 1:
    If the PDF has Q&A structure, split each Q&A as one clean chunk.

    Priority 2:
    If the PDF is not Q&A, split by generic headings and section content.

    This is NOT hardcoded for travel.
    It works based on document structure.
    """
    cleaned_text = clean_text_for_chunking(text)

    if not cleaned_text:
        return []

    question_pattern = re.compile(
        r"(?im)^\s*(?:\d+[\).]\s*)?(?:Q|Question)\s*[:\-]\s*"
    )

    answer_pattern = re.compile(
        r"(?im)^\s*(?:A|Answer)\s*[:\-]\s*"
    )

    question_matches = list(question_pattern.finditer(cleaned_text))

    # Q&A mode
    if len(question_matches) >= 2 and answer_pattern.search(cleaned_text):
        chunks = []

        for idx, match in enumerate(question_matches):
            start = match.start()
            end = (
                question_matches[idx + 1].start()
                if idx + 1 < len(question_matches)
                else len(cleaned_text)
            )

            section_title = get_last_heading(cleaned_text[:start])
            raw_section = cleaned_text[start:end].strip()
            raw_section = clean_qa_section(raw_section)
            raw_section = re.sub(r"\s+", " ", raw_section).strip()

            if not raw_section:
                continue

            if section_title:
                chunk = f"Section: {section_title}\n{raw_section}"
            else:
                chunk = raw_section

            chunks.extend(split_long_text(chunk, max_chunk_length=max_chunk_length))

        return [chunk for chunk in chunks if len(chunk) > 30]

    # General document mode
    return split_general_sections(cleaned_text, max_chunk_length=max_chunk_length)


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


def retrieve_relevant_chunks(query, chatbot_id, top_k=3):
    try:
        active_file = get_active_knowledge_file(chatbot_id)

        if not active_file:
            logging.warning(f"No active knowledge file found for chatbot {chatbot_id}.")
            return ["No relevant knowledge found, but answer using your general domain knowledge in a helpful and friendly way."]

        active_file_id = active_file.get("id")
        logging.info(f"Using active knowledge file ID: {active_file_id}")

        # 1. First try keyword/FAQ matching inside active file only
        file_chunks = get_chunks_by_file(active_file_id)
        query_words = clean_query_words(query)

        scored_chunks = []

        for chunk in file_chunks:
            content = chunk.get("content", "")
            score = score_chunk(query, query_words, content)

            if score > 0:
                scored_chunks.append({
                    "content": content,
                    "score": score
                })

        scored_chunks = sorted(
            scored_chunks,
            key=lambda item: item["score"],
            reverse=True
        )

        if scored_chunks and scored_chunks[0]["score"] >= 8:
            logging.info(f"Keyword match found in active file. Top score: {scored_chunks[0]['score']}")

            for idx, item in enumerate(scored_chunks[:top_k], start=1):
                logging.info(f"Keyword chunk {idx} score: {item['score']}")
                logging.info(f"Keyword chunk {idx} content: {item['content']}")

            return [item["content"] for item in scored_chunks[:top_k]]

        # 2. If keyword match is not strong, use vector search inside active file only
        query_embedding = generate_embedding(query)

        if not query_embedding:
            logging.warning("Could not generate embedding for query.")
            return ["No relevant knowledge found, but answer using your general domain knowledge in a helpful and friendly way."]

        results = search_similar_chunks(
            chatbot_id=chatbot_id,
            query_embedding=query_embedding,
            match_threshold=0.45,
            match_count=top_k,
            file_id=active_file_id
        )

        if not results:
            logging.info("No strong chunk match found via active-file vector search.")
            return ["No relevant knowledge found, but answer using your general domain knowledge in a helpful and friendly way."]

        logging.info(f"Top chunk similarity: {results[0].get('similarity')}")

        for idx, res in enumerate(results, start=1):
            logging.info(f"Retrieved chunk {idx} similarity: {res.get('similarity')}")
            logging.info(f"Retrieved chunk {idx} content: {res.get('content')}")

        return [res.get("content") for res in results]
    
    except Exception as e:
        logging.error(f"Retrieve relevant chunks failed: {e}")
        return ["No relevant knowledge found, but answer using your general domain knowledge in a helpful and friendly way."]

def build_rag_prompt(message, context_chunks):
    """
    Simplified prompt builder for external providers (DeepSeek, Groq, etc.)
    """
    context = "\n\n".join(context_chunks)
    prompt = f"""
Use the following context to answer the user's question. 
If you don't know the answer based on the context, answer politely based on general knowledge but stay within the business domain.

Context:
{context}

User Question:
{message}

Answer:
"""
    return prompt


def build_prompt(history, message, context_chunks, chatbot_id):
    """
    Optimized prompt builder for any LLM bot.
    Uses retrieved chunks if any, or lets LLM answer using its own knowledge.
    """
    settings = get_deployed_settings(chatbot_id)

    bot_name = settings.get("bot_name") or "AI Assistant"
    company_name = settings.get("company_name") or "the company"
    business_description = settings.get("business_description") or "No business description provided."
    tone = settings.get("tone") or "Friendly"
    additional_instructions = settings.get("additional_instructions") or ""
    fallback_message = generate_fallback(settings)

    # Conversation history
    conversation = ""
    for item in history:
        role = "User" if item["role"] == "user" else "Assistant"
        conversation += f"{role}: {item['content']}\n"

    # Structured context
    structured_context = ""
    for idx, chunk in enumerate(context_chunks, start=1):
        structured_context += f"Context {idx}:\n{chunk}\n\n"

    # Custom prompt if available
    prompt_template = settings.get("custom_prompt", "").strip()
    if prompt_template:
        return prompt_template.format(
            bot_name=bot_name,
            company_name=company_name,
            business_description=business_description,
            tone=tone,
            additional_instructions=additional_instructions,
            fallback_message=fallback_message,
            context=structured_context,
            conversation=conversation,
            message=message
        )

    # Default general prompt
    prompt = f"""
You are {bot_name}, an AI assistant for {company_name}.

Company / business information:
{business_description}

Tone:
Reply in a {tone.lower()} tone.

Additional company instructions:
{additional_instructions if additional_instructions else "None"}

Knowledge provided:
{structured_context if structured_context else "No relevant knowledge found, answer using your general knowledge in a helpful, practical, and friendly way."}

Recent conversation:
{conversation if conversation else "No recent conversation."}

User question:
{message}

Important rules:
1. Answer using the provided Knowledge first.
2. If the Knowledge contains the answer, answer directly.
3. Use relevant examples, scenarios, recommendations, prices, schedules, or policies from the Knowledge.
4. Do not invent company-specific facts not in the Knowledge.
5. If Knowledge is missing or unrelated, respond politely and clearly using your own knowledge.
6. Keep the reply short, clear, and useful.
7. Avoid mentioning internal words like "context", "chunks", "database", or "PDF".
8. If the user question is unclear or ambiguous, ask politely for clarification before providing an answer.
9. Use friendly and professional language, showing empathy when the user expresses problems or frustration.
10. Avoid repeating the same information from the conversation unless needed for clarity.
11. When applicable, reference the source of the knowledge (e.g., document, policy, FAQ) to increase user trust.
12. If the user asks for instructions or procedures, provide clear step-by-step guidance.
13. When possible, illustrate answers with practical examples or scenarios from the provided knowledge.
14. Ensure responses are concise, avoiding unnecessary filler words while still being informative.
15. Tailor explanations to the user’s level; avoid overly technical language if not required.
16. Maintain consistent terminology, spelling, and data across all responses.
17. When answering questions that can lead to actions (booking, contacting support, using a feature), provide clear actionable steps.

Fallback instruction:
If the Knowledge chunks do not contain information relevant to the user’s question, still answer fully using your own knowledge, examples, and advice.
Do not say 'I don’t know' or 'I have no information'.

Assistant:
"""
    return prompt


def get_bot_identity(chatbot_id):
    settings = get_deployed_settings(chatbot_id)
    return {
        "bot_name": settings.get("bot_name") or "AI Assistant",
        "company_name": settings.get("company_name") or "the company",
        "tone": settings.get("tone") or "Friendly",
    }
