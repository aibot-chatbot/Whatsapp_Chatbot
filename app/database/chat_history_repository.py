from app.database.db import supabase


def get_recent_chat_history(conversation_id, limit=6):
    response = (
        supabase
        .table("messages")
        .select("sender_type,message_text,created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    rows = response.data or []
    rows = list(reversed(rows))

    formatted = []
    for row in rows:
        sender_type = row.get("sender_type", "")
        role = "assistant" if sender_type == "bot" else "user"

        formatted.append({
            "role": role,
            "content": row.get("message_text", ""),
            "timestamp": row.get("created_at", "")
        })

    return formatted