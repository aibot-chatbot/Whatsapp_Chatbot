import os
from dotenv import load_dotenv
load_dotenv()

from app.database.conversation_repository import get_or_create_conversation
from app.database.agent_action_repository import save_agent_action
from app.database.db import supabase

def create_test_escalation():
    # 1. We know from testing the API that deeying888@gmail.com owns bot 20
    bots_res = supabase.table("chatbots").select("id, company_id").eq("id", 20).execute()
    if not bots_res.data:
        print("Bot 20 not found.")
        return

    bot = bots_res.data[0]
    chatbot_id = bot["id"]
    company_id = bot["company_id"]
    
    print(f"Using Chatbot ID: {chatbot_id}")

    # 2. Create a dummy conversation
    conversation = get_or_create_conversation(
        chatbot_id=chatbot_id,
        customer_phone="+1234567890",
        customer_name="Test User (Proof)",
        source_channel="whatsapp"
    )
    print(f"Created/Found Conversation ID: {conversation['id']}")

    # 3. Create an agent action (escalation)
    action = save_agent_action(
        chatbot_id=chatbot_id,
        company_id=company_id,
        conversation_id=conversation['id'],
        intent="handoff_request",
        action_type="escalate",
        confidence=0.99,
        reason="User said: 'I want to speak to a human immediately!'"
    )
    print(f"Created Pending Escalation Action ID: {action['id']}")

    print("\n--- PROOF ---")
    print("Test escalation successfully injected into the database!")
    print("If you go to your Inbox page now, you will see 'Test User (Proof)' waiting for you.")

if __name__ == "__main__":
    create_test_escalation()
