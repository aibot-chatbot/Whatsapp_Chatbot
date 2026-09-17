import logging

from app.database.db import supabase
from app.database.db_errors import is_unique_violation

TABLE_NAME = "processed_telegram_updates"


def claim_telegram_update(telegram_channel_id, update_id):
    """Atomically take ownership of one Telegram update.

    Returns True when this caller won the update and should process it, False
    when another in-flight request already owns it.

    This exists because checking `is_telegram_update_processed` and only writing
    the marker afterwards is a race, not a guard: Telegram re-delivers an update
    it considers undelivered, and while the first request is still waiting on the
    model both requests read "not processed" and the customer is answered twice.

    The UNIQUE (telegram_channel_id, update_id) index makes the INSERT itself the
    claim, so Postgres picks the winner and the loser gets a 23505.
    """
    if not telegram_channel_id or update_id is None:
        raise ValueError("Telegram update identity is required")

    try:
        supabase.table(TABLE_NAME).insert({
            "telegram_channel_id": telegram_channel_id,
            "update_id": str(update_id),
        }).execute()
        return True
    except Exception as error:
        if is_unique_violation(error):
            return False
        raise


def release_telegram_update_claim(telegram_channel_id, update_id):
    """Hand the claim back after processing failed, so a retry can pick it up.

    Best effort on purpose: this runs while another exception is already being
    handled, and raising here would replace the real error with a database one.
    Leaving a stale claim only costs one un-answered message, which is what
    already happened.
    """
    if not telegram_channel_id or update_id is None:
        return

    try:
        (
            supabase
            .table(TABLE_NAME)
            .delete()
            .eq("telegram_channel_id", telegram_channel_id)
            .eq("update_id", str(update_id))
            .execute()
        )
    except Exception:
        logging.warning(
            "Could not release Telegram update claim; a retry of this update "
            "will be ignored as a duplicate.",
        )


def is_telegram_update_processed(telegram_channel_id: int, update_id: str):
    """
    Check whether this Telegram update has already been processed.
    This prevents duplicate bot replies if Telegram retries the webhook.
    """
    if not telegram_channel_id or update_id is None:
        return False

    response = (
        supabase
        .table(TABLE_NAME)
        .select("id")
        .eq("telegram_channel_id", telegram_channel_id)
        .eq("update_id", str(update_id))
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return len(rows) > 0


def save_processed_telegram_update(telegram_channel_id: int, update_id: str):
    """
    Save processed Telegram update ID after successful handling.
    """
    if not telegram_channel_id or update_id is None:
        raise ValueError("telegram_channel_id and update_id are required")

    response = (
        supabase
        .table(TABLE_NAME)
        .insert({
            "telegram_channel_id": telegram_channel_id,
            "update_id": str(update_id),
        })
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise ValueError("Failed to save processed Telegram update")

    return rows[0]