import logging
from app.database.db import supabase

def save_flow(company_id: int, chatbot_id: int, name: str, flow_data: dict, action: str = "draft"):
    """
    Saves a draft or publishes a flow.
    """
    try:
        existing = supabase.table("flows").select("id").eq("company_id", company_id).eq("chatbot_id", chatbot_id).execute()
        
        update_payload = {
            "name": name,
            "status": "active"
        }
        
        if action == "publish":
            update_payload["published_data"] = flow_data
            update_payload["draft_data"] = flow_data
            update_payload["published_at"] = "now()"
        else:
            update_payload["draft_data"] = flow_data
            
        if existing.data and len(existing.data) > 0:
            flow_id = existing.data[0]["id"]
            response = supabase.table("flows").update(update_payload).eq("id", flow_id).execute()
            return response.data[0] if response.data else None
        else:
            insert_payload = {
                "company_id": company_id,
                "chatbot_id": chatbot_id,
                "name": name,
                "status": "active",
                "draft_data": flow_data
            }
            if action == "publish":
                insert_payload["published_data"] = flow_data
                insert_payload["published_at"] = "now()"
                
            response = supabase.table("flows").insert(insert_payload).execute()
            return response.data[0] if response.data else None
    except Exception as e:
        import traceback
        with open("error_log.txt", "w") as f:
            f.write(traceback.format_exc())
        logging.error(f"Error saving flow for bot {chatbot_id}: {e}")
        raise e

def get_active_flow(company_id: int, chatbot_id: int):
    """
    Retrieves the active flow for a given chatbot.
    """
    try:
        response = supabase.table("flows").select("*").eq("company_id", company_id).eq("chatbot_id", chatbot_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        logging.error(f"Error retrieving flow for bot {chatbot_id}: {e}")
        raise e
