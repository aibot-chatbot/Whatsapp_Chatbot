from flask import g
from app.database.db import supabase


def get_current_company_id():
    company_id = getattr(g, "company_id", None)

    if not company_id:
        raise ValueError("Company ID not found in token. Please login again.")

    return company_id


def verify_chatbot_access(chatbot_id):
    company_id = get_current_company_id()

    response = (
        supabase
        .table("chatbots")
        .select("id, company_id")
        .eq("id", chatbot_id)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise PermissionError("You do not have access to this chatbot.")

    return rows[0]