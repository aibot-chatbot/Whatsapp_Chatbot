"""Inbound webhook payloads must never be written to the logs verbatim.

Those payloads carry our tenants' customers' message text, phone numbers and
profile names. Those people are not our users, never agreed to anything, and
cannot ask us to delete what they never knew we stored. Logs are retained by the
hosting platform and readable by anyone with dashboard access, so a single
f-string here quietly turns an application log into a personal-data store.

This is a source-level invariant rather than a behavioural test on purpose: the
failure it guards is "someone adds a convenient debug line", and that is visible
in the source long before it is visible in a response.
"""

import pathlib
import re
import logging

import httpx

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

# Interpolating one of these names into a log call means the value - not a
# count, not a set of keys - is being written out.
DANGEROUS = re.compile(
    r"logging\.[a-z]+\(\s*f[\"'][^\"']*\{\s*(payload|body|data|message|text)\s*\}"
)


def _python_sources():
    return [p for p in APP.rglob("*.py") if "__pycache__" not in str(p)]


def test_no_webhook_payload_is_logged_verbatim():
    offenders = []
    for path in _python_sources():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if DANGEROUS.search(line):
                offenders.append(f"{path.relative_to(APP.parent)}:{lineno}")

    assert not offenders, (
        "Inbound payloads logged verbatim at: "
        + ", ".join(offenders)
        + ". Log a count, a set of keys, or a hashed identifier instead."
    )


def test_the_two_known_offenders_stay_fixed():
    views = (APP / "views.py").read_text(encoding="utf-8", errors="ignore")

    assert 'f"request body: {body}"' not in views


def test_database_phone_filter_is_absent_from_http_request_logs(monkeypatch, caplog):
    from app.config import configure_logging

    # Keep pytest's capture handler while exercising the real HTTPX request logger.
    monkeypatch.setattr(logging, "basicConfig", lambda **_: None)
    with caplog.at_level(logging.INFO, logger="httpx"):
        configure_logging()
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
            client.get("https://db.invalid/conversations", params={"customer_phone": "eq.private-recipient"})
    assert "private-recipient" not in caplog.text
