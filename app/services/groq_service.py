import os
import logging
from openai import OpenAI
from app.services.gemini_service import retrieve_relevant_chunks, build_rag_prompt

# Initialize Groq client (OpenAI compatible)
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY")
)

def generate_response(message, wa_id, chatbot_id=1, model="llama-3.1-70b-versatile", temperature=0.7):
    """
    Generates a response using Groq with RAG context.
    """
    try:
        logging.info(f"Generating Groq response for {wa_id} using model {model}")

        # 1. Retrieve context (RAG)
        context = retrieve_relevant_chunks(message, chatbot_id)
        
        # 2. Build prompt
        prompt = build_rag_prompt(message, context)

        # 3. Call Groq
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
        logging.error(f"Groq Service Error: {e}")
        return "I'm having trouble connecting to my brain (Groq) right now. Please try again later."
