from app.database.db import supabase


# Which senders are OUR side of the conversation, as an allowlist. The
# direction matters: the previous test was `== "bot"` else "user", so every
# sender type that is not the bot became the customer. 060 adds staff
# authorship (messages.actor_user_id, and sender_type='human' with it), and
# under the old test a staff reply was replayed to the model as if the
# customer had typed it -- so after a resume-to-AI the model reads its own
# operator's "Sure, I'll refund you" as a customer demand.
ASSISTANT_SENDER_TYPES = frozenset({"bot", "human"})


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
        role = "assistant" if sender_type in ASSISTANT_SENDER_TYPES else "user"

        formatted.append({
            "role": role,
            "content": row.get("message_text", ""),
            "timestamp": row.get("created_at", "")
        })

    return formatted