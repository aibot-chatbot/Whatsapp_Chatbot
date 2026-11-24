from app.database.db import supabase
from app.database import agent_action_repository


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
        .select("id,sender_type,message_text,created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .limit(limit)
        .execute()
    )

    rows = response.data or []
    rows = list(reversed(rows))
    blocked_ids = agent_action_repository.get_blocked_content_message_ids(conversation_id)

    formatted = []
    for row in rows:
        if str(row.get("id")) in blocked_ids:
            continue
        sender_type = row.get("sender_type", "")
        role = "assistant" if sender_type in ASSISTANT_SENDER_TYPES else "user"

        formatted.append({
            "role": role,
            "content": row.get("message_text", ""),
            "timestamp": row.get("created_at", "")
        })

    return formatted


def get_summary_candidates(conversation_id, chatbot_id, through_id, *, keep_recent, limit):
    """Read bounded projections in one snapshot, scoped through their parent conversation."""
    query = (
        supabase.table("conversations")
        .select("recent:messages(id),oldest:messages(id,sender_type,content:message_text),by_id:messages(id)")
        .eq("id", conversation_id)
        .eq("chatbot_id", chatbot_id)
        .order("created_at", desc=True, foreign_table="recent")
        .order("id", desc=True, foreign_table="recent")
        .limit(keep_recent, foreign_table="recent")
        .order("created_at", foreign_table="oldest")
        .order("id", foreign_table="oldest")
        .limit(limit, foreign_table="oldest")
        .order("id", foreign_table="by_id")
        .limit(limit, foreign_table="by_id")
    )
    if through_id is not None:
        query = query.gt("oldest.id", through_id).gt("by_id.id", through_id)
    pages = query.execute().data
    if not pages:
        return []

    page = pages[0]
    recent = {row["id"] for row in page["recent"]}
    older = [row for row in page["oldest"] if row["id"] not in recent]
    # Late webhooks can put a larger id earlier in time. The time-ordered prefix must
    # end at its largest id and match the same-length id prefix, or the cursor loses rows.
    safe_count = 0
    largest = 0
    for count, (row, by_id) in enumerate(zip(older, page["by_id"]), start=1):
        largest = max(largest, row["id"])
        if row["id"] == largest == by_id["id"]:
            safe_count = count
    batch = older[:safe_count]
    if batch:
        blocked = agent_action_repository.query_blocked_content_message_ids(
            conversation_id, chatbot_id=chatbot_id, message_ids=[row["id"] for row in batch],
        )
        for row in batch:
            if str(row["id"]) in blocked:
                row.pop("content")
                row["blocked"] = True
    return batch
