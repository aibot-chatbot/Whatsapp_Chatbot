from datetime import datetime, timedelta
from app.database.db import supabase


def get_total_users(chatbot_id=1):
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


def get_transcript_logs(chatbot_id=1, days=7):
    """
    Fetch all conversation messages for the given chatbot_id in the last X days,
    sorted chronologically, and group them by customer conversation.
    """
    start_date = (datetime.now() - timedelta(days=days)).date().isoformat()
    
    response = (
        supabase
        .table("messages")
        .select("sender_type,message_text,created_at,conversations!inner(chatbot_id,customer_phone)")
        .eq("conversations.chatbot_id", chatbot_id)
        .gte("created_at", f"{start_date}T00:00:00")
        .order("created_at")
        .execute()
    )
    
    rows = response.data or []
    
    # Group by customer_phone
    grouped = {}
    for row in rows:
        conv = row.get("conversations", {})
        phone = conv.get("customer_phone")
        if not phone:
            continue
            
        if phone not in grouped:
            grouped[phone] = []
            
        role = "Customer" if row.get("sender_type") == "customer" else "Bot"
        text = row.get("message_text") or ""
        created_at = row.get("created_at") or ""
        grouped[phone].append(f"[{created_at}] {role}: {text}")
        
    results = []
    for phone, lines in grouped.items():
        results.append({
            "phone": phone,
            "chat": "\n".join(lines)
        })
        
    return results