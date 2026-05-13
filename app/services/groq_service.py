import os
import logging
from openai import OpenAI
from dotenv import load_dotenv
from app.services.chat_logic_service import detect_intent, handle_greeting, handle_out_of_scope, MAX_HISTORY
from app.services.rag_service import retrieve_relevant_chunks, build_prompt
from app.database.chat_history_repository import get_recent_chat_history
from app.database.conversation_repository import get_or_create_conversation

load_dotenv()

# Initialize Groq client
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY")
)


def generate_response(message, wa_id, chatbot_id=1, model="llama-3.3-70b-versatile", temperature=0.7):
    """
    Generates a response using Groq with the same chatbot flow as Gemini and DeepSeek.
    """
    try:
        logging.info(f"[Groq] Generating response for {wa_id} using model {model}")

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
        logging.info(f"[Groq] Detected intent: {intent}")

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

        logging.info(f"[Groq] Retrieved chunks: {len(context_chunks)}")

        # 6. Build full prompt with bot profile, tone, instructions, history, and knowledge
        prompt = build_prompt(
            history,
            message,
            context_chunks,
            chatbot_id=chatbot_id
        )

        # 7. Call Groq API
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

        if reply:
            return reply.strip()

        return "Sorry, I’m not sure how to answer that right now."

    except Exception as e:
        logging.error(f"Groq Service Error: {e}")
        return "I'm sorry, I encountered an error while processing your request with Groq."