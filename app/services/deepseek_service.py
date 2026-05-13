import logging
import os
from openai import OpenAI
from dotenv import load_dotenv
from app.services.chat_logic_service import detect_intent, handle_greeting, handle_out_of_scope, MAX_HISTORY
from app.services.rag_service import retrieve_relevant_chunks, build_prompt
from app.database.chat_history_repository import get_recent_chat_history
from app.database.conversation_repository import get_or_create_conversation

load_dotenv()

# DeepSeek Client
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def generate_response(message, wa_id, chatbot_id=1, model="deepseek-chat", temperature=0.7):
    try:
        conversation = get_or_create_conversation(
            chatbot_id=chatbot_id,
            customer_phone=wa_id,
            customer_name=None,
        )
        history = get_recent_chat_history(conversation["id"], limit=MAX_HISTORY)

        intent = detect_intent(message)
        logging.info(f"[DeepSeek] Detected intent: {intent}")

        if intent == "greeting" or intent == "main_menu":
            return handle_greeting(chatbot_id)

        if intent == "out_of_scope":
            return handle_out_of_scope(chatbot_id)

        # RAG: Retrieve context
        context_chunks = retrieve_relevant_chunks(message, chatbot_id=chatbot_id)
        
        # Build prompt using the same logic as Gemini for consistency
        prompt = build_prompt(history, message, context_chunks, chatbot_id=chatbot_id)

        # DeepSeek API Call
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            stream=False
        )

        reply = response.choices[0].message.content
        return reply

    except Exception as e:
        logging.error(f"DeepSeek Error: {e}")
        return "I'm sorry, I encountered an error while processing your request with DeepSeek."
