"""Re-point every connected Telegram bot at the current PUBLIC_BASE_URL.

Why this exists: the webhook URL is baked into Telegram's side at connect time.
Change PUBLIC_BASE_URL -- a new tunnel, a move to a real deployment -- and every
already-connected bot keeps posting to the old address until someone opens the
UI and reconnects it one at a time. That is the failure this script removes.

It also verifies afterwards with getWebhookInfo rather than trusting setWebhook,
because setWebhook returns ok for a URL Telegram cannot actually reach.

    python scripts/reregister_telegram_webhooks.py            # show what would change
    python scripts/reregister_telegram_webhooks.py --apply    # do it
    python scripts/reregister_telegram_webhooks.py --apply --chatbot-id 42

Safe to re-run. A bot that fails is left with its row intact and its reason
recorded, so a second run retries it.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

import os  # noqa: E402  (must follow load_dotenv)

from app.database.db import supabase  # noqa: E402
from app.database.telegram_channel_repository import update_telegram_channel  # noqa: E402
from app.routes.telegram_routes import (  # noqa: E402
    DELIVERY_STATUS_OK,
    DELIVERY_STATUS_UNKNOWN,
    check_telegram_webhook_delivery,
    clean_public_base_url,
    set_telegram_webhook,
    validate_telegram_bot_token,
)


def load_channels(chatbot_id: int | None) -> list:
    """Every active Telegram channel, optionally narrowed to one chatbot."""
    query = supabase.table("telegram_channels").select("*").eq("is_active", True)
    if chatbot_id is not None:
        query = query.eq("chatbot_id", chatbot_id)
    return query.execute().data or []


def reregister(channel: dict, base_url: str, apply: bool) -> tuple[str, str]:
    """Return (outcome, detail) for one channel."""
    label = channel.get("bot_username") or channel.get("telegram_bot_id") or channel.get("id")
    bot_token = channel.get("bot_token")

    if not bot_token:
        return "skipped", f"{label}: no stored token, reconnect it from the app"

    info, token_error = validate_telegram_bot_token(bot_token)
    if token_error:
        if apply:
            update_telegram_channel(channel["id"], {
                "connection_status": "failed",
                "last_error": token_error,
                "is_active": False,
            })
        return "failed", f"{label}: token rejected by Telegram"

    # A fresh secret per registration: the old one is in the old URL, which may
    # have been logged or shared while the tunnel was public.
    secret = secrets.token_urlsafe(32)
    webhook_url = f"{base_url}/telegram/webhook/{secret}"

    if not apply:
        return "would-update", f"{label}: would point at {base_url}/telegram/webhook/***"

    # Stamped before the call: getWebhookInfo reports the last delivery error
    # whenever it happened, and the URL we are replacing has almost certainly
    # been failing for a while. Without this the old tunnel's error condemns
    # the new registration on every single bot.
    registered_at = int(time.time())
    ok, error = set_telegram_webhook(bot_token, webhook_url, secret_token=secret)
    if not ok:
        update_telegram_channel(channel["id"], {
            "connection_status": "failed",
            "last_error": error,
        })
        return "failed", f"{label}: setWebhook refused it"

    update_telegram_channel(channel["id"], {
        "telegram_bot_id": str(info.get("id")),
        "bot_username": info.get("username"),
        "webhook_secret": secret,
        "webhook_url": webhook_url,
        "connection_status": "connected",
        "last_error": None,
    })

    # setWebhook returning ok proves nothing about delivery, so ask Telegram
    # whether it can actually reach us before calling this a success.
    status, reason, _ = check_telegram_webhook_delivery(
        bot_token, webhook_url, registered_since=registered_at
    )
    if status == DELIVERY_STATUS_OK:
        return "connected", f"@{info.get('username')}: delivering"

    if status == DELIVERY_STATUS_UNKNOWN:
        # Telegram would not tell us. That is our blind spot, not proof the new
        # registration is broken, so the row keeps the "connected" written above
        # rather than reporting a working bot as failed.
        return "unverified", f"@{info.get('username')}: re-pointed, delivery unconfirmed"

    update_telegram_channel(channel["id"], {
        "connection_status": "failed",
        "last_error": reason,
    })
    return "undelivered", f"@{info.get('username')}: registered but not delivering. {reason}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--chatbot-id", type=int, default=None)
    args = parser.parse_args()

    base_url = clean_public_base_url(os.getenv("PUBLIC_BASE_URL"))
    if not base_url:
        print("PUBLIC_BASE_URL is not set. Nothing to point the bots at.")
        return 1
    if not base_url.startswith("https://"):
        print(f"PUBLIC_BASE_URL is {base_url!r}. Telegram only delivers to https.")
        return 1

    channels = load_channels(args.chatbot_id)
    if not channels:
        print("No active Telegram channels found.")
        return 0

    print(f"Base URL : {base_url}")
    print(f"Channels : {len(channels)}")
    print("Mode     : " + ("APPLY" if args.apply else "dry run, pass --apply to write"))
    print("-" * 60)

    tally: dict[str, int] = {}
    for channel in channels:
        outcome, detail = reregister(channel, base_url, args.apply)
        tally[outcome] = tally.get(outcome, 0) + 1
        print(f"  [{outcome:>13}] {detail}")

    print("-" * 60)
    print(", ".join(f"{count} {name}" for name, count in sorted(tally.items())))
    if tally.get("failed") or tally.get("undelivered"):
        return 2
    # "unverified" means Telegram would not tell us whether it can deliver. The
    # row keeps the connected status we wrote, but nothing was confirmed - so a
    # caller reading only the exit code must not be told this was a success.
    if tally.get("unverified"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
