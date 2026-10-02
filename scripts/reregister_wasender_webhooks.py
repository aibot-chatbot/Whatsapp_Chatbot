"""Re-point every connected WasenderAPI session at the current PUBLIC_BASE_URL.

Why this exists: the webhook URL is built once at connect time
(wasender_routes.py:184) and handed to WasenderAPI. Change PUBLIC_BASE_URL -- a
move to a real domain -- and every already-connected session keeps posting to
the old host. Nothing announces it: the row still says "connected" and the
dashboard still says connected, while inbound customer messages land nowhere.
Telegram already had this script; Wasender did not.

It verifies by reading the session back from WasenderAPI rather than trusting
the update call, for the reason telegram_routes.py:327 records about
setWebhook: a provider that accepts a URL without contacting it cannot be
trusted to have stored what you sent.

Three things that make this different from the Telegram script:

  * The secret is NOT rotated by default. It lives in the URL path and it is
    the only authentication factor on this webhook -- there is no signature
    header -- but rotating it on every run would mean the target URL is
    different every run, so no run could ever report a no-op, and each one
    would open a window where WasenderAPI and the database disagree about
    which secret is live. Pass --rotate-secret when the secret itself is the
    problem; then treat it as a maintenance window, not a routine re-point.
  * The session endpoint is authenticated with the TENANT's personal access
    token, which this app never stores (wasender_routes.py takes it per
    request). Without one, a channel is reported needs-token and left
    completely alone -- rewriting the row without telling WasenderAPI would
    leave the database claiming a URL the provider has never heard of.
  * It NEVER writes connection_status or is_active.
    get_wasender_channel_by_secret (wasender_channel_repository.py:41) filters
    on connection_status == "connected", so writing "failed" here would stop
    routing inbound messages for a channel that may still be delivering. A
    failed re-point is recorded in last_error only.

No secret is ever printed. Webhook URLs are shown with the path secret replaced
by its SHA-256 fingerprint prefix, the same shape wasender_routes.py:426 logs.

    python scripts/reregister_wasender_webhooks.py            # show what would change
    python scripts/reregister_wasender_webhooks.py --apply --personal-access-token TOKEN
    python scripts/reregister_wasender_webhooks.py --apply --channel-id 9 --personal-access-token TOKEN

Run it LOCALLY. It is not in the container image and cannot be: the
.dockerignore allowlist is machine-derived and test_container_release.py
asserts it equals exactly the tracked app/*.py and frontend files, so adding
scripts/ would fail that test. `fly ssh console` will not find this file.
Running locally means the operator needs PUBLIC_BASE_URL, the Supabase service
credentials and each tenant's personal access token on that machine for the
duration; prefer passing the token as an argument over leaving it in .env.

Safe to re-run. A session already pointing at the right URL is reported as a
no-op and nothing is sent for it.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

import os  # noqa: E402  (must follow load_dotenv)

from app.database.db import supabase  # noqa: E402
from app.database.wasender_channel_repository import update_wasender_channel  # noqa: E402
# Reused rather than re-derived: _provider_get already encodes the house rule
# that a 5xx/429 is "the provider is unwell" (RequestException, retry later)
# while any other non-200 is "the credentials are wrong" (ValueError).
from app.services.provider_connection_verification import _provider_get  # noqa: E402

WEBHOOK_PATH = "/wasender/webhook/"
REQUIRED_EVENT = "messages.received"
PROVIDER_TIMEOUT_SECONDS = 15
FINGERPRINT_LENGTH = 12


def fingerprint(secret: str) -> str:
    """Enough to tell two channels apart in a log, useless to an attacker."""
    return hashlib.sha256(str(secret).encode()).hexdigest()[:FINGERPRINT_LENGTH]


def redact(url) -> str:
    """A webhook URL with its path secret replaced by the secret's fingerprint."""
    if not url:
        return "unset"
    head, marker, secret = str(url).partition(WEBHOOK_PATH)
    if not marker:
        return str(url)
    return f"{head}{marker}{fingerprint(secret)}"


