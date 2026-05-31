import json
import fitz  # PyMuPDF

from app.services.settings_service import get_draft_runtime
from app.services.profile_service import get_profile_by_name
from app.services.knowledge_service import get_active_pdf
from app.database.knowledge_file_repository import get_active_knowledge_file
from app.database.knowledge_chunk_repository import get_chunks_by_file
from google import genai


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


def check_pdf_config_match(chatbot_id, profile_name=None):
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
    active_file = get_active_knowledge_file(chatbot_id)
    if active_file:
        chunks = get_chunks_by_file(active_file.get("id"))
        if chunks:
            pdf_preview = "\n\n".join([c.get("content", "") for c in chunks])[:4000]

    # Fallback to local PDF reading if database chunks were not found
    if not pdf_preview:
        pdf_preview = extract_pdf_preview(active_pdf_path)

    if not pdf_preview:
        return {
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

    client = genai.Client()

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        if response.text:
            raw_text = response.text.strip()
        else:
            raw_text = ""
            print("Warning: The model returned no text.")

    except Exception as e:
        error_text = str(e)

        if "503" in error_text or "Service Unavailable" in error_text or "high demand" in error_text:
            return {
                "match": False,
                "reason": "Match check is temporarily unavailable because the AI service is busy. Please try again in a moment.",
                "profile_name": profile_name or "Current Settings",
                "pdf_path": active_pdf_path
            }

        return {
            "match": False,
            "reason": f"Match check failed: {error_text}",
            "profile_name": profile_name or "Current Settings",
            "pdf_path": active_pdf_path
        }

    # Clean up markdown code block fences if present
    cleaned_text = raw_text.strip()
    if cleaned_text.startswith("```"):
        lines = cleaned_text.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned_text = "\n".join(lines).strip()

    try:
        result = json.loads(cleaned_text)
        return {
            "match": bool(result.get("match", False)),
            "reason": result.get("reason", "No reason provided."),
            "profile_name": profile_name or "Current Settings",
            "pdf_path": active_pdf_path
        }
    except Exception:
        return {
            "match": False,
            "reason": f"Could not parse AI result. Raw response: {raw_text}",
            "profile_name": profile_name or "Current Settings",
            "pdf_path": active_pdf_path
        }
