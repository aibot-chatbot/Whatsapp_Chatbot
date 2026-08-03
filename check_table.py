import sys
import os
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.database.db import supabase

try:
    print(supabase.table("flows").insert({
        "company_id": 3, 
        "chatbot_id": 29, 
        "name": "Test Flow",
        "flow_data": {"test": "data"},
        "status": "active"
    }).execute())
except Exception as e:
    import traceback
    with open("error_log.txt", "w") as f:
        f.write(traceback.format_exc())
    print("Error written to error_log.txt")