def wasender_base() -> str:
    return os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com").rstrip("/")


def public_base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")


def read_session(session_id, personal_access_token: str) -> dict:
    """WasenderAPI's own view of one session. This is the verification."""
    payload = _provider_get(
        f"{wasender_base()}/api/whatsapp-sessions/{session_id}", personal_access_token)
    session = payload.get("data")
    if not isinstance(session, dict):
        raise ValueError("WasenderAPI did not return a verifiable session.")
    return session


def set_session_webhook(session_id, personal_access_token: str, webhook_url: str) -> None:
    """Point the session at webhook_url and make sure inbound messages are on."""
    response = requests.put(
        f"{wasender_base()}/api/whatsapp-sessions/{session_id}",
        headers={"Authorization": f"Bearer {personal_access_token}"},
        json={
            "webhook_url": webhook_url,
            "webhook_enabled": True,
            "webhook_events": [REQUIRED_EVENT],
        },
        timeout=PROVIDER_TIMEOUT_SECONDS,
    )
    if response.status_code >= 500 or response.status_code == 429:
        raise requests.RequestException(
            f"WasenderAPI is temporarily unavailable (HTTP {response.status_code})."
        )
    if response.status_code not in (200, 201):
        raise ValueError("WasenderAPI rejected the webhook update. Check the personal access token.")
    data = response.json()
    if not isinstance(data, dict) or data.get("success") is False or data.get("error"):
        raise ValueError("WasenderAPI returned an unsuccessful update response.")


def session_matches(session: dict, target: str) -> bool:
    """A right URL with delivery switched off still delivers nothing."""
    events = session.get("webhook_events") or []
    return (session.get("webhook_url") == target
            and session.get("webhook_enabled") is True
            and REQUIRED_EVENT in events)


def load_channels(chatbot_id: int | None = None, company_id: int | None = None,
                  channel_id: int | None = None) -> list:
    """Every active WasenderAPI channel, optionally narrowed."""
    query = supabase.table("wasender_channels").select("*").eq("is_active", True)
    if chatbot_id is not None:
        query = query.eq("chatbot_id", chatbot_id)
    if company_id is not None:
        query = query.eq("company_id", company_id)
    if channel_id is not None:
        query = query.eq("id", channel_id)
    return query.execute().data or []


