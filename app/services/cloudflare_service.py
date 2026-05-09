import os
import logging
import requests
from app.services.gemini_service import retrieve_relevant_chunks, build_rag_prompt

def generate_response(message, wa_id, chatbot_id=1, model="@cf/meta/llama-3.1-8b-instruct", temperature=0.7):
    """
    Generates a response using Cloudflare Workers AI with RAG context.
    """
    try:
        logging.info(f"Generating Cloudflare AI response for {wa_id} using model {model}")

        # 1. Retrieve context (RAG)
        context = retrieve_relevant_chunks(message, chatbot_id)
        
        # 2. Build prompt
        prompt = build_rag_prompt(message, context)

        # 3. Call Cloudflare
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        api_token = os.getenv("CLOUDFLARE_API_TOKEN")
        
        if not account_id or not api_token:
            raise ValueError("Cloudflare Account ID or API Token missing in .env")

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        headers = {"Authorization": f"Bearer {api_token}"}
        
        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post(url, headers=headers, json=payload)
        result = response.json()

        if result.get("success"):
            return result["result"]["response"]
        else:
            logging.error(f"Cloudflare AI Error: {result.get('errors')}")
            return "I'm having trouble connecting to my brain (Cloudflare AI) right now."

    except Exception as e:
        logging.error(f"Cloudflare Service Error: {e}")
        return "I'm having trouble connecting to my brain (Cloudflare) right now. Please try again later."
