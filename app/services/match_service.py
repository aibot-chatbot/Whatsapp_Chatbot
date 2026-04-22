import json

from app.services.settings_service import get_settings
from app.services.profile_service import get_profile_by_name
from app.services import gemini_service
from google import genai


def check_pdf_config_match(profile_name=None):
    if profile_name:
        settings = get_profile_by_name(profile_name)

        if not settings:
            raise ValueError(f'Profile "{profile_name}" not found')
    else:
        settings = get_settings()

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

    pdf_preview = (gemini_service.PDF_TEXT or "")[:4000]
    active_pdf_path = gemini_service.PDF_PATH or ""

    prompt = f"""
You are checking whether a chatbot configuration matches the content of an uploaded PDF.

Bot Configuration:
{config_summary}

Profile Name:
{profile_name or "Current Settings"}

Active PDF Path:
{active_pdf_path}

PDF Content Preview:
{pdf_preview}

Task:
Decide whether the bot configuration is aligned with the PDF content.

Return ONLY valid JSON in this exact format:
{{
  "match": true,
  "reason": "short explanation"
}}

Rules:
- "match" must be true if the configuration generally fits the PDF topic and purpose.
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
        raw_text = response.text.strip()

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

    try:
        result = json.loads(raw_text)
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