"""Re-point the Meta WhatsApp webhook at the current PUBLIC_BASE_URL.

Why this exists: the webhook destination is baked into Meta's side, and the
copy stored on each row is baked in at connect time (whatsapp_routes.py:107,
build_webhook_url). Move the app to a new domain and neither one follows. The
dashboard keeps saying "connected" while inbound customer messages go to a host
that no longer answers. Telegram already had this script; WhatsApp did not.

WhatsApp is shaped differently from Telegram, and the difference is the whole
reason this file is not a copy of reregister_telegram_webhooks.py:

  * The callback URL is configured on the META APP, not on the channel. One
    POST re-points every tenant at once. That is the blast radius, and the
    script prints it before it touches anything.
  * A WABA may carry its own override_callback_uri, which BEATS the app-level
    callback for that tenant's messages. Fixing only the app default leaves
    every overridden tenant posting into the void -- silently. So each channel
    is checked separately.
  * This script NEVER writes connection_status or is_active.
    get_whatsapp_channel_by_phone_number_id (whatsapp_channel_repository.py:86)
    filters on connection_status == "connected", so writing "failed" here would
    take a tenant whose messages are still arriving via the app-level callback
    and stop routing them. A failed re-point is recorded in last_error only.

Verification is a read-back, never the return value of the write. Meta accepts
a callback_url it has never contacted -- the same trap telegram_routes.py:327
records for setWebhook -- so the only proof is asking Meta what it now holds.

    python scripts/reregister_whatsapp_webhooks.py            # show what would change
    python scripts/reregister_whatsapp_webhooks.py --apply    # do it
    python scripts/reregister_whatsapp_webhooks.py --apply --channel-id 11

Run it LOCALLY. It is not in the container image and cannot be: the
.dockerignore allowlist is machine-derived and test_container_release.py
asserts it equals exactly the tracked app/*.py and frontend files, so adding
scripts/ would fail that test. `fly ssh console` will not find this file.
Running locally means the operator needs PUBLIC_BASE_URL, the Supabase service
credentials and WHATSAPP_META_APP_SECRET in a local .env for the duration.

Safe to re-run. A channel already pointing at the right URL is reported as a
no-op and nothing is sent for it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

import os  # noqa: E402  (must follow load_dotenv)

from app.database.db import supabase  # noqa: E402
from app.database.whatsapp_channel_repository import update_whatsapp_channel  # noqa: E402
# Reused rather than re-derived: _provider_get already encodes the house rule
# that a 5xx/429 is "the provider is unwell" (RequestException, retry later)
# while any other non-200 is "the credentials are wrong" (ValueError). Getting
# that backwards is how a bad two seconds at Meta gets recorded as a permanent
# failure on every tenant at once.
from app.services.provider_connection_verification import _provider_get  # noqa: E402

SUBSCRIPTION_OBJECT = "whatsapp_business_account"
MESSAGES_FIELD = "messages"
PROVIDER_TIMEOUT_SECONDS = 15


def graph_base() -> str:
    version = os.getenv("WHATSAPP_GRAPH_API_VERSION") or os.getenv("VERSION") or "v22.0"
    return f"https://graph.facebook.com/{version}"


def public_base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")


def meta_app_credentials() -> tuple[str, str, str]:
    """(app_id, app_secret, verify_token) as the running app reads them."""
    return (
        (os.getenv("WHATSAPP_META_APP_ID") or "").strip(),
        os.getenv("WHATSAPP_META_APP_SECRET") or "",
        os.getenv("VERIFY_TOKEN") or "",
    )


def _provider_post(url: str, token: str, payload: dict) -> dict:
    """POST counterpart to _provider_get, with the same 5xx-vs-4xx split.

    Graph writes are form-encoded, so the payload goes in `data`. Nothing from
    the response or the request is ever echoed to the caller: the payload
    carries the verify token.
    """
    if not token:
        raise ValueError("Provider credentials are missing.")
    response = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                             data=payload, timeout=PROVIDER_TIMEOUT_SECONDS)
    if response.status_code >= 500 or response.status_code == 429:
        raise requests.RequestException(
            f"Meta is temporarily unavailable (HTTP {response.status_code})."
        )
    if response.status_code != 200:
        raise ValueError("Meta rejected the webhook registration. Check the app credentials.")
    data = response.json()
    if not isinstance(data, dict) or data.get("success") is False or data.get("error"):
        raise ValueError("Meta returned an unsuccessful registration response.")
    return data


def _has_messages_field(subscription: dict) -> bool:
    fields = subscription.get("fields")
    if not isinstance(fields, list):
        return False
    return any((field.get("name") if isinstance(field, dict) else field) == MESSAGES_FIELD
               for field in fields)


def read_app_subscription(app_id: str, app_secret: str) -> dict | None:
    """The app's one whatsapp_business_account webhook subscription, or None.

    This read needs the server's own app token, not any tenant's token.
    """
    payload = _provider_get(f"{graph_base()}/{app_id}/subscriptions", f"{app_id}|{app_secret}")
    rows = payload.get("data")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Meta did not return a verifiable webhook configuration.")
    matching = [row for row in rows if row.get("object") == SUBSCRIPTION_OBJECT]
    if len(matching) > 1:
        raise ValueError("The Meta app has more than one WhatsApp webhook subscription.")
    return matching[0] if matching else None


def set_app_subscription(callback_url: str, verify_token: str, app_id: str, app_secret: str) -> None:
    _provider_post(f"{graph_base()}/{app_id}/subscriptions", f"{app_id}|{app_secret}", {
        "object": SUBSCRIPTION_OBJECT,
        "callback_url": callback_url,
        "verify_token": verify_token,
        "fields": MESSAGES_FIELD,
    })


def read_waba_override(waba_id: str, access_token: str, app_id: str) -> tuple[bool, str | None]:
    """(is this WABA subscribed to our app, what override URL does it carry).

    A None override means the WABA inherits the app-level callback, which is
    the state we want once the app subscription is correct.
    """
    payload = _provider_get(f"{graph_base()}/{waba_id}/subscribed_apps", access_token)
    rows = payload.get("data")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Meta did not return verifiable WhatsApp app subscriptions.")
    for row in rows:
        app = row.get("whatsapp_business_api_data", row)
        if isinstance(app, dict) and str(app.get("id")) == str(app_id):
            override = row.get("override_callback_uri")
            if override is not None and not isinstance(override, str):
                raise ValueError("Meta did not return a verifiable webhook callback URL.")
            return True, override
    return False, None


def set_waba_override(waba_id: str, access_token: str, callback_url: str, verify_token: str) -> None:
    _provider_post(f"{graph_base()}/{waba_id}/subscribed_apps", access_token, {
        "override_callback_uri": callback_url,
        "verify_token": verify_token,
    })


def load_channels(chatbot_id: int | None = None, company_id: int | None = None,
                  channel_id: int | None = None) -> list:
    """Every active WhatsApp channel, optionally narrowed."""
    query = supabase.table("whatsapp_channels").select("*").eq("is_active", True)
    if chatbot_id is not None:
        query = query.eq("chatbot_id", chatbot_id)
    if company_id is not None:
        query = query.eq("company_id", company_id)
    if channel_id is not None:
        query = query.eq("id", channel_id)
    return query.execute().data or []


def reregister_app(base_url: str, apply: bool) -> tuple[str, str]:
    """Point the Meta app's own webhook callback at base_url. Affects everyone."""
    app_id, app_secret, verify_token = meta_app_credentials()
    if not app_id or not app_secret:
        return "app-failed", "WHATSAPP_META_APP_ID / WHATSAPP_META_APP_SECRET are not set"

    target = f"{base_url}/webhook"
    try:
        subscription = read_app_subscription(app_id, app_secret)
    except requests.RequestException:
        # Deliberately not echoing the exception: a requests error carries the
        # request URL, and the app token is built from the app secret.
        return "app-unverified", "Meta would not report the app subscription; nothing was changed"
    except ValueError as error:
        return "app-failed", f"cannot read the app subscription. {error}"

    current = subscription.get("callback_url") if subscription else None
    healthy = (subscription is not None and current == target
               and subscription.get("active") is True and _has_messages_field(subscription))
    if healthy:
        return "app-ok", f"app callback is already {target}"

    if not apply:
        return "app-would-update", (
            f"would point the Meta app callback at {target} "
            f"(currently {current or 'unset'}) - this re-points every tenant at once"
        )

    if not verify_token:
        # Meta re-runs the hub.challenge handshake against the new URL and the
        # app answers it from VERIFY_TOKEN (views.py:86). Sending a different
        # one would make Meta reject a URL that the app would have accepted.
        return "app-failed", "VERIFY_TOKEN is not set; Meta would reject the new callback"

    try:
        set_app_subscription(target, verify_token, app_id, app_secret)
    except requests.RequestException:
        return "app-unverified", "Meta was unavailable mid-registration; re-run to find out what took"
    except ValueError as error:
        return "app-failed", f"Meta refused the app callback. {error}"

    # The POST returning success proves only that Meta parsed it. Ask Meta what
    # it actually holds now.
    try:
        confirmed = read_app_subscription(app_id, app_secret)
    except requests.RequestException:
        return "app-unverified", f"registered {target} but Meta would not confirm it"
    except ValueError as error:
        return "app-failed", f"registered {target} but the read-back was unusable. {error}"

    if confirmed is None or confirmed.get("callback_url") != target:
        held = (confirmed or {}).get("callback_url") or "nothing"
        return "app-failed", f"Meta accepted the call and is still holding {held}"
    if confirmed.get("active") is not True or not _has_messages_field(confirmed):
        return "app-failed", f"callback is {target} but the messages subscription is not active"
    return "app-updated", f"app callback is now {target}, confirmed by reading it back"


