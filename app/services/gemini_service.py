import logging
import os
from dotenv import load_dotenv
from google import genai
from app.services.chat_logic_service import detect_intent, handle_greeting, handle_out_of_scope, MAX_HISTORY
from app.services.rag_service import retrieve_relevant_chunks, build_prompt
from app.database.chat_history_repository import get_recent_chat_history
from app.database.conversation_repository import get_or_create_conversation


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

load_dotenv()

# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# model = genai.GenerativeModel("gemini-3-flash-preview")

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
DEFAULT_MODEL = "gemini-2.5-flash"


def generate_response(message, wa_id, chatbot_id=1, model=DEFAULT_MODEL, temperature=0.7):

    try:
        conversation = get_or_create_conversation(
            chatbot_id=chatbot_id,
            customer_phone=wa_id,
            customer_name=None,
        )
        history = get_recent_chat_history(conversation["id"], limit=MAX_HISTORY)

        intent = detect_intent(message)
        logging.info(f"Detected intent: {intent}")

        if intent == "main_menu":
            reply = handle_greeting(chatbot_id)

        elif intent == "greeting":
            reply = handle_greeting(chatbot_id)

        elif intent == "out_of_scope":
            reply = handle_out_of_scope(chatbot_id)

        else:

            context_chunks = retrieve_relevant_chunks(message, chatbot_id=chatbot_id)

            logging.info(f"Retrieved chunks: {len(context_chunks)}")

            logging.info(f"User message: {message}")

            prompt = build_prompt(history, message, context_chunks, chatbot_id)

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": temperature
                }
            )

            reply = response.text.strip() if response.text else "Sorry, I’m not sure how to answer that right now."

        return reply

    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return "Sorry, I’m having trouble replying right now."
