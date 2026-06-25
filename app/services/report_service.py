import logging
from app.database.analytics_repository import get_transcript_logs
from app.services.ai_router import generate_system_response, OPERATION_AI_REPORT


def generate_weekly_report(chatbot_id: int, days: int = 7) -> str:
    """
    Generate an AI insights report by analyzing recent conversation transcripts.
    All AI calls go through ai_router.generate_system_response for billing enforcement.
    """
    from app.database.bot_repository import get_bot_by_id

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

    # Get bot model settings
    bot = get_bot_by_id(chatbot_id)
    provider = bot.get("ai_provider", "deepseek") if bot else "deepseek"
    model = bot.get("model_name") if bot else None

    # Use the system AI gateway — billing is enforced inside generate_system_response
    try:
        reply = generate_system_response(
            prompt=prompt,
            chatbot_id=chatbot_id,
            provider=provider,
            model=model,
            temperature=0.3,
            operation_type=OPERATION_AI_REPORT,
        )
        return f"{reply.strip()}\n\n---\n*Report generated using model: **{provider} / {model or 'default'}***"
    except Exception as e:
        logging.error(f"Error in generate_weekly_report: {e}")
        # Fallback: try Gemini directly
        logging.info("Attempting fallback to direct Gemini model 'gemini-2.5-flash'")
        try:
            reply = generate_system_response(
                prompt=prompt,
                chatbot_id=chatbot_id,
                provider="google",
                model="gemini-2.5-flash",
                temperature=0.3,
                operation_type=OPERATION_AI_REPORT,
            )
            return f"{reply.strip()}\n\n---\n*Report generated using fallback model: **google / gemini-2.5-flash** (original request to {provider}/{model or 'default'} failed)*"
        except Exception as fallback_err:
            logging.error(f"Fallback to Gemini failed: {fallback_err}")
            return f"An error occurred while generating the report: {str(e)}"