def reregister(channel: dict, base_url: str, personal_access_token: str | None,
               apply: bool, rotate_secret: bool = False) -> tuple[str, str]:
    """Return (outcome, detail) for one channel. Never returns a secret."""
    label = (channel.get("session_name") or channel.get("phone_number")
             or channel.get("id"))
    session_id = channel.get("session_id")

    if not session_id:
        return "skipped", f"{label}: no WasenderAPI session ID stored, reconnect it from the app"
    if not personal_access_token:
        return "needs-token", (
            f"{label}: needs this tenant's WasenderAPI personal access token; "
            f"pass --personal-access-token and scope the run to their channels"
        )

    stored_secret = channel.get("webhook_secret")
    # A row with no secret cannot address a webhook at all, so it gets one
    # whether or not rotation was asked for.
    rotating = rotate_secret or not stored_secret
    secret = secrets.token_urlsafe(32) if rotating else stored_secret
    target = f"{base_url}{WEBHOOK_PATH}{secret}"

    try:
        session = read_session(session_id, personal_access_token)
    except requests.RequestException:
        # Deliberately not echoing the exception: a requests error carries the
        # request URL, and these URLs carry the path secret.
        return "unverified", f"{label}: WasenderAPI would not report the session; nothing was changed"
    except ValueError as error:
        return "failed", f"{label}: cannot read the session. {error}"

    provider_ok = session_matches(session, target)
    row_ok = channel.get("webhook_url") == target
    if provider_ok and row_ok:
        return "no-op", f"{label}: already on {redact(target)}"

    if not apply:
        return "would-update", (
            f"{label}: would point at {redact(target)} "
            f"(WasenderAPI holds {redact(session.get('webhook_url'))}, "
            f"stored: {redact(channel.get('webhook_url'))})"
        )

    if not provider_ok:
        try:
            set_session_webhook(session_id, personal_access_token, target)
        except requests.RequestException:
            return "unverified", f"{label}: WasenderAPI was unavailable mid-update; re-run to find out what took"
        except ValueError as error:
            return "failed", f"{label}: WasenderAPI refused the update. {error}"

        # The update returning success proves only that WasenderAPI parsed it.
        try:
            session = read_session(session_id, personal_access_token)
        except requests.RequestException:
            return "unverified", f"{label}: sent {redact(target)} but WasenderAPI would not confirm it"
        except ValueError as error:
            return "failed", f"{label}: sent {redact(target)} but the read-back was unusable. {error}"

        if not session_matches(session, target):
            reason = (f"WasenderAPI accepted the update and is holding "
                      f"{redact(session.get('webhook_url'))} "
                      f"(enabled={session.get('webhook_enabled')}, "
                      f"events={session.get('webhook_events')})")
            # last_error only. connection_status stays untouched, or the
            # inbound secret lookup would stop finding this channel at all.
            update_wasender_channel(channel["id"], {"last_error": reason})
            return "failed", f"{label}: {reason}"

    changes = {"webhook_url": target, "last_error": None}
    if rotating:
        # Written only after WasenderAPI has confirmed the new URL, so the
        # window where the provider posts a secret the database does not know
        # is as short as one update call.
        changes["webhook_secret"] = secret
    update_wasender_channel(channel["id"], changes)
    return "updated", f"{label}: now on {redact(target)}, confirmed against WasenderAPI"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--chatbot-id", type=int, default=None)
    parser.add_argument("--company-id", type=int, default=None)
    parser.add_argument("--channel-id", type=int, default=None)
    parser.add_argument("--personal-access-token", default=None,
                        help="the tenant's WasenderAPI personal access token "
                             "(or set WASENDER_PERSONAL_ACCESS_TOKEN)")
    parser.add_argument("--rotate-secret", action="store_true",
                        help="mint a new path secret; only when the old one leaked")
    args = parser.parse_args()

    base_url = public_base_url()
    if not base_url:
        print("PUBLIC_BASE_URL is not set. Nothing to point the sessions at.")
        return 1
    if not base_url.startswith("https://"):
        print(f"PUBLIC_BASE_URL is {base_url!r}. WasenderAPI only delivers to https.")
        return 1

    token = args.personal_access_token or os.getenv("WASENDER_PERSONAL_ACCESS_TOKEN")
    channels = load_channels(args.chatbot_id, args.company_id, args.channel_id)
    companies = len({channel.get("company_id") for channel in channels})

    print(f"Base URL : {base_url}")
    print(f"Channels : {len(channels)} across {companies} companies")
    print("Mode     : " + ("APPLY" if args.apply else "dry run, pass --apply to write"))
    if args.rotate_secret:
        print("Secrets  : ROTATING - inbound is dead for each channel until its update lands")
    print("-" * 70)

    tally: dict[str, int] = {}
    for channel in channels:
        outcome, detail = reregister(channel, base_url, token, args.apply, args.rotate_secret)
        tally[outcome] = tally.get(outcome, 0) + 1
        print(f"  [{outcome:>13}] {detail}")

    print("-" * 70)
    print(", ".join(f"{count} {name}" for name, count in sorted(tally.items())) or "nothing to do")

    if tally.get("failed"):
        return 2
    # Nothing was confirmed for these, so a caller reading only the exit code
    # must not be told the run succeeded.
    if tally.get("unverified") or tally.get("needs-token"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
