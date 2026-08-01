from app.database.db import supabase

# Let's see what bots exist and their active knowledge files
bots = supabase.table("bots").select("id, bot_name").execute()
for bot in bots.data:
    print(f"Bot: {bot['bot_name']} (ID: {bot['id']})")
    files = supabase.table("knowledge_files").select("id, file_name, file_type, is_active").eq("chatbot_id", bot['id']).execute()
    for f in files.data:
        active_str = "[ACTIVE]" if f.get('is_active') else ""
        print(f"  - {f['file_name']} (type: {f['file_type']}) {active_str}")

