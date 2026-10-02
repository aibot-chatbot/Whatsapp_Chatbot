from datetime import datetime, timedelta
from app.database.db import supabase


def get_total_users(chatbot_id):
    response = (
        supabase
        .table("conversations")
        .select("customer_phone")
        .eq("chatbot_id", chatbot_id)
        .execute()
    )

    rows = response.data or []
    unique_phones = set()

    for row in rows:
        phone = row.get("customer_phone")
        if phone:
            unique_phones.add(phone)

    return len(unique_phones)


def get_total_user_messages(chatbot_id):
    response = (
        supabase
        .table("messages")
        .select("id,conversations!inner(chatbot_id)", count="exact")
        .eq("sender_type", "customer")
        .eq("conversations.chatbot_id", chatbot_id)
        .execute()
    )
    return response.count or 0


def get_recent_history(chatbot_id, limit=4):
    convo_res = (
        supabase
        .table("conversations")
        .select("id,customer_phone,updated_at,source_channel")
        .eq("chatbot_id", chatbot_id)
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )

    conversations = convo_res.data or []
    results = []

    for convo in conversations:
        msg_res = (
            supabase
            .table("messages")
            .select("message_text,created_at")
            .eq("conversation_id", convo["id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        msg_rows = msg_res.data or []
        last_msg = msg_rows[0] if msg_rows else {}

        phone = convo.get("customer_phone") or ""
        masked = phone[-4:] if len(phone) > 4 else phone

        results.append({
            "user": masked,
            "status": "Active",
            "timestamp": last_msg.get("created_at") or convo.get("updated_at") or "2020-01-01T00:00:00",
            "last_content": last_msg.get("message_text", ""),
            # Written by conversation_repository (defaults to "whatsapp"); the
            # dashboard shows which surface a conversation arrived on.
            "channel": convo.get("source_channel") or "whatsapp"
        })

    return results


def get_message_chart_last_7_days(chatbot_id):
    today = datetime.now().date()
    date_counts = {(today - timedelta(days=i)).isoformat(): 0 for i in range(6, -1, -1)}

    start_date = (today - timedelta(days=6)).isoformat()

    response = (
        supabase
        .table("messages")
        .select("created_at,sender_type,conversations!inner(chatbot_id)")
        .eq("sender_type", "customer")
        .eq("conversations.chatbot_id", chatbot_id)
        .gte("created_at", f"{start_date}T00:00:00")
        .execute()
    )

    rows = response.data or []

    for row in rows:
        created_at = row.get("created_at")
        if not created_at:
            continue

        try:
            msg_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
            msg_date_str = msg_date.isoformat()
            if msg_date_str in date_counts:
                date_counts[msg_date_str] += 1
        except Exception:
            pass

    chart_labels = []
    chart_data = []

    for d in sorted(date_counts.keys()):
        day_name = datetime.fromisoformat(d).strftime("%a")
        chart_labels.append(day_name)
        chart_data.append(date_counts[d])

    return {
        "labels": chart_labels,
        "data": chart_data
    }


def get_transcript_logs(chatbot_id, days=7):
    """
    Fetch all conversation messages for the given chatbot_id in the last X days,
    sorted chronologically, and group them by customer conversation.
    """
    start_date = (datetime.now() - timedelta(days=days)).date().isoformat()
    
    rows, cursor = [], 0
    while True:
        response = (supabase.table("messages")
            .select("id,conversation_id,sender_type,ai_generated,actor_user_id,message_text,created_at,conversations!inner(chatbot_id,customer_phone)")
            .eq("conversations.chatbot_id", chatbot_id).gte("created_at", f"{start_date}T00:00:00")
            .gt("id", cursor).order("id").limit(500).execute())
        if not isinstance(response.data, list):
            raise RuntimeError("Report transcript source is unavailable")
        if not response.data:
            break
        rows.extend(response.data)
        next_cursor = response.data[-1]["id"]
        if next_cursor <= cursor or len(rows) > 5000:
            raise ValueError("Conversation report exceeds its processing limit; choose a shorter period")
        cursor = next_cursor

    # Conversation identity includes anonymous web sessions and keeps sessions distinct.
    grouped = {}
    for row in rows:
        conv = row.get("conversations", {})
        identity = row["conversation_id"]
        if identity not in grouped:
            grouped[identity] = {"phone": conv.get("customer_phone") or "", "lines": []}
        sender = row.get("sender_type")
        role = "Customer" if sender == "customer" else "Staff" if sender == "human" or (sender == "bot" and row.get("actor_user_id")) else "Non-AI reply (sender unconfirmed)" if sender == "bot" and row.get("ai_generated") is False else "Bot" if sender == "bot" else "System"
        text = row.get("message_text") or ""
        created_at = row.get("created_at") or ""
        grouped[identity]["lines"].append(f"[{created_at}] {role}: {text}")
        
    results = []
    for identity, item in grouped.items():
        results.append({
            "conversation_id": identity,
            "phone": item["phone"],
            "chat": "\n".join(item["lines"])
        })
        
    return results
