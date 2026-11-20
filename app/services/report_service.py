import logging
from app.database.analytics_repository import get_transcript_logs
from app.services.ai_router import generate_system_response, OPERATION_AI_REPORT, is_error_reply
from app.services.openrouter_service import ModerationBlocked
from app.services import content_filter
from app.services.client_job_limits import ClientJobLimitError, report_job



from app.database.bot_repository import get_bot_by_id


class ReportGenerationError(RuntimeError):
    pass


def _safe_chat(chat, chatbot_id):
    """Filter 1 (plan A3) for the report: flagged lines never reach the AI, IC and card numbers are hidden.

    Returns None when a flagged phrase spans a message's own line breaks, so the whole
    conversation is left out rather than sent in pieces.
    """
    kept = "\n".join(line for line in chat.split("\n") if content_filter.check_bot_text(line, chatbot_id) is None)
    if content_filter.check_bot_text(kept, chatbot_id) is not None:
        return None
    return content_filter.hide_sensitive_numbers(kept)

def generate_weekly_report(chatbot_id: int, days: int = 7) -> str:
    """
    Generate an AI insights report by analyzing recent conversation transcripts.
    All AI calls go through ai_router.generate_system_response for billing enforcement.
    """

    transcripts = get_transcript_logs(chatbot_id=chatbot_id, days=days)

    if not transcripts:
        return f"No conversation history found for the last {days} days to generate a report."

    # Format transcript data for context
    context_data = ""
    for idx, t in enumerate(transcripts):
        chat = _safe_chat(t.get("chat") or "", chatbot_id)
        if chat is None:
            continue
        masked_phone = t.get("phone") or "Anonymous visitor"
        # Mask phone number slightly for user privacy in report context
        if len(masked_phone) > 4:
            masked_phone = masked_phone[:-4] + "****"
        context_data += f"\n--- Conversation #{idx+1} (User WAID/Phone: {masked_phone}) ---\n{chat}\n"

    if not context_data:
        return f"No conversation from the last {days} days could be analysed: the safety check left them all out."

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

    # Use the system AI gateway - billing is enforced inside generate_system_response
    # No hardcoded provider fallback: provider isolation and model-tier enforcement
    # are handled centrally.  If the request fails, return a safe error message.
    try:
        with report_job((bot or {}).get("company_id")):
            reply = generate_system_response(
                prompt=prompt,
                chatbot_id=chatbot_id,
                provider=provider,
                model=model,
                temperature=0.3,
                operation_type=OPERATION_AI_REPORT,
            )
        if not isinstance(reply, str) or is_error_reply(reply):
            raise ReportGenerationError("Report generation failed.")
        return f"{reply.strip()}\n\n---\n*Report generated using model: **{provider} / {model or 'default'}***"
    except ModerationBlocked:
        # A flagged message stays in this window, so each retry would be one more block.
        raise ValueError("The AI provider's safety filter refused part of these conversations. "
                         "Trying again will not help.") from None
    except ClientJobLimitError:
        raise
    except Exception as e:
        logging.error("Weekly report generation failed (%s)", type(e).__name__)
        raise ReportGenerationError("Report generation failed. Please try again later.") from None
