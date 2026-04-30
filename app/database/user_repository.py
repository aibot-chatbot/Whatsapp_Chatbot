from app.database.db import supabase


def get_user_by_email(email):
    response = supabase.table("users") \
        .select("*") \
        .eq("email", email) \
        .limit(1) \
        .execute()

    data = response.data

    if not data:
        return None

    return data[0]