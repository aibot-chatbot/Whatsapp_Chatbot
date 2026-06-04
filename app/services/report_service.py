import os
import logging
from google import genai
from app.database.analytics_repository import get_transcript_logs


def generate_weekly_report(chatbot_id: int, days: int = 7) -> str:
    """
    Generate an AI insights report by analyzing recent conversation transcripts.
    """
    from app.database.bot_repository import get_bot_by_id
    from app.services.model_catalog import normalize_model_selection, OPENROUTER_PROVIDER_KEYS

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
    provider = "deepseek"
    model = None

    if bot:
        provider = bot.get("ai_provider", "deepseek")
        model = bot.get("model_name")

    provider, model = normalize_model_selection(provider, model)
    logging.info(f"Generating analytics report using provider: {provider}, model: {model}")

    try:
        # 1. Route via OpenRouter
        if provider in OPENROUTER_PROVIDER_KEYS:
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                logging.error("OPENROUTER_API_KEY is not set in environment settings.")
                return "Failed to generate report: OPENROUTER_API_KEY environment variable is missing."

            import requests
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-OpenRouter-Title": "AI Chatbot System",
            }
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert AI Chatbot Analyst."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            }
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=90
            )
            response.raise_for_status()
            data = response.json()
            reply = data["choices"][0]["message"]["content"].strip()
            return f"{reply}\n\n---\n*Report generated using model: **{provider} / {model}***"

        # 2. Route via DeepSeek
        elif provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                logging.error("DEEPSEEK_API_KEY is not set in environment settings.")
                return "Failed to generate report: DEEPSEEK_API_KEY environment variable is missing."

            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )
            response = client.chat.completions.create(
                model=model if model else "deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an expert AI Chatbot Analyst."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                stream=False
            )
            reply = response.choices[0].message.content
            if reply:
                return f"{reply.strip()}\n\n---\n*Report generated using model: **{provider} / {model}***"
            return "Failed to generate report: DeepSeek returned an empty response."

        else:
            return f"Failed to generate report: Unsupported provider '{provider}'."

    except Exception as e:
        logging.error(f"Error in generate_weekly_report: {e}")
        # Fallback to direct Gemini
        logging.info("Attempting fallback to direct Gemini model 'gemini-2.5-flash'")
        try:
            fallback_api_key = os.getenv("GEMINI_API_KEY")
            if not fallback_api_key:
                return f"An error occurred: {str(e)} (Gemini fallback key also missing)"

            from google import genai
            fallback_client = genai.Client(api_key=fallback_api_key)
            response = fallback_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            if response.text:
                return f"{response.text.strip()}\n\n---\n*Report generated using fallback model: **google / gemini-2.5-flash** (original request to {provider}/{model} failed)*"
            return f"An error occurred: {str(e)} (Gemini fallback returned empty response)"
        except Exception as fallback_err:
            logging.error(f"Fallback to direct Gemini failed: {fallback_err}")
            return f"An error occurred while generating the report: {str(e)}"

