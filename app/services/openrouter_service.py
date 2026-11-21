import hashlib
import hmac
import os
import logging
import threading
import time

import requests
from dotenv import load_dotenv

from app.services import ai_gateway, openrouter_key_service

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
logging.info(f"OpenRouter key loaded: {bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY.strip())}")
#: Credit remaining on the platform key. This balance funds EVERY tenant on the
#: pooled plans, so when it empties every bot stops at once -- nothing in the
#: per-tenant MYR wallet protects against it. Polled by the scheduler.
#: Deliberately always direct, never through the AI Gateway: this is an account
#: fact, not an inference call, and a gateway that cached or rewrote it would
#: misreport the one balance every pooled tenant depends on.
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
#: Credit left on the whole account; needs the management key. The key above cannot show this
#: when it is uncapped: it then reports no limit however low the account runs.
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"

#: OpenRouter can act on a whole account, so the owner hears about a block at once,
#: but a burst must not exhaust the mailbox that sign-in mail also depends on.
MODERATION_ALERT_WINDOW_SECONDS = 15 * 60
#: A spent key stays spent until the month resets, so its reminder is daily.
KEY_LIMIT_ALERT_WINDOW_SECONDS = 24 * 60 * 60
# shortcut: per-process memory, correct while Fly runs one gunicorn worker; move to the DB if that changes.
_moderation_alert_sent_at = {}
_moderation_alert_lock = threading.Lock()
_MAX_REASONS = 5
_MAX_DETAIL_CHARACTERS = 80
#: Measured 2026-11-07: only these spent reasoning on a chat reply (283-403 tokens, cut to
#: 113-284 with the answer unchanged). Most paid models reject effort "none" with a 400.
_MINIMAL_REASONING_MODELS = frozenset({"google/gemini-3.8-flash", "google/gemini-3.1-pro-preview"})
#: How OpenRouter marks a refusal because the key spent its own cap. Its docs say to branch on this
#: field: the same 403 can also be a workspace or guardrail budget.
_KEY_LIMIT_SOURCE = "openrouter_key_limit"
#: Phase 5: a customer waits at most this long for one chat-reply attempt. post_chat_completion's
#: other callers (background and report work) keep their own, longer timeouts.
CHAT_REPLY_TIMEOUT_SECONDS = 20
_TROUBLE_REPLY = "Sorry, I'm having trouble replying right now."


class ModerationBlocked(RuntimeError):
    """OpenRouter refused the input on policy grounds.

    Deliberately never holds ``flagged_input``: that field quotes the customer, and this
    object reaches logs, email and the agent-action payload. The message doubles as the
    GEO adapters' ``provider_*`` error code.
    """

    def __init__(self, reasons=(), provider_name=None, model_slug=None):
        super().__init__("provider_moderation_block")
        self.reasons = list(reasons)
        self.provider_name = provider_name
        self.model_slug = model_slug


class KeyLimitReached(RuntimeError):
    """The key's monthly cap is spent. Stops the Clients on this key and nobody else."""

    def __init__(self):
        super().__init__("provider_key_limit")


def end_user_id(company_id, customer_id=None):
    """Stable pseudonym for OpenRouter's ``user`` field, so a block lands on one person.

    Without it, OpenRouter says provider blocks can affect the whole account. Keyed with
    the server secret because a plain hash of a phone number is reversed by hashing every
    phone number.
    """
    identity = f"openrouter-user:{company_id}:{customer_id or ''}".encode()
    return "omx_" + hmac.new(os.getenv("SECRET_KEY", "").encode(), identity, hashlib.sha256).hexdigest()[:32]


def _detail(value):
    return str(value)[:_MAX_DETAIL_CHARACTERS] if value else None


def _refusal_metadata(response):
    """What a refusal says about itself, or None. The OpenRouter docs disagree on whether a
    spent key is a 402 or a 403, so both are read.
    """
    if response.status_code not in (402, 403):
        return None
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return None
    metadata = error.get("metadata") if isinstance(error, dict) else None
    return metadata if isinstance(metadata, dict) else None


def _key_limit_reached(response):
    metadata = _refusal_metadata(response)
    return metadata is not None and metadata.get("limit_source") == _KEY_LIMIT_SOURCE


