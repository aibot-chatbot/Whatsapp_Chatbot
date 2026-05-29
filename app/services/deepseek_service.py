import logging
import os
from openai import OpenAI
from dotenv import load_dotenv

from app.services.chat_pipeline_service import prepare_chat_prompt

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


def generate_response(
    message,
    customer_id,
    chatbot_id,
    model="deepseek-v4-flash",
    temperature=0.7,
    source_channel="whatsapp",
):
    try:
        pipeline = prepare_chat_prompt(
            message=message,
            customer_id=customer_id,
            chatbot_id=chatbot_id,
            source_channel=source_channel,
        )

        if pipeline.get("direct_reply"):
            return pipeline["direct_reply"]

        prompt = pipeline.get("prompt")

        if not prompt:
            raise ValueError("Prompt could not be prepared for DeepSeek.")

        logging.info(f"[DeepSeek] Using model: {model}")

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant."
                },
                {
                    "role": "user",
                    "content": prompt
                },
            ],
            temperature=temperature,
            stream=False
        )

        reply = response.choices[0].message.content

        if reply:
            return reply.strip()

        return "Sorry, I’m not sure how to answer that right now."

    except Exception as e:
        logging.error(f"DeepSeek Error: {e}")
        return "I'm sorry, I encountered an error while processing your request with DeepSeek."
