from datetime import datetime, timedelta
from app.database.db import supabase


def get_total_users(chatbot_id=1):
    response = (
        supabase
        .table("conversations")
        .select("id", count="exact")
        .eq("chatbot_id", chatbot_id)
        .execute()
    )
    return response.count or 0


def get_total_user_messages(chatbot_id=1):
    response = (
        supabase
        .table("messages")
        .select("id,conversations!inner(chatbot_id)", count="exact")
        .eq("sender_type", "customer")
        .eq("conversations.chatbot_id", chatbot_id)
        .execute()
    )
    return response.count or 0


def get_recent_history(chatbot_id=1, limit=4):
    convo_res = (
        supabase
        .table("conversations")
        .select("id,customer_phone,updated_at")
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

        phone = convo.get("customer_phone", "")
        masked = phone[-4:] if len(phone) > 4 else phone

        results.append({
            "user": masked,
            "status": "Active",
            "timestamp": last_msg.get("created_at") or convo.get("updated_at") or "2020-01-01T00:00:00",
            "last_content": last_msg.get("message_text", "")
        })

    return results


def get_message_chart_last_7_days(chatbot_id=1):
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