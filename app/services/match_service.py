import json
import fitz  # PyMuPDF
import logging
import os
import requests

from app.services.settings_service import get_draft_runtime
from app.services.profile_service import get_profile_by_name
from app.services.knowledge_service import get_active_pdf
from app.services.model_catalog import (
    OPENROUTER_PROVIDER_KEYS,
    get_default_model,
    normalize_model_selection,
)
from app.database.bot_repository import get_bot_by_id
from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
from app.database.knowledge_chunk_repository import get_chunks_by_file


def extract_pdf_preview(pdf_path, max_chars=4000):
    if not pdf_path:
        return ""

    try:
        doc = fitz.open(pdf_path)
        text_parts = []

        for page in doc:
            text_parts.append(page.get_text())

        return "\n".join(text_parts)[:max_chars]
    except Exception:
        return ""


def _validation_unavailable(profile_name, active_pdf_path, reason=None):
    return {
        "validation_status": "unavailable",
        "match": None,
        "reason": reason or "Validation is temporarily unavailable. Please try again later.",
        "profile_name": profile_name or "Current Settings",
        "pdf_path": active_pdf_path,
    }


def _call_openrouter_validation(prompt, provider, model, temperature):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is missing.")

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-OpenRouter-Title": "AI Chatbot System",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You validate chatbot profile and knowledge alignment. Return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": temperature,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_deepseek_validation(prompt, model, temperature):
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is missing.")

    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You validate chatbot profile and knowledge alignment. Return only valid JSON.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=temperature,
        stream=False,
    )

    reply = response.choices[0].message.content
    if not reply:
        raise RuntimeError("Selected provider returned an empty validation response.")

    return reply.strip()


def _call_selected_validation_provider(prompt, chatbot_id, company_id=None):
    bot = get_bot_by_id(chatbot_id, company_id)
    provider = bot.get("ai_provider") if bot else None
    model = bot.get("model_name") if bot else None
    temperature = bot.get("temperature") if bot else None
    if temperature is None:
        temperature = 0.3

    provider, model = normalize_model_selection(provider, model)

    if provider == "default":
        provider = "deepseek"
        model = get_default_model(provider)

    provider_candidates = [provider]
    for fallback_provider in ["deepseek", "google", "openai"]:
        if fallback_provider not in provider_candidates:
            provider_candidates.append(fallback_provider)

    errors = []
    for candidate_provider in provider_candidates:
        candidate_provider, candidate_model = normalize_model_selection(
            candidate_provider,
            model if candidate_provider == provider else None,
        )

        try:
            logging.info(
                "Running match validation using provider=%s model=%s",
                candidate_provider,
                candidate_model,
            )

            if candidate_provider == "deepseek":
                return _call_deepseek_validation(
                    prompt,
                    candidate_model,
                    temperature,
                )

            if candidate_provider in OPENROUTER_PROVIDER_KEYS:
                return _call_openrouter_validation(
                    prompt,
                    candidate_provider,
                    candidate_model,
                    temperature,
                )

            errors.append(f"Unsupported validation provider: {candidate_provider}")

        except Exception as e:
            logging.warning(
                "Match validation provider failed: provider=%s model=%s error=%s",
                candidate_provider,
                candidate_model,
                e,
            )
            errors.append(f"{candidate_provider}: {e}")

    raise RuntimeError("; ".join(errors) or "No validation provider succeeded.")


def check_pdf_config_match(chatbot_id, profile_name=None, company_id=None):
    draft_runtime = get_draft_runtime(chatbot_id)

    if profile_name:
        settings = get_profile_by_name(profile_name, chatbot_id)

        if not settings:
            raise ValueError(f'Profile "{profile_name}" not found')
    else:
        draft_profile_name = draft_runtime.get("draft_profile_name", "")

        if not draft_profile_name:
            raise ValueError("Please select an active profile before checking match.")

        settings = get_profile_by_name(draft_profile_name, chatbot_id)

        if not settings:
            raise ValueError("Selected profile was not found for this bot.")

        profile_name = draft_profile_name

    bot_name = settings.get("bot_name", "")
    company_name = settings.get("company_name", "")
    business_description = settings.get("business_description", "")
    tone = settings.get("tone", "")
    additional_instructions = settings.get("additional_instructions", "")

    config_summary = f"""
Bot Name: {bot_name}
Company Name: {company_name}
Business Description: {business_description}
Tone: {tone}
Custom Instructions: {additional_instructions}
""".strip()

    active_pdf_path = draft_runtime.get("draft_pdf_path", "")

    if not active_pdf_path:
        active_pdf = get_active_pdf(chatbot_id)
        active_pdf_path = active_pdf.get("file_path", "")

    # Query active knowledge file from DB and compile text preview from its chunks
    pdf_preview = ""
    active_file = get_active_pdf_knowledge_file(chatbot_id)
    if active_file:
        chunks = get_chunks_by_file(active_file.get("id"))
        if chunks:
            pdf_preview = "\n\n".join([c.get("content", "") for c in chunks])[:4000]

    # Fallback to local PDF reading if database chunks were not found
    if not pdf_preview:
        pdf_preview = extract_pdf_preview(active_pdf_path)

    if not pdf_preview:
        return {
            "validation_status": "completed",
            "match": False,
            "reason": "Knowledge base content is missing, cannot determine alignment.",
            "profile_name": profile_name or "Current Settings",
            "pdf_path": active_pdf_path
        }

    prompt = f"""
You are checking whether a chatbot configuration matches the content of an uploaded knowledge source (PDF or Scraped Website).

Bot Configuration:
{config_summary}

Profile Name:
{profile_name or "Current Settings"}

Active Knowledge Path/URL:
{active_pdf_path}

Knowledge Content Preview:
{pdf_preview}

Task:
Decide whether the bot configuration is aligned with the knowledge content.

Return ONLY valid JSON in this exact format:
{{
  "match": true,
  "reason": "short explanation"
}}

Rules:
- "match" must be true if the configuration generally fits the knowledge topic and purpose.
- "match" must be false if the configuration clearly describes a different business/domain/topic.
- Keep "reason" short and clear.
- Do not return markdown.
"""

    try:
        raw_text = _call_selected_validation_provider(
            prompt,
            chatbot_id=chatbot_id,
            company_id=company_id,
        )

    except Exception as e:
        logging.error("Match validation failed for chatbot_id=%s: %s", chatbot_id, e)
        return _validation_unavailable(profile_name, active_pdf_path)

    # Clean up markdown code block fences if present
    cleaned_text = raw_text.strip()
    if cleaned_text.startswith("```"):
        lines = cleaned_text.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned_text = "\n".join(lines).strip()

    try:
        result = json.loads(cleaned_text)
        return {
            "validation_status": "completed",
            "match": bool(result.get("match", False)),
            "reason": result.get("reason", "No reason provided."),
            "profile_name": profile_name or "Current Settings",
            "pdf_path": active_pdf_path
        }
    except Exception as e:
        logging.error("Could not parse match validation response for chatbot_id=%s: %s", chatbot_id, e)
        return _validation_unavailable(profile_name, active_pdf_path)
