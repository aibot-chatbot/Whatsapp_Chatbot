import hashlib
import hmac
import os
import logging
import threading
import time

import requests
from dotenv import load_dotenv

from app.services import ai_gateway

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

#: OpenRouter can act on a whole account, so the owner hears about a block at once,
#: but a burst must not exhaust the mailbox that sign-in mail also depends on.
MODERATION_ALERT_WINDOW_SECONDS = 15 * 60
# shortcut: per-process memory, correct while Fly runs one gunicorn worker; move to the DB if that changes.
_moderation_alert_sent_at = {}
_moderation_alert_lock = threading.Lock()
_MAX_REASONS = 5
_MAX_DETAIL_CHARACTERS = 80
#: Measured 2026-11-07: only these spent reasoning on a chat reply (283-403 tokens, cut to
#: 113-284 with the answer unchanged). Most paid models reject effort "none" with a 400.
_MINIMAL_REASONING_MODELS = frozenset({"google/gemini-3.8-flash", "google/gemini-3.1-pro-preview"})


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


def _moderation_block(response):
    """The block a 403 describes, or None: a 403 can also be a key limit or a permission error."""
    if response.status_code != 403:
        return None
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return None
    metadata = error.get("metadata") if isinstance(error, dict) else None
    if not isinstance(metadata, dict) or not {"reasons", "flagged_input"} & metadata.keys():
        return None
    reasons = metadata.get("reasons")
    return ModerationBlocked(
        reasons=[_detail(reason) for reason in reasons if reason][:_MAX_REASONS] if isinstance(reasons, list) else [],
        provider_name=_detail(metadata.get("provider_name")),
        model_slug=_detail(metadata.get("model_slug")),
    )


def _in_background(work):
    threading.Thread(target=work, name="moderation-alert", daemon=True).start()


def _claim_moderation_alert(company_id):
    with _moderation_alert_lock:
        now = time.monotonic()
        last = _moderation_alert_sent_at.get(company_id)
        if last is not None and now - last < MODERATION_ALERT_WINDOW_SECONDS:
            return False
        _moderation_alert_sent_at[company_id] = now
        return True


def _report_moderation_block(block, company_id):
    # ERROR reaches Sentry for every block; the email is limited per Client per window.
    logging.error(
        "OpenRouter moderation block: company_id=%s provider=%s model=%s reasons=%s",
        company_id, block.provider_name, block.model_slug, block.reasons,
    )
    if not _claim_moderation_alert(company_id):
        return

    def notify():
        from app.services.email_service import send_moderation_alert_email
        sent = send_moderation_alert_email(company_id=company_id, reasons=block.reasons,
                                           provider_name=block.provider_name, model_slug=block.model_slug)
        if not sent:
            # Nothing was delivered, so the next block must try again.
            with _moderation_alert_lock:
                _moderation_alert_sent_at.pop(company_id, None)

    # SMTP can take seconds; the customer's reply must not wait on it.
    _in_background(notify)


def post_chat_completion(body, *, api_key, company_id=None, customer_id=None, timeout=60,
                         referer="http://localhost:8000", title="Omnexa System"):
    """The only route to OpenRouter (pinned by test_openrouter_account_protection).

    Returns the raw response so callers keep their own error handling. Raises
    ModerationBlocked, after reporting it, when OpenRouter refused the input.
    """
    response = requests.post(
        ai_gateway.openrouter_chat_completions_url(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": referer,
            "X-OpenRouter-Title": title,
        },
        json={**body, "user": end_user_id(company_id, customer_id)},
        timeout=timeout,
    )
    block = _moderation_block(response)
    if block is not None:
        _report_moderation_block(block, company_id)
        raise block
    return response


def _request(prompt, model="google/gemini-3.5-flash", temperature=0.7,
             max_tokens=ai_gateway.MAX_CHAT_REPLY_TOKENS, company_id=None, customer_id=None):
    """Raw OpenRouter API request returning (success, data_dict_or_error_text)."""
    try:
        if not OPENROUTER_API_KEY:
            logging.error("OPENROUTER_API_KEY is missing.")
            return False, "Sorry, I'm having trouble replying right now."
        logging.info(f"[OpenRouter] _request using model: {model}")
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if model in _MINIMAL_REASONING_MODELS:
            body["reasoning"] = {"effort": "minimal"}
        response = post_chat_completion(
            body,
            api_key=OPENROUTER_API_KEY,
            company_id=company_id,
            customer_id=customer_id,
        )
        response.raise_for_status()
        return True, response.json()
    except ModerationBlocked:
        raise
    except requests.exceptions.HTTPError as e:
        # Status only: a provider error body can quote the customer's message.
        logging.error("OpenRouter HTTP error %s", getattr(e.response, "status_code", "unknown"))
        return False, "Sorry, I'm having trouble replying right now."
    except Exception as e:
        logging.error("OpenRouter request failed (%s)", type(e).__name__)
        return False, "Sorry, I'm having trouble replying right now."


def get_key_status(timeout: int = 10) -> dict | None:
    """Return OpenRouter's own view of the platform key's credit.

    Returns the parsed ``data`` object from ``GET /api/v1/key`` -- notably
    ``limit_remaining`` (credits left), ``limit`` (the cap, or ``None`` when the
    key is uncapped) and ``usage``. Returns ``None`` when the balance could not
    be read at all, which the caller must treat as "unknown", never as "empty":
    alerting on a network blip would train the operator to ignore the alert.

    Never raises, and never logs the key or the response body -- a balance
    endpoint's response is account-identifying.
    """
    if not OPENROUTER_API_KEY:
        logging.error("OPENROUTER_API_KEY is missing; cannot read provider balance.")
        return None

    try:
        response = requests.get(
            OPENROUTER_KEY_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
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

    return data