def _moderation_block(response):
    """The block a 403 describes, or None: a 403 can also be a key limit or a permission error."""
    metadata = _refusal_metadata(response)
    if metadata is None or not {"reasons", "flagged_input"} & metadata.keys():
        return None
    reasons = metadata.get("reasons")
    return ModerationBlocked(
        reasons=[_detail(reason) for reason in reasons if reason][:_MAX_REASONS] if isinstance(reasons, list) else [],
        provider_name=_detail(metadata.get("provider_name")),
        model_slug=_detail(metadata.get("model_slug")),
    )


def _in_background(work):
    threading.Thread(target=work, name="moderation-alert", daemon=True).start()


def _claim_owner_alert(marker, window_seconds):
    with _moderation_alert_lock:
        now = time.monotonic()
        last = _moderation_alert_sent_at.get(marker)
        if last is not None and now - last < window_seconds:
            return False
        _moderation_alert_sent_at[marker] = now
        return True


def _alert_owner_once(marker, send, window_seconds=MODERATION_ALERT_WINDOW_SECONDS):
    """Email the owner once per window. A failed send frees the window, so the next one tries again."""
    if not _claim_owner_alert(marker, window_seconds):
        return

    def notify():
        if not send():
            with _moderation_alert_lock:
                _moderation_alert_sent_at.pop(marker, None)

    # SMTP can take seconds; the customer's reply must not wait on it.
    _in_background(notify)


def _report_moderation_block(block, company_id):
    # ERROR reaches Sentry for every block; the email is limited per Client per window.
    logging.error(
        "OpenRouter moderation block: company_id=%s provider=%s model=%s reasons=%s",
        company_id, block.provider_name, block.model_slug, block.reasons,
    )

    def send():
        from app.services.email_service import send_moderation_alert_email
        return send_moderation_alert_email(company_id=company_id, reasons=block.reasons,
                                           provider_name=block.provider_name, model_slug=block.model_slug)

    _alert_owner_once(company_id, send)


def _report_key_limit(api_key, company_id):
    # ERROR reaches Sentry every time. The email is limited per key, not per Client, because
    # every Client on a spent key hits it at once.
    logging.error("OpenRouter key limit reached: company_id=%s", company_id)

    def send():
        from app.services.email_service import send_openrouter_key_alert_email
        return send_openrouter_key_alert_email(
            label=f"the key used by company {company_id}",
            problem="has spent its monthly cap, so chats from the Clients on it are going to staff.",
        )

    _alert_owner_once(hashlib.sha256(api_key.encode()).hexdigest(), send, KEY_LIMIT_ALERT_WINDOW_SECONDS)


def post_chat_completion(body, *, api_key, company_id=None, customer_id=None, timeout=60,
                         referer="http://localhost:8000", title="Omnexa System"):
    """The only route to OpenRouter (pinned by test_openrouter_account_protection).

    Returns the raw response so callers keep their own error handling. Raises
    ModerationBlocked, after reporting it, when OpenRouter refused the input, and
    KeyLimitReached, after reporting it, when the key has spent its monthly cap.
    """
    api_key = openrouter_key_service.key_for_company(company_id, api_key)
    response = requests.post(
        ai_gateway.openrouter_chat_completions_url(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": referer,
            "X-OpenRouter-Title": title,
        },
        json={**body, "user": end_user_id(company_id, customer_id)},
        timeout=ai_gateway.publish_test_http_timeout(timeout),
    )
    block = _moderation_block(response)
    if block is not None:
        _report_moderation_block(block, company_id)
        raise block
    if _key_limit_reached(response):
        _report_key_limit(api_key, company_id)
        raise KeyLimitReached()
    return response


def _retryable(error):
    """A timeout, a 5xx or a 429 may pass on another model; any other failure would fail the same way."""
    if isinstance(error, requests.exceptions.Timeout):
        return True
    status = getattr(getattr(error, "response", None), "status_code", None)
    return (isinstance(error, requests.exceptions.HTTPError) and isinstance(status, int)
            and (status == 429 or status >= 500))


