import os, sys
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.getcwd())

from app import create_app
from app.services.ai_router import _call_deepseek_direct
import logging
logging.basicConfig(level=logging.DEBUG)

app = create_app()
with app.app_context():
    try:
        print("Testing _call_deepseek_direct unconditionally")
        res = _call_deepseek_direct("hello", model="deepseek-chat", temperature=0.7)
        print("SUCCESS")
        print("REPLY:", res.text)
    except Exception as e:
        print(f"EXCEPTION TYPE: {type(e)}")
        print(f"EXCEPTION MESSAGE: {e}")
