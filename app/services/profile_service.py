from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "bot_configs"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row_to_profile(row):
    return {
        "id": row.get("id"),
        "name": row.get("profile_name") or "",
        "bot_name": row.get("bot_name") or "",
        "company_name": row.get("company_name") or "",
        "business_description": row.get("business_description")
        or row.get("business_objective")
        or "",
        "tone": row.get("tone") or row.get("response_style") or "",
        "additional_instructions": row.get("additional_instructions") or "",
        "custom_prompt": row.get("custom_prompt") or row.get("prompt_text") or "",
        "is_active": row.get("is_active", False),
    }


def get_profiles():
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .order("id")
        .execute()
    )

    rows = response.data or []
    return [_row_to_profile(row) for row in rows]


def get_profile_by_name(profile_name):
    if not profile_name:
        return None

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("profile_name", profile_name)
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        return None

    return _row_to_profile(rows[0])


def save_profile(profile_data):
    profile_name = profile_data.get("name", "").strip()

    if not profile_name:
        raise ValueError("Profile name is required")

    row_data = {
        "profile_name": profile_name,
        "bot_name": profile_data.get("bot_name", ""),
        "company_name": profile_data.get("company_name", ""),
        "business_description": profile_data.get("business_description", ""),
        "tone": profile_data.get("tone", ""),
        "additional_instructions": profile_data.get("additional_instructions", ""),
        "custom_prompt": profile_data.get("custom_prompt", ""),

        # Keep old table meaning also filled
        "prompt_text": profile_data.get("custom_prompt", ""),
        "business_objective": profile_data.get("business_description", ""),
        "response_style": profile_data.get("tone", ""),
        "out_of_scope_reply": profile_data.get("out_of_scope_reply", ""),

        "updated_at": _now_iso(),
    }

    existing_response = (
        supabase
        .table(TABLE_NAME)
        .select("id")
        .eq("profile_name", profile_name)
        .limit(1)
        .execute()
    )

    existing_rows = existing_response.data or []

    if existing_rows:
        profile_id = existing_rows[0]["id"]

        response = (
            supabase
            .table(TABLE_NAME)
            .update(row_data)
            .eq("id", profile_id)
            .execute()
        )
    else:
        row_data["is_active"] = False

        response = (
            supabase
            .table(TABLE_NAME)
            .insert(row_data)
            .execute()
        )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to save profile")

    return _row_to_profile(rows[0])


def delete_profile(profile_name):
    if not profile_name:
        raise ValueError("Profile name is required")

    existing_profile = get_profile_by_name(profile_name)

    if not existing_profile:
        raise ValueError("Profile not found")

    (
        supabase
        .table(TABLE_NAME)
        .delete()
        .eq("profile_name", profile_name)
        .execute()
    )

    return existing_profile