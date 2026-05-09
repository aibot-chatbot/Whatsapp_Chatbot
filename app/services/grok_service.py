import os
import logging
from openai import OpenAI
from app.services.gemini_service import retrieve_relevant_chunks, build_rag_prompt

# Initialize xAI (Grok) client
client = OpenAI(
    base_url="https://api.x.ai/v1",
    api_key=os.getenv("XAI_API_KEY")
)

def generate_response(message, wa_id, chatbot_id=1, model="grok-beta", temperature=0.7):
    """
    Generates a response using xAI Grok with RAG context.
    """
    try:
        logging.info(f"Generating Grok (xAI) response for {wa_id} using model {model}")

        # 1. Retrieve context (RAG)
        context = retrieve_relevant_chunks(message, chatbot_id)
        
        # 2. Build prompt
        prompt = build_rag_prompt(message, context)

        # 3. Call xAI
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
        )

        return response.choices[0].message.content

    except Exception as e:
        logging.error(f"xAI Service Error: {e}")
        return "I'm having trouble connecting to my brain (xAI Grok) right now. Please try again later."
