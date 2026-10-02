"""Cloudflare Turnstile bot protection for the public, unauthenticated forms.

Turnstile is the one Cloudflare product this deployment can actually use: the
app serves from a *.fly.dev hostname with no custom domain, so nothing is
proxied through Cloudflare's edge. Turnstile does not need to be -- it is a
widget the browser loads plus a server-to-server verification call, and it
works from any origin.

THE SWITCH IS OFF AND IS RE-READ PER REQUEST. Same reasoning as
app/services/ai_gateway.py: sign-in, sign-up, password reset and invitation
acceptance are the four doors into the product, so the control that guards them
must be revocable by changing a secret, never by shipping a deploy. is_enabled()
therefore touches the environment on every call and is never cached.

IT ALSO REFUSES TO TURN ITSELF ON HALFWAY. Enabling needs the flag *and* both
keys. The secret key is what makes verification possible at all; the site key is
what lets the browser mint a token in the first place. A deployment holding the
secret but not the site key would reject every human on the site while accepting
nobody -- a self-inflicted outage on the login page -- so a missing key reads as
"off" rather than as "on and broken".

WHEN IT IS ON IT FAILS CLOSED, INCLUDING ON A CLOUDFLARE OUTAGE. A missing,
blank, replayed or rejected token is refused (403), and so is a siteverify call
that times out, refuses the connection or answers with anything but a parseable
200 (503). Failing open on the unreachable case would hand any attacker who can
degrade that one call a switch that silently removes the protection, which makes
the control decoration. The operator's escape hatch is the flag above: clearing
TURNSTILE_ENABLED restores the old behaviour on the very next request.

remoteip is deliberately NOT sent. Cloudflare treats it as an assertion to
match, and this app sits behind a proxy whose hop count is configurable
(TRUSTED_PROXY_HOPS). One wrong hop count would turn every verification into a
failure -- a total lockout caused by an optional field that buys nothing here.
"""

import logging
import os
from functools import wraps

import requests
from flask import jsonify, request

logger = logging.getLogger(__name__)

#: Cloudflare's server-side verification endpoint.
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

#: The field the widget writes its token into, and therefore the JSON key the
#: browser sends. Keeping Cloudflare's own name means the hidden input a plain
#: HTML form would post and this JSON key are the same string.
TOKEN_FIELD = "cf-turnstile-response"

#: A challenge is solved in seconds; anything slower than this is an outage, and
#: waiting longer only holds a gunicorn worker open during one.
VERIFY_TIMEOUT_SECONDS = 5

_TRUTHY = ("1", "true", "yes", "on")


def _secret_key() -> str:
    """Server-side key. Never logged, never sent to a browser."""
    return os.getenv("TURNSTILE_SECRET_KEY", "").strip()


def site_key() -> str:
    """Public key the widget is rendered with. Safe to publish."""
    return os.getenv("TURNSTILE_SITE_KEY", "").strip()


def is_enabled() -> bool:
    """Whether the guarded endpoints require a solved challenge.

    Read from the environment on every call, never cached: an operator must be
    able to switch Turnstile off without waiting for a deploy.
    """
    if os.getenv("TURNSTILE_ENABLED", "").strip().lower() not in _TRUTHY:
        return False
    return bool(_secret_key() and site_key())


def _submitted_token() -> str:
    """The token from the request body, or "" when there is not a usable one.

    silent=True keeps the guard invisible to a malformed or non-JSON body: the
    endpoint's own request.get_json() still fails exactly the way it does today.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return ""
    token = body.get(TOKEN_FIELD)
    if not isinstance(token, str):
        return ""
    return token.strip()


def _verified(token: str) -> bool:
    """Ask Cloudflare whether this token is a genuine, unused solution.

    Raises TurnstileUnavailable when the answer cannot be obtained at all, which
    the caller turns into a 503 rather than a pass.
    """
    try:
        response = requests.post(
            SITEVERIFY_URL,
            data={"secret": _secret_key(), "response": token},
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise TurnstileUnavailable(f"siteverify returned HTTP {response.status_code}")
        payload = response.json()
    except TurnstileUnavailable:
        raise
    except (requests.RequestException, ValueError) as exc:
        raise TurnstileUnavailable(type(exc).__name__) from exc

    if isinstance(payload, dict) and payload.get("success") is True:
        return True

    # Cloudflare's error codes name the failure kind ("timeout-or-duplicate",
    # "invalid-input-response"); they carry neither the secret nor the token.
    codes = payload.get("error-codes") if isinstance(payload, dict) else None
    logger.warning("Turnstile challenge rejected: %s", codes or "unspecified")
    return False


class TurnstileUnavailable(RuntimeError):
    """Cloudflare could not be asked, so the request cannot be trusted."""


def _rejection():
    """The response that stops a request, or None to let it through."""
    if not is_enabled():
        return None

    token = _submitted_token()
    if not token:
        return jsonify({
            "status": "error",
            "code": "turnstile_required",
            "message": "Please complete the security check and try again.",
        }), 403

    try:
        if _verified(token):
            return None
    except TurnstileUnavailable as exc:
        logger.error("Turnstile verification unavailable: %s", exc)
        return jsonify({
            "status": "error",
            "code": "turnstile_unavailable",
            "message": "The security check is temporarily unavailable. Please try again shortly.",
        }), 503

    return jsonify({
        "status": "error",
        "code": "turnstile_failed",
        "message": "Security check failed. Please try again.",
    }), 403


def require_turnstile(view):
    """Refuse the request unless it carries a solved Turnstile challenge.

    A no-op while Turnstile is off, so the decorated endpoints keep their exact
    current behaviour until an operator supplies the keys and flips the flag.
    """

    @wraps(view)
    def guarded(*args, **kwargs):
        rejection = _rejection()
        if rejection is not None:
            return rejection
        return view(*args, **kwargs)

    return guarded