def _chat_attempt(prompt, model, temperature, max_tokens, company_id, customer_id):
    """One chat-reply request to one model: (data, None), or (None, the error that stopped it)."""
    logging.info(f"[OpenRouter] _request using model: {model}")
    content = prompt
    if model.startswith("anthropic/") and os.getenv("ANTHROPIC_PROMPT_CACHE", "").strip().lower() != "off":
        prefix, header, tail = prompt.partition(ai_gateway.DYNAMIC_SECTION_HEADER)
        if header:
            content = [
                {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": header + tail},
            ]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if model in _MINIMAL_REASONING_MODELS:
        body["reasoning"] = {"effort": "minimal"}
    try:
        response = post_chat_completion(
            body,
            api_key=OPENROUTER_API_KEY,
            company_id=company_id,
            customer_id=customer_id,
            timeout=CHAT_REPLY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        # Billing records the model that answered, even when the response leaves it out.
        return {**data, "model": data.get("model") or model}, None
    except (ModerationBlocked, KeyLimitReached):
        raise
    except requests.exceptions.HTTPError as e:
        # Status only: a provider error body can quote the customer's message.
        logging.error("OpenRouter HTTP error %s", getattr(e.response, "status_code", "unknown"))
        return None, e
    except Exception as e:
        logging.error("OpenRouter request failed (%s)", type(e).__name__)
        return None, e


def _request(prompt, model="google/gemini-3.5-flash", temperature=0.7,
             max_tokens=ai_gateway.MAX_CHAT_REPLY_TOKENS, company_id=None, customer_id=None,
             fallback_model=None):
    """Customer chat-reply request returning (success, data_dict_or_error_text).

    fallback_model is the caller's decision, never made here: after a timeout, a 5xx or a 429 the
    reply is tried once more, on that one model. ModerationBlocked and KeyLimitReached always raise
    at once: another model would only re-send refused text or spend a capped key.
    """
    if not OPENROUTER_API_KEY:
        logging.error("OPENROUTER_API_KEY is missing.")
        return False, _TROUBLE_REPLY
    data, error = _chat_attempt(prompt, model, temperature, max_tokens, company_id, customer_id)
    if data is None and fallback_model and _retryable(error):
        logging.warning("[OpenRouter] chat reply failed (%s); trying the same-tier fallback model once",
                        type(error).__name__)
        data, error = _chat_attempt(prompt, fallback_model, temperature, max_tokens, company_id, customer_id)
    return (True, data) if data is not None else (False, _TROUBLE_REPLY)


def _account_credit(data):
    """``GET /api/v1/credits`` in the shape of ``GET /api/v1/key``, so the balance job reads both."""
    try:
        return {
            "limit": data["total_credits"],
            "usage": data["total_usage"],
            "limit_remaining": float(data["total_credits"]) - float(data["total_usage"]),
        }
    except (KeyError, TypeError, ValueError):
        logging.warning("OpenRouter credit response was not numeric.")
        return None


def get_key_status(timeout: int = 10) -> dict | None:
    """Return OpenRouter's own view of the credit left.

    With the management key this is the whole account, which every Client key
    spends from. Without it, it is the parsed ``data`` object from
    ``GET /api/v1/key``. Either way the result carries
    ``limit_remaining`` (credits left), ``limit`` (the cap, or ``None`` when the
    key is uncapped) and ``usage``. Returns ``None`` when the balance could not
    be read at all, which the caller must treat as "unknown", never as "empty":
    alerting on a network blip would train the operator to ignore the alert.

    Never raises, and never logs the key or the response body -- a balance
    endpoint's response is account-identifying.
    """
    management_key = os.getenv("OPENROUTER_MANAGEMENT_API_KEY", "").strip()
    if not management_key and not OPENROUTER_API_KEY:
        logging.error("OPENROUTER_API_KEY is missing; cannot read provider balance.")
        return None

    try:
        response = requests.get(
            OPENROUTER_CREDITS_URL if management_key else OPENROUTER_KEY_URL,
            headers={"Authorization": f"Bearer {management_key or OPENROUTER_API_KEY}"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        logging.warning("OpenRouter balance request failed (%s).", type(e).__name__)
        return None

    if response.status_code != 200:
        logging.warning("OpenRouter balance request returned %s.", response.status_code)
        return None

    try:
        payload = response.json()
    except ValueError:
        logging.warning("OpenRouter balance response was not JSON.")
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        logging.warning("OpenRouter balance response had no data object.")
        return None

    return _account_credit(data) if management_key else data
