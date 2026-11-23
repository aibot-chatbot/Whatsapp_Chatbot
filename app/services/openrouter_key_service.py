"""Which OpenRouter key each Client uses.

Clients share keys in small groups, so a blocked or spent key stops one group and not the whole
platform. The key is always chosen here from the company_id, never from a request, and keys are
stored encrypted with a master key that lives only in Fly secrets.

Every failure logs the error type only: an error from OpenRouter or the database can quote a key.
"""
import logging
import math
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

import requests
from app.utils.provider_secrets import provider_fernet as _fernet
from postgrest.exceptions import APIError

OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/keys"
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
# if that changes. Moving a Client to another key (move_clients_off) clears its cache entry, so
# moves run only in the check job, inside the web process that holds this cache.
_cache = {}
_closed_to_new_clients = frozenset()
_lock = threading.Lock()
_MASKED_LABEL = re.compile(r"sk-or-v1-[0-9a-f]{3}\.\.\.[0-9a-f]{4}")


def _masked_label(value):
    return value if isinstance(value, str) and _MASKED_LABEL.fullmatch(value) else None


def _usd(value):
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        return value
    return None


def list_admin_keys():
    rows = _repository().list_admin_keys()
    try:
        by_hash = {item["hash"]: item for item in list_openrouter_keys()}
    except Exception as error:
        logging.warning("OpenRouter usage unavailable (%s)", type(error).__name__)
        by_hash = {}
    result = []
    for row in rows:
        remote = by_hash.get(row["key_hash"], {})
        result.append({
            **{k: row[k] for k in ("id", "status", "disabled_reason", "culprit_company_id", "clients", "max_clients")},
            "label": _masked_label(remote.get("label")) or _masked_label(row["label"]),
            "usage": _usd(remote.get("usage")), "limit": _usd(remote.get("limit")),
        })
    return {"keys": result}


def get_admin_key_companies(key_id):
    from app.services.platform_admin_service import PlatformAdminServiceError
    details = _repository().get_key_companies(key_id)
    if details is None:
        raise PlatformAdminServiceError(404, "key_not_found", "The selected key no longer exists.")
    return details


def set_admin_key_max_clients(key_id, payload, actor_id):
    from app.services.platform_admin_service import PlatformAdminServiceError
    value = payload.get("max_clients") if isinstance(payload, dict) else None
    if type(value) is not int or not 1 <= value <= 20:
        raise PlatformAdminServiceError(400, "invalid_client_limit", "Enter a whole number from 1 to 20.")
    repo = _repository()
    # Serialize the limit change with this worker's assignment and replacement operations.
    with _lock:
        clients = len(repo.list_key_companies(key_id))
        try:
            previous = repo.set_key_max_clients(key_id, value, actor_id)
        except APIError as error:
            if error.code == "PT404":
                raise PlatformAdminServiceError(404, "key_not_found", "The selected key no longer exists.") from None
            if error.code == "PT409":
                raise PlatformAdminServiceError(409, "key_unavailable", "Key is unavailable.") from None
            if error.code == "PT403":
                raise PlatformAdminServiceError(403, "access_denied", "Super Admin access is required.") from None
            raise
    return {"id": key_id, "max_clients": value, "previous_max_clients": previous, "clients": clients}


def _reject_key():
    from app.services.platform_admin_service import PlatformAdminServiceError
    raise PlatformAdminServiceError(400, "invalid_replacement_key",
                                    "Enter an active, capped Client key from this OpenRouter account.")


def _owned_key_hash(pasted):
    label = pasted[:12] + "..." + pasted[-4:]
    response = requests.get("https://openrouter.ai/api/v1/key",
                            headers={"Authorization": "Bearer " + pasted},
                            timeout=KEY_API_TIMEOUT_SECONDS, allow_redirects=False)
    if response.status_code in (401, 403):
        _reject_key()
    response.raise_for_status()
    if response.status_code != 200:
        _reject_key()
    own = response.json()["data"]
    if own.get("label") != label or own.get("is_management_key", own.get("is_provisioning_key")) is not False:
        _reject_key()
    if own.get("is_provisioning_key") is True or _usd(own.get("limit")) is None:
        _reject_key()
    matches = [key for key in list_openrouter_keys() if key.get("label") == label]
    if len(matches) != 1:
        _reject_key()
    match = matches[0]
    if match.get("disabled") is not False or _usd(match.get("limit")) is None:
        _reject_key()
    for field in ("workspace_id", "creator_user_id"):
        identity = own.get(field)
        if not isinstance(identity, str) or not identity.strip() or match.get(field) != identity:
            _reject_key()
    for record in (own, match):
        expiry = record.get("expires_at")
        if expiry is not None:
            try:
                expires = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                _reject_key()
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                _reject_key()
    key_hash = match.get("hash")
    if (not isinstance(key_hash, str) or "sk-or-" in key_hash.lower()
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key_hash)):
        _reject_key()
    return key_hash, label


def replace_admin_key(key_id, payload, actor_id):
    from app.services.platform_admin_service import PlatformAdminServiceError
    if not isinstance(payload, dict) or not isinstance(payload.get("api_key"), str):
        _reject_key()
    pasted = payload["api_key"]
    if not re.fullmatch(r"sk-or-v1-[0-9a-f]{64}", pasted):
        _reject_key()
    reason = payload.get("reason")
    if (not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 240
            or not reason.strip().isprintable() or "sk-or-" in reason.lower()):
        raise PlatformAdminServiceError(400, "invalid_replacement_reason",
                                        "Enter a short reason without credentials.")
    repo = _repository()
    key_hash, label = _owned_key_hash(pasted)
    with _lock:
        old = repo.get_replacement_source(key_id)
        if old is None:
            raise PlatformAdminServiceError(404, "key_not_found", "The selected key no longer exists.")
        if old.get("disabled_reason") == "manual_replacement" or repo.has_key_hash(key_hash):
            raise PlatformAdminServiceError(409, "key_already_replaced", "This key has already been used.")
        encrypted = _fernet().encrypt(pasted.encode()).decode()
        month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cap = target_cap_usd(repo.month_credit_micro_myr(key_id, month.isoformat()))
        set_key_cap({"key_hash": key_hash}, cap, monthly=True)
        try:
            moved = repo.replace_key(key_id, key_hash, encrypted, label, actor_id, reason.strip())
        except Exception:
            # A lost database response can follow a committed move.
            _cache.clear()
            raise
        for company_id in moved:
            _cache.pop(company_id, None)
    try:
        disable_on_openrouter(old)
        disabled = True
    except Exception as error:
        logging.warning("Could not disable replaced OpenRouter key (%s)", type(error).__name__)
        disabled = False
    return {"label": label, "moved_count": len(moved), "old_key_disabled": disabled}


def _repository():
    # Imported here so a deployment with the feature off never touches these tables.
    from app.database import openrouter_key_repository
    return openrouter_key_repository


def is_enabled():
    return os.getenv("OPENROUTER_CLIENT_KEYS_ENABLED", "").strip().lower() == "true"


def management_headers():
    return {"Authorization": f"Bearer {os.environ['OPENROUTER_MANAGEMENT_API_KEY']}"}


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
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code != 200:
            raise requests.HTTPError("Unexpected OpenRouter management response.")
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
        allow_redirects=False,
    )
    response.raise_for_status()
    if response.status_code != 200:
        raise requests.HTTPError("OpenRouter did not confirm the update.")


def set_key_cap(key, cap_usd, *, monthly=False):
    fields = {"limit": cap_usd}
    if monthly:
        fields["limit_reset"] = "monthly"
    _update_key(key, fields)


def disable_on_openrouter(key):
    _update_key(key, {"disabled": True})


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
    keys = _repository().list_keys("active")
    return next((key for key in keys
                 if key["clients"] < key["max_clients"] and key["id"] not in _closed_to_new_clients), None)


def _assigned_key(company_id):
    """The Client's key, whatever its status: a disabled key is never swapped for the shared one,
    so a block cannot spread to the shared key. move_clients_off moves Clients to a spare key.
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


def disable_key_because_of(company_id):
    """Operator action: stop the key this Client is on, because of this Client. No route calls it.

    Records the decision only. The next key check (every 15 minutes, in the web process that holds
    the key cache) moves every other Client on the key to one with room, and only then disables the
    key on OpenRouter, so they never lose AI replies. This Client stays on the key and keeps it
    until that check runs. Needs data/082: until it is applied this raises and changes nothing.

    Owner decision (2026-11-14): whoever calls this also suspends the same Client in the Super
    Admin portal at the same time, so it stops at once while the others move within 15 minutes.
    """
    if not is_enabled():
        raise RuntimeError("OPENROUTER_CLIENT_KEYS_ENABLED is off, so every Client uses the shared key.")
    repository = _repository()
    key = repository.get_company_key(company_id)
    if key is None:
        raise ValueError(f"company_id={company_id} has no OpenRouter key.")
    current = repository.list_disable_reasons().get(key["id"]) or {}
    if current.get("disabled_reason") == "ours" and current.get("culprit_company_id") != company_id:
        # One culprit per key: blaming a second one would move the first off the dead key.
        raise ValueError(f"OpenRouter key {key['label']} is already disabled because of another Client.")
    repository.mark_disabled(key["id"], "ours", company_id)
    return key["label"]


def move_clients_off(key, culprit_company_id):
    """Move every Client on this key except culprit_company_id to a key with room, or a new one.

    The culprit is never moved, so with no culprit named nobody moves. Each moved Client's cached
    key is dropped, so its next reply reads the new assignment. Returns how many moved.
    """
    if culprit_company_id is None:
        raise ValueError("A key disabled because of one Client must name that Client.")
    repository = _repository()
    moved = 0
    with _lock:
        for company_id in repository.list_key_companies(key["id"]):
            if company_id == culprit_company_id:
                continue
            repository.move_company(company_id, key["id"], (_key_with_room() or _create_key())["id"])
            _cache.pop(company_id, None)
            moved += 1
    return moved


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
