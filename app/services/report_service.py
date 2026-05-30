import os
import logging
from google import genai
from app.database.analytics_repository import get_transcript_logs


def generate_weekly_report(chatbot_id: int, days: int = 7) -> str:
    """
    Generate an AI insights report by analyzing recent conversation transcripts.
    """
    transcripts = get_transcript_logs(chatbot_id=chatbot_id, days=days)

    if not transcripts:
        return f"No conversation history found for the last {days} days to generate a report."

    # Format transcript data for context
    context_data = ""
    for idx, t in enumerate(transcripts):
        masked_phone = t["phone"]
        # Mask phone number slightly for user privacy in report context
        if len(masked_phone) > 4:
            masked_phone = masked_phone[:-4] + "****"
        context_data += f"\n--- Conversation #{idx+1} (User WAID/Phone: {masked_phone}) ---\n{t['chat']}\n"

    prompt = f"""
You are an expert AI Chatbot Analyst. Analyze the following user interaction logs from the last {days} days:

{context_data}

Provide a comprehensive, highly readable analytical report in Markdown format. Address the following:
1. **EXECUTIVE SUMMARY**: 2-3 sentence overview of overall user interaction and sentiment.
2. **TOP CUSTOMER THEMES**: List the most common topics, intents, or questions users asked about, along with representative sample questions.
3. **BOT ACCURACY & PROBLEMS**: Highlight instances where the bot got stuck, failed to answer, triggered fallback mechanisms, or generated lower-quality responses.
4. **RECOMMENDED KNOWLEDGE ADDITIONS**: List specific topics, policies, or questions that appear to be missing from the bot's current knowledge source.
5. **ACTIONABLE NEXT STEPS**: Suggest 3-5 concrete recommendations to improve the chatbot's performance.

Structure the report clearly with bold Markdown headers. Do not use raw HTML tags.
""".strip()

    try:
        # Load API key from environment and verify
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logging.error("GEMINI_API_KEY is not set in environment settings.")
            return "Failed to generate report: GEMINI_API_KEY environment variable is missing."

        client = genai.Client(api_key=api_key)

        logging.info(f"Generating analytics report for chatbot {chatbot_id} covering last {days} days.")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        if response.text:
            return response.text.strip()
        else:
            return "Failed to generate report: AI returned an empty response."

    except Exception as e:
        logging.error(f"Error in generate_weekly_report: {e}")
        return f"An error occurred while generating the report: {str(e)}"
