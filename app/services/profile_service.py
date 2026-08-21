from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

from app.database.db import supabase
from app.services.bot_config_fields import (
    PROVENANCE_CLIENT,
    PROVENANCE_COLUMN,
    merge_persona_write,
    persona_provenance_payload,
    persona_write_payload,
    resolve_persona_fields,
    resolve_persona_provenance,
)


TABLE_NAME = "bot_configs"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row_to_profile(row):
    return {
        "id": row.get("id"),
        "name": row.get("profile_name") or "",
        "bot_name": row.get("bot_name") or "",
        "company_name": row.get("company_name") or "",
        "additional_instructions": row.get("additional_instructions") or "",
        "is_active": row.get("is_active", False),
        # save_profile already stamps this on every write; without forwarding it
        # the library's "Last updated" column had nothing to show.
        "updated_at": row.get("updated_at") or "",
        **resolve_persona_fields(row),
        PROVENANCE_COLUMN: {
            field: marker
            for field, marker in resolve_persona_provenance(row).items()
            if marker
        },
    }


def get_profiles(chatbot_id):
    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .order("id")
        .execute()
    )

    rows = response.data or []
    return [_row_to_profile(row) for row in rows]


def get_tones_for_chatbots(
    chatbot_ids: Iterable[int],
    deployed_profile_names: Mapping[int, str] | None = None,
) -> dict[int, str]:
    """Batch-read the tone that actually reaches the model, per chatbot.

    ``bot_configs.tone`` is the single source of truth for tone; ``chatbots.tone``
    is display-only leftover that no runtime code reads. The bot list needs the
    real value for every card, so this resolves them in ONE query rather than
    one per bot.

    Resolution order per chatbot mirrors ``rag_service.get_deployed_settings``:
    the deployed profile's tone first, because that is the row the reply
    pipeline reads, then the active profile row for a bot that has not deployed
    anything yet. A chatbot with neither maps to "" so the caller can render an
    honest empty state instead of inventing a default.

    Args:
        chatbot_ids: Chatbot identifiers the caller has already scoped to the
            requesting company. This function does not widen that scope.
        deployed_profile_names: Optional ``{chatbot_id: deployed_profile_name}``
            taken from the chatbots rows the caller already holds.
    """
    ids = [chatbot_id for chatbot_id in (chatbot_ids or []) if chatbot_id is not None]

    if not ids:
        return {}

    response = (
        supabase
        .table(TABLE_NAME)
        .select("chatbot_id, profile_name, is_active, tone, response_style")
        .in_("chatbot_id", ids)
        .execute()
    )

    deployed = deployed_profile_names or {}
    deployed_tones: dict[int, str] = {}
    active_tones: dict[int, str] = {}

    for row in response.data or []:
        chatbot_id = row.get("chatbot_id")
        tone = resolve_persona_fields(row).get("tone") or ""

        if not tone:
            continue

        deployed_name = deployed.get(chatbot_id)

        if deployed_name and row.get("profile_name") == deployed_name:
            deployed_tones[chatbot_id] = tone
        elif row.get("is_active") and chatbot_id not in active_tones:
            active_tones[chatbot_id] = tone

    return {
        chatbot_id: deployed_tones.get(chatbot_id) or active_tones.get(chatbot_id) or ""
        for chatbot_id in ids
    }


def get_profile_by_name(profile_name, chatbot_id):
    if not profile_name:
        return None

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("profile_name", profile_name)
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        return None

    return _row_to_profile(rows[0])


def save_profile(profile_data, chatbot_id):
    """Insert or update one profile row.

    Non-persona fields keep the historical full-replace semantics: a key the
    body omits is written blank.  The three derivable persona fields do NOT --
    an omitted key preserves the stored value and its provenance.  Without
    that, a partial body would silently wipe a client override, and the next
    document ingest would then "derive" over the hole, defeating requirement 3
    through a path that never touches the ingestion code.
    """
    profile_name = profile_data.get("name", "").strip()

    if not profile_name:
        raise ValueError("Profile name is required")

    # select("*") rather than select("id"): the stored persona values and their
    # provenance are needed for the merge below, and this is the same single
    # round-trip the lookup already cost.
    existing_response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("chatbot_id", chatbot_id)
        .eq("profile_name", profile_name)
        .limit(1)
        .execute()
    )

    existing_rows = existing_response.data or []
    stored = _row_to_profile(existing_rows[0]) if existing_rows else {}

    persona = merge_persona_write(
        stored,
        stored.get(PROVENANCE_COLUMN),
        profile_data,
        source=PROVENANCE_CLIENT,
    )

    # The three persona fields below are validated against the *merged* value,
    # so a partial save is not rejected for a field the stored row already
    # holds.  bot_name is not part of the persona merge, so it falls back to
    # the stored row by hand to keep the same semantics.
    #
    # ``or ""`` rather than a .get default: a JSON null arrives as None, and
    # None.strip() would raise AttributeError, which profile_routes.py would
    # surface as a 500 instead of the 400 it returns for ValueError.
    final_bot_name = (
        profile_data.get("bot_name") or stored.get("bot_name") or ""
    ).strip()
    if not final_bot_name:
        raise ValueError("Bot name is required")

    for field, label in (
        ("company_name", "Company name"),
        ("business_description", "Business description"),
        ("tone", "Tone"),
    ):
        if not (persona.values.get(field) or "").strip():
            raise ValueError(f"{label} is required")

    row_data = {
        "chatbot_id": chatbot_id,
        "profile_name": profile_name,
        "bot_name": final_bot_name,
        "company_name": persona.values["company_name"],
        "additional_instructions": profile_data.get("additional_instructions", ""),
        "out_of_scope_reply": profile_data.get("out_of_scope_reply", ""),
        **persona_write_payload({**profile_data, **persona.values}),
        **persona_provenance_payload(persona.provenance),
        "updated_at": _now_iso(),
    }

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


def delete_profile(profile_name, chatbot_id):
    if not profile_name:
        raise ValueError("Profile name is required")

    existing_profile = get_profile_by_name(profile_name, chatbot_id)

    if not existing_profile:
        raise ValueError("Profile not found")

    (
        supabase
        .table(TABLE_NAME)
        .delete()
        .eq("chatbot_id", chatbot_id)
        .eq("profile_name", profile_name)
        .execute()
    )

    return existing_profile
