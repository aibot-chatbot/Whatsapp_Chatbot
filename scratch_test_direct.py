import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.getcwd())

from flask import request
from app import create_app
from app.routes.guide_router import guide_chat

app = create_app()

# We need to strip the @token_required decorator, but we can't easily do that.
# Let's just run the code directly.
from app.database.db import supabase
from app.routes.guide_router import PROJECT_MAP
bot_id = 52
user_message = "hi"

instructions = PROJECT_MAP.format(bot_id=bot_id)
combined_prompt = f"{instructions}\n\nUser Question: {user_message}"

try:
    from app.services.ai_router import _call_deepseek_direct
    result = _call_deepseek_direct(
        prompt=combined_prompt,
        model="deepseek-chat",
        temperature=0.7,
        json_response=False
    )
    ai_reply = result.text
    print("SUCCESS")
except Exception as primary_e:
    print(f"FAILED: {type(primary_e)}: {primary_e}")