def reregister(channel: dict, base_url: str, apply: bool) -> tuple[str, str]:
    """Return (outcome, detail) for one channel's WABA-level override."""
    label = (channel.get("display_phone_number") or channel.get("phone_number_id")
             or channel.get("id"))
    access_token = channel.get("access_token")
    waba_id = channel.get("whatsapp_business_account_id") or channel.get("waba_id")
    app_id, _, verify_token = meta_app_credentials()

    if not access_token or not waba_id:
        return "skipped", f"{label}: no stored token or WABA id, reconnect it from the app"

    target = f"{base_url}/webhook"
    try:
        subscribed, override = read_waba_override(waba_id, access_token, app_id)
    except requests.RequestException:
        return "unverified", f"{label}: Meta would not report this WABA; nothing was changed"
    except ValueError as error:
        return "failed", f"{label}: cannot read this WABA's subscription. {error}"

    if not subscribed:
        return "failed", f"{label}: this WABA is not subscribed to the Meta app; reconnect it from the app"

    override_stale = override is not None and override != target
    row_stale = channel.get("webhook_url") != target
    if not override_stale and not row_stale:
        return "no-op", f"{label}: already on {target}"

    if not apply:
        held = override if override is not None else "the app-level callback"
        return "would-update", (
            f"{label}: would point at {target} "
            f"(WABA override: {held}, stored: {channel.get('webhook_url') or 'unset'})"
        )

    if override_stale:
        if not verify_token:
            return "failed", f"{label}: VERIFY_TOKEN is not set; Meta would reject the new override"
        try:
            set_waba_override(waba_id, access_token, target, verify_token)
        except requests.RequestException:
            return "unverified", f"{label}: Meta was unavailable mid-registration; re-run to find out what took"
        except ValueError as error:
            return "failed", f"{label}: Meta refused the override. {error}"

        # Read-back, for the same reason as above: an accepted URL is not a
        # stored URL, and an override that quietly survives keeps this one
        # tenant pointed at the dead host while every other tenant is fine.
        try:
            _, confirmed = read_waba_override(waba_id, access_token, app_id)
        except requests.RequestException:
            return "unverified", f"{label}: registered {target} but Meta would not confirm it"
        except ValueError as error:
            return "failed", f"{label}: registered {target} but the read-back was unusable. {error}"

        if confirmed is not None and confirmed != target:
            reason = f"Meta accepted the override and is still holding {confirmed}"
            # last_error only. connection_status stays untouched: this channel
            # may still be delivering through the app-level callback, and
            # flipping it to "failed" would stop the inbound lookup dead.
            update_whatsapp_channel(channel["id"], {"last_error": reason})
            return "failed", f"{label}: {reason}"

    update_whatsapp_channel(channel["id"], {"webhook_url": target, "last_error": None})
    return "updated", f"{label}: now on {target}, confirmed against Meta"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--chatbot-id", type=int, default=None)
    parser.add_argument("--company-id", type=int, default=None)
    parser.add_argument("--channel-id", type=int, default=None)
    args = parser.parse_args()

    base_url = public_base_url()
    if not base_url:
        print("PUBLIC_BASE_URL is not set. Nothing to point the webhook at.")
        return 1
    if not base_url.startswith("https://"):
        print(f"PUBLIC_BASE_URL is {base_url!r}. Meta only delivers to https.")
        return 1

    channels = load_channels(args.chatbot_id, args.company_id, args.channel_id)
    scoped = any(value is not None for value in (args.chatbot_id, args.company_id, args.channel_id))
    companies = len({channel.get("company_id") for channel in channels})

    print(f"Base URL : {base_url}")
    print(f"Channels : {len(channels)} across {companies} companies")
    print("Mode     : " + ("APPLY" if args.apply else "dry run, pass --apply to write"))
    print("-" * 70)

    tally: dict[str, int] = {}

    # The app-level callback is global. Re-pointing every tenant while the
    # operator asked about one of them would be a blast radius they did not
    # ask for, so a scoped run touches WABA overrides only.
    if scoped:
        print("  [        scoped] app-level callback left alone; re-run without a filter to move it")
    else:
        outcome, detail = reregister_app(base_url, args.apply)
        tally[outcome] = tally.get(outcome, 0) + 1
        print(f"  [{outcome:>14}] {detail}")

    for channel in channels:
        outcome, detail = reregister(channel, base_url, args.apply)
        tally[outcome] = tally.get(outcome, 0) + 1
        print(f"  [{outcome:>14}] {detail}")

    print("-" * 70)
    print(", ".join(f"{count} {name}" for name, count in sorted(tally.items())) or "nothing to do")

    if tally.get("failed") or tally.get("app-failed"):
        return 2
    # "unverified" means Meta would not tell us what it now holds. Nothing was
    # confirmed, so a caller reading only the exit code must not be told this
    # was a success.
    if tally.get("unverified") or tally.get("app-unverified"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
