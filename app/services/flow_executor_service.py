import logging
from app.database.db import supabase

def process_flow_message(chatbot_id: int, user_message: str, customer_id: str):
    """
    Stateful Flow Executor.
    Checks if the conversation is already in a flow (Memory),
    otherwise checks for trigger keywords to start a new flow.
    """
    try:
        # We store the conversation state in crm_leads or conversations.
        # Since this is a lightweight state machine for now, we'll use a new table or the existing crm_leads for state.
        # Wait, the migration added active_flow_id to conversations!
        # Let's find the conversation for this customer_id (which could be a phone number or session ID)
        conv_res = supabase.table("conversations").select("id, active_flow_id, current_node_id").eq("chatbot_id", chatbot_id).eq("customer_phone", customer_id).execute()
        
        # If not found by phone, try platform_user_id (for Telegram/Testbot)
        if not conv_res.data:
             conv_res = supabase.table("conversations").select("id, active_flow_id, current_node_id").eq("chatbot_id", chatbot_id).eq("platform_user_id", customer_id).execute()

        active_flow_id = None
        current_node_id = None
        real_conv_id = None
        
        if conv_res.data and len(conv_res.data) > 0:
            real_conv_id = conv_res.data[0].get("id")
            active_flow_id = conv_res.data[0].get("active_flow_id")
            current_node_id = conv_res.data[0].get("current_node_id")
            
        if active_flow_id and current_node_id and real_conv_id:
            # We are currently in a flow, process the user_message as input for current_node
            # TODO: implement node input processing (e.g. wait_for_input)
            pass
            
        # 2. If not in a flow, check if user message matches a trigger keyword
        response = supabase.table("flows").select("*").eq("chatbot_id", chatbot_id).eq("status", "active").execute()
        if not response.data or len(response.data) == 0:
            return None
            
        flow_record = response.data[0]
        flow_data = flow_record.get("flow_data")
        if not flow_data:
            return None
            
        home_data = flow_data.get("drawflow", {}).get("Home", {}).get("data", {})
        
        # Find the trigger node
        trigger_node = None
        for node_id, node_info in home_data.items():
            if node_info.get("name") == "trigger":
                trigger_node = node_info
                break
                
        if not trigger_node:
            return None
            
        keyword = trigger_node.get("data", {}).get("keyword", "").strip().lower()
        
        # Check if keyword matches user message
        if not keyword or user_message.strip().lower() != keyword:
            return None
            
        # If matched, we start the flow! 
        # Update conversation state
        if real_conv_id:
            supabase.table("conversations").update({
                "active_flow_id": flow_record["id"]
            }).eq("id", real_conv_id).execute()
        
        # Follow the output connection to find the next node
        outputs = trigger_node.get("outputs", {}).get("output_1", {}).get("connections", [])
        if not outputs:
            return None
            
        next_node_id = str(outputs[0].get("node"))
        return _execute_node(chatbot_id, real_conv_id, home_data, next_node_id)
        
    except Exception as e:
        logging.error(f"Error executing flow for bot {chatbot_id}: {e}")
        return None

def _execute_node(chatbot_id: int, real_conv_id: str, home_data: dict, node_id: str):
    """
    Recursively executes nodes until it hits a stopping point (e.g. wait for input, or end of flow).
    Returns the accumulated text to send back to the user.
    """
    node = home_data.get(node_id)
    if not node:
        # End of flow, clear state
        if real_conv_id:
            supabase.table("conversations").update({"active_flow_id": None, "current_node_id": None}).eq("id", real_conv_id).execute()
        return None
        
    node_name = node.get("name")
    
    if node_name == "send_message":
        reply_text = node.get("data", {}).get("text", "")
        
        # Check for next node
        outputs = node.get("outputs", {}).get("output_1", {}).get("connections", [])
        if outputs:
            next_node_id = str(outputs[0].get("node"))
            next_reply = _execute_node(chatbot_id, real_conv_id, home_data, next_node_id)
            if next_reply:
                return reply_text + "\n\n" + next_reply
                
        # If no next node, flow is done
        if real_conv_id:
            supabase.table("conversations").update({"active_flow_id": None, "current_node_id": None}).eq("id", real_conv_id).execute()
        return reply_text
        
    if node_name == "interactive_buttons":
        btn_data = node.get("data", {})
        menu_text = btn_data.get("body_text", "Options:")
        b1 = btn_data.get("btn_1", "")
        b2 = btn_data.get("btn_2", "")
        b3 = btn_data.get("btn_3", "")
        
        buttons = []
        if b1: buttons.append(f"1️⃣ {b1}")
        if b2: buttons.append(f"2️⃣ {b2}")
        if b3: buttons.append(f"3️⃣ {b3}")
        
        reply_text = menu_text
        if buttons:
            reply_text += "\n" + "\n".join(buttons)
            
        # Stop here and wait for input. We set current_node_id to this node.
        # So when they reply, we can evaluate their choice.
        if real_conv_id:
            supabase.table("conversations").update({"current_node_id": node_id}).eq("id", real_conv_id).execute()
        return reply_text
        
    # More advanced node handlers (Tag, Condition, Escalate) will go here...
    
    return None
