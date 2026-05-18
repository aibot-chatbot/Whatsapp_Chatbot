import logging
import os
import re
from dotenv import load_dotenv
from google import genai

from app.services.settings_service import (
    get_settings,
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


def split_text_into_sections(text, max_chunk_length=900):
    text = normalize_text(text)

    if not text:
        return []

    if re.search(r"\b\d+\s+Q:", text, re.IGNORECASE):
        raw_sections = re.split(r"(?=\b\d+\s+Q:)", text)

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


def build_prompt(history, message, context_chunks, chatbot_id=1):
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


def get_bot_identity(chatbot_id=1):
    settings = get_deployed_settings(chatbot_id)
    return {
        "bot_name": settings.get("bot_name") or "AI Assistant",
        "company_name": settings.get("company_name") or "the company",
        "tone": settings.get("tone") or "Friendly",
    }