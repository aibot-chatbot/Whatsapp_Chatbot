"""Which OpenRouter key each Client uses.

Clients share keys in small groups, so a blocked or spent key stops one group and not the whole
platform. The key is always chosen here from the company_id, never from a request, and keys are
stored encrypted with a master key that lives only in Fly secrets.

Every failure logs the error type only: an error from OpenRouter or the database can quote a key.
"""
import logging
import math
import os
import secrets
import threading
import time

import requests
from cryptography.fernet import Fernet, MultiFernet

OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/keys"
DEFAULT_MAX_CLIENTS_PER_KEY = 20
KEY_API_TIMEOUT_SECONDS = 10
#: OpenRouter returns keys 100 at a time.
PAGE_SIZE = 100
#: Room above what the Clients on a key can pay for, because they renew on different days.
CAP_MARGIN = 1.5
# A failed lookup uses the shared key and tries again after this long, so an expired management
# key cannot add a slow call to every reply.
FALLBACK_RETRY_SECONDS = 60
_FOREVER = float("inf")

# shortcut: per-process cache and lock, correct while Fly runs one gunicorn worker; move to the DB
# if that changes. Moving a Client to another key (plan step E6) must clear its cache entry.
_cache = {}
_closed_to_new_clients = frozenset()
_lock = threading.Lock()


def _repository():
    # Imported here so a deployment with the feature off never touches these tables.
    from app.database import openrouter_key_repository
    return openrouter_key_repository


def is_enabled():
    return os.getenv("OPENROUTER_CLIENT_KEYS_ENABLED", "").strip().lower() == "true"


def management_headers():
    return {"Authorization": f"Bearer {os.environ['OPENROUTER_MANAGEMENT_API_KEY']}"}


def _fernet():
    # Comma-separated, newest first, so the master key can change without losing stored keys.
    return MultiFernet([Fernet(key.strip().encode()) for key in os.environ["AI_KEY_ENCRYPTION_KEY"].split(",")])


def _max_clients_per_key():
    try:
        return max(1, int(os.getenv("MAX_CLIENTS_PER_KEY", DEFAULT_MAX_CLIENTS_PER_KEY)))
    except ValueError:
        logging.warning("MAX_CLIENTS_PER_KEY is not a number; using %s.", DEFAULT_MAX_CLIENTS_PER_KEY)
        return DEFAULT_MAX_CLIENTS_PER_KEY


def _monthly_limit_usd():
    """The lowest cap a key can have. Required: a key must never exist without a cap."""
    limit = float(os.environ["OPENROUTER_KEY_MONTHLY_LIMIT_USD"])
    if not 0 < limit < _FOREVER:
        raise ValueError("OPENROUTER_KEY_MONTHLY_LIMIT_USD must be a positive number.")
    return limit


def _create_key():
    # Before calling OpenRouter: a key that cannot be stored must not be created.
    fernet = _fernet()
    label = f"omnexa-pool-{secrets.token_hex(3)}"
    response = requests.post(
        OPENROUTER_KEYS_URL,
        headers=management_headers(),
        json={"name": label, "limit": _monthly_limit_usd(), "limit_reset": "monthly"},
        timeout=KEY_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    return _repository().create_key(body["data"]["hash"], fernet.encrypt(body["key"].encode()).decode(), label)


def list_openrouter_keys():
    """Every key on the account, with its usage."""
    keys, offset = [], 0
    while True:
        response = requests.get(
            OPENROUTER_KEYS_URL,
            headers=management_headers(),
            # Disabled keys are hidden by default, and the check job exists to find those.
            params={"include_disabled": "true", "offset": offset},
            timeout=KEY_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        page = response.json()["data"]
        keys = [*keys, *page]
        if len(page) < PAGE_SIZE:
            return keys
        offset += PAGE_SIZE


def _update_key(key, fields):
    response = requests.patch(
        f"{OPENROUTER_KEYS_URL}/{key['key_hash']}",
        headers=management_headers(),
        json=fields,
        timeout=KEY_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def set_key_cap(key, cap_usd):
    _update_key(key, {"limit": cap_usd})


def target_cap_usd(month_credit_micro_myr):
    """The monthly cap a key needs: what its Clients can pay for this month, plus a margin.

    Built only from the app's own credit records, never from OpenRouter usage. Spending moves
    money from credit left to charged, so the total does not grow with it, and a runaway that
    bypasses billing adds nothing. The cap therefore stops a key only when real spending passes
    what was billed by the margin, which is the case the second stop exists for.
    """
    from app.services.ai_credit_service import get_ai_usd_to_myr_rate_micro_myr_per_usd

    rate = get_ai_usd_to_myr_rate_micro_myr_per_usd()
    if rate <= 0:
        raise ValueError("The USD to MYR rate is not configured.")
    return max(_monthly_limit_usd(), math.ceil(month_credit_micro_myr * CAP_MARGIN / rate))


def close_to_new_clients(key_ids):
    """Set by the check job, so a new Client never starts on a key about to run out."""
    global _closed_to_new_clients
    _closed_to_new_clients = frozenset(key_ids)


def _key_with_room():
    limit = _max_clients_per_key()
    keys = _repository().list_keys("active")
    return next((key for key in keys if key["clients"] < limit and key["id"] not in _closed_to_new_clients), None)


def _assigned_key(company_id):
    """The Client's key, whatever its status: a disabled key is never swapped for the shared one,
    so a block cannot spread to the shared key. Plan step E6 moves Clients to a spare key.
    """
    repository = _repository()
    key = repository.get_company_key(company_id)
    if key is not None:
        return key
    repository.assign_company(company_id, (_key_with_room() or _create_key())["id"])
    return repository.get_company_key(company_id)


def _cached_key(company_id):
    key, usable_until = _cache.get(company_id, (None, 0))
    return key if time.monotonic() < usable_until else None


def key_for_company(company_id, shared_key):
    """The key for this Client's AI calls, or shared_key when it has none it can use."""
    if company_id is None or not is_enabled():
        return shared_key
    key = _cached_key(company_id)
    if key:
        return key
    with _lock:
        # Another thread may have finished this while this one waited for the lock.
        key = _cached_key(company_id)
        if key:
            return key
        try:
            entry = (_fernet().decrypt(_assigned_key(company_id)["encrypted_key"].encode()).decode(), _FOREVER)
        except Exception as error:
            logging.error("Client OpenRouter key unavailable for company_id=%s (%s)",
                          company_id, type(error).__name__)
            entry = (shared_key, time.monotonic() + FALLBACK_RETRY_SECONDS)
        _cache[company_id] = entry
    return entry[0]


def retire_empty_keys():
    """Disable keys whose last Client has left.

    A suspended Client stays assigned, so suspending one never cuts off the others on its key.
    A new key is created and assigned under the same lock, so a key waiting for its first Client
    is never seen here. Recording the change first means no Client can join a key on its way out,
    and a failed call to OpenRouter leaves only a capped key that nothing uses.
    """
    repository = _repository()
    with _lock:
        empty = [key for key in repository.list_keys("active") if key["clients"] == 0]
        for key in empty:
            repository.mark_disabled(key["id"])
    for key in empty:
        try:
            _update_key(key, {"disabled": True})
        except requests.RequestException as error:
            logging.error("Could not disable empty OpenRouter key %s (%s)", key["label"], type(error).__name__)
