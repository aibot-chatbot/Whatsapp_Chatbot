import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
logging.info(f"OpenRouter key loaded: {bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY.strip())}")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def generate_response(
    prompt,
    model="google/gemini-3.5-flash",
    temperature=0.7,
    max_tokens=1500,
):
    try:
        if not OPENROUTER_API_KEY:
            logging.error("OPENROUTER_API_KEY is missing.")
            return "Sorry, I’m having trouble replying right now."

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-OpenRouter-Title": "AI Chatbot System",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        logging.info(f"[OpenRouter] Using model: {model}")
        logging.info(f"[OpenRouter] API key loaded: {bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY.strip())}")

        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )

        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        reply = choice["message"]["content"].strip()
        finish_reason = choice.get("finish_reason")

        logging.info(f"[OpenRouter] Finish reason: {finish_reason}")
        logging.info(f"[OpenRouter] Reply length: {len(reply)}")
        logging.info(f"[OpenRouter] Reply preview: {reply[:500]}")
        logging.info("[OpenRouter] Response received successfully.")

        return reply

    except requests.exceptions.HTTPError as e:
        logging.error(f"OpenRouter HTTP error: {e}")
        logging.error(f"OpenRouter response: {response.text if 'response' in locals() else ''}")
        return "Sorry, I’m having trouble replying right now."

    except Exception as e:
        logging.error(f"OpenRouter error: {e}")
        return "Sorry, I’m having trouble replying right now."