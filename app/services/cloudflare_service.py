import os
import logging
import requests
from dotenv import load_dotenv
from app.services.chat_logic_service import detect_intent, handle_greeting, handle_out_of_scope, MAX_HISTORY
from app.services.rag_service import retrieve_relevant_chunks, build_prompt
from app.database.chat_history_repository import get_recent_chat_history
from app.database.conversation_repository import get_or_create_conversation

load_dotenv()


def generate_response(message, wa_id, chatbot_id=1, model="@cf/meta/llama-3.1-8b-instruct", temperature=0.7):
    """
    Generates a response using Cloudflare Workers AI with the same chatbot flow as Gemini and DeepSeek.
    """
    try:
        logging.info(f"[Cloudflare] Generating response for {wa_id} using model {model}")

        # 1. Get or create conversation
        conversation = get_or_create_conversation(
            chatbot_id=chatbot_id,
            customer_phone=wa_id,
            customer_name=None,
        )

        # 2. Get recent chat history
        history = get_recent_chat_history(
            conversation["id"],
            limit=MAX_HISTORY
        )

        # 3. Detect simple intent
        intent = detect_intent(message)
        logging.info(f"[Cloudflare] Detected intent: {intent}")

        # 4. If user says hi/menu, return greeting immediately
        if intent == "greeting" or intent == "main_menu":
            return handle_greeting(chatbot_id)

        if intent == "out_of_scope":
            return handle_out_of_scope(chatbot_id)

        # 5. Retrieve knowledge chunks from database
        context_chunks = retrieve_relevant_chunks(
            message,
            chatbot_id=chatbot_id
        )

        logging.info(f"[Cloudflare] Retrieved chunks: {len(context_chunks)}")

        # 6. Build full prompt with bot profile, tone, instructions, history, and knowledge
        prompt = build_prompt(
            history,
            message,
            context_chunks,
            chatbot_id=chatbot_id
        )

        # 7. Get Cloudflare credentials
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        api_token = os.getenv("CLOUDFLARE_API_TOKEN")

        if not account_id or not api_token:
            raise ValueError("Cloudflare Account ID or API Token missing in .env")

        # 8. Call Cloudflare Workers AI
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }

        response = requests.post(url, headers=headers, json=payload)
        result = response.json()

        if result.get("success"):
            reply = result.get("result", {}).get("response", "")

            if reply:
                return reply.strip()

            return "Sorry, I’m not sure how to answer that right now."

        logging.error(f"Cloudflare AI Error: {result.get('errors')}")
        return "I'm sorry, I encountered an error while processing your request with Cloudflare."

    except Exception as e:
        logging.error(f"Cloudflare Service Error: {e}")
        return "I'm sorry, I encountered an error while processing your request with Cloudflare."