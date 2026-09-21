"""CHIP Collect hosted purchases and raw-body callback authentication."""

from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import requests
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class ChipConfigError(ValueError):
    """CHIP's server configuration is missing or unsafe."""


class ChipRequestRejectedError(RuntimeError):
    """CHIP definitively rejected purchase creation."""


class ChipAmbiguousError(RuntimeError):
    """A purchase may exist; reconcile before permitting another creation."""


class ChipAPIError(RuntimeError):
    """CHIP could not provide a valid authoritative response."""


@dataclass(frozen=True)
class ChipConfig:
    enabled: bool = False
    environment: str = "test"
    api_key: str = field(default="", repr=False)
    brand_id: str = ""
    redirect_url: str = ""
    webhook_url: str = ""
    live_enabled: bool = False
    callback_public_key: str = field(default="", repr=False)
    webhook_public_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "ChipConfig":
        environment = os.getenv("CHIP_ENV", "test").strip().lower()
        if environment not in {"test", "live"}:
            raise ChipConfigError("CHIP_ENV must be 'test' or 'live'")
        prefix = f"CHIP_{environment.upper()}"
        return cls(
            enabled=_env_bool("CHIP_ENABLED"),
            environment=environment,
            api_key=os.getenv(f"{prefix}_API_KEY", "").strip(),
            brand_id=(os.getenv(f"{prefix}_BRAND_ID") or os.getenv("CHIP_BRAND_ID", "")).strip(),
            redirect_url=os.getenv("CHIP_REDIRECT_URL", "").strip(),
            webhook_url=os.getenv("CHIP_WEBHOOK_URL", "").strip(),
            live_enabled=_env_bool("CHIP_LIVE_ENABLED"),
            callback_public_key=_public_key_env(prefix, "CALLBACK_PUBLIC_KEY"),
            webhook_public_key=_public_key_env(prefix, "WEBHOOK_PUBLIC_KEY"),
        )

    @property
    def is_test(self) -> bool:
        if self.environment not in {"test", "live"}:
            raise ChipConfigError("CHIP_ENV must be 'test' or 'live'")
        return self.environment == "test"

    @property
    def base_url(self) -> str:
        return "https://gate.chip-in.asia/api/v1"

    def validate_for_api(self) -> None:
        if self.enabled is not True:
            raise ChipConfigError("CHIP is not enabled")
        if not self.is_test and self.live_enabled is not True:
            raise ChipConfigError("CHIP live mode requires CHIP_LIVE_ENABLED=true")
        if not isinstance(self.api_key, str) or not re.fullmatch(r"[A-Za-z0-9_+=/.-]{8,2048}", self.api_key):
            raise ChipConfigError("The selected CHIP mode requires a valid API key")
        try:
            _uuid(self.brand_id, "brand ID")
        except ValueError:
            raise ChipConfigError("CHIP_BRAND_ID must be a UUID") from None

    def validate_for_checkout(self) -> None:
        self.validate_for_api()
        for value, name in ((self.redirect_url, "CHIP_REDIRECT_URL"), (self.webhook_url, "CHIP_WEBHOOK_URL")):
            if not _https_url(value):
                raise ChipConfigError(f"{name} must be an absolute HTTPS URL without credentials or fragments")
        if urlsplit(self.webhook_url).path.rstrip("/").endswith("/webhook"):
            # success_callback payloads are signed with the company-wide key, while the
            # /webhook endpoint requires a registered Webhook's own key. Pointing one at
            # the other rejects every delivery, so refuse before a customer pays.
            raise ChipConfigError("CHIP_WEBHOOK_URL is a success_callback URL and must not target /webhook")


def _env_bool(name: str) -> bool:
    value = os.getenv(name, "false").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ChipConfigError(f"{name} must be a boolean")


def _public_key_env(prefix: str, name: str) -> str:
    """Prefer the mode's own key: CHIP test and live are separate signing datasets."""
    value = os.getenv(f"{prefix}_{name}") or os.getenv(f"CHIP_{name}", "")
    return value.strip().replace("\\n", "\n")


def _https_url(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 500 or re.search(r"[\s\\<>\"']", value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme == "https" and parsed.hostname and parsed.port in {None, 443}
                    and parsed.username is None and parsed.password is None and not parsed.fragment)
    except ValueError:
        return False


def _uuid(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"CHIP {name} must be a UUID")
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise ValueError(f"CHIP {name} must be a UUID")


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or not 0 < value <= 9223372036854775807:
        raise ValueError(f"CHIP {name} must be a positive integer")
    return value


def _reference(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError("CHIP order reference is invalid")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError(f"CHIP {name} is invalid")
    return value.strip()


def validate_checkout_url(value: object) -> str:
    """Accept only the documented CHIP hosted-checkout origin."""
    if not _https_url(value) or urlsplit(value).hostname != "gate.chip-in.asia":
        raise ChipAmbiguousError("CHIP returned an unexpected checkout URL")
    return value


def create_purchase(
    config: ChipConfig,
    *,
    order_reference: str,
    amount_sen: int,
    description: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None = None,
    due: int | None = None,
) -> dict:
    """Create once. An ambiguous outcome must never trigger an automatic retry."""
    config.validate_for_checkout()
    _reference(order_reference)
    _positive_integer(amount_sen, "amount")
    email = _text(customer_email, "customer email", 254)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("CHIP customer email is invalid")
    client = {"email": email, "full_name": _text(customer_name, "customer name", 1000)}
    if customer_phone:
        client["phone"] = _text(customer_phone, "customer phone", 32)
    payload = {
        "brand_id": config.brand_id,
        "reference": order_reference,
        "client": client,
        "purchase": {"currency": "MYR", "products": [{"name": _text(description, "description", 256), "price": amount_sen}]},
        "success_redirect": config.redirect_url,
        "failure_redirect": config.redirect_url,
        "cancel_redirect": config.redirect_url,
        "success_callback": config.webhook_url,
        "send_receipt": False,
        "force_recurring": False,
        "skip_capture": False,
    }
    if due is not None:
        payload["due"] = _positive_integer(due, "due timestamp")
        payload["purchase"]["due_strict"] = True
    try:
        response = requests.post(
            f"{config.base_url}/purchases/", headers=_headers(config), json=payload,
            timeout=(5, 20), allow_redirects=False,
        )
    except requests.RequestException:
        # Raw request exceptions can retain the Authorization header and customer data.
        raise ChipAmbiguousError("CHIP purchase outcome is unknown") from None
    status = response.status_code
    if 400 <= status < 500 and status not in {408, 409, 425, 429}:
        raise ChipRequestRejectedError(f"CHIP rejected purchase creation (HTTP {status})")
    if status != 201:
        raise ChipAmbiguousError(f"CHIP purchase outcome is unknown (HTTP {status})")
    try:
        body = response.json()
        normalized = _validate_purchase(body, config)
        if normalized["order_reference"] != order_reference or normalized["amount_sen"] != amount_sen:
            raise ValueError("CHIP returned mismatched purchase details")
        if normalized["gateway_status"] != "created" or body.get("force_recurring") is not False or body.get("skip_capture") is not False:
            raise ValueError("CHIP returned an unexpected purchase configuration")
        checkout_url = validate_checkout_url(body.get("checkout_url"))
    except (ValueError, TypeError):
        raise ChipAmbiguousError("CHIP returned invalid or mismatched purchase details") from None
    return {
        "gateway_order_id": normalized["gateway_order_id"],
        "checkout_url": checkout_url,
        "gateway_status": normalized["gateway_status"],
        "brand_id": normalized["brand_id"],
        "is_test": normalized["is_test"],
    }


def _headers(config: ChipConfig) -> dict:
    return {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}


def _get_json(config: ChipConfig, path: str) -> object:
    config.validate_for_api()
    try:
        response = requests.get(f"{config.base_url}/{path}", headers=_headers(config), timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise ChipAPIError("CHIP lookup failed") from None
    if response.status_code != 200:
        raise ChipAPIError(f"CHIP lookup failed (HTTP {response.status_code})")
    try:
        return response.json()
    except (ValueError, TypeError):
        raise ChipAPIError("CHIP lookup returned invalid JSON") from None


def get_purchase(config: ChipConfig, purchase_id: str) -> dict:
    """Fetch authoritative state, bound to the configured brand and mode."""
    _uuid(purchase_id, "purchase ID")
    body = _get_json(config, f"purchases/{purchase_id}/")
    try:
        normalized = _validate_purchase(body, config)
        if normalized["gateway_order_id"] != purchase_id:
            raise ValueError("CHIP purchase ID did not match")
    except (ValueError, TypeError):
        raise ChipAPIError("CHIP lookup returned invalid or mismatched purchase details") from None
    return body


def _rsa_public_key(public_key: str) -> rsa.RSAPublicKey:
    if not isinstance(public_key, str) or len(public_key) > 16384:
        raise ValueError("Invalid CHIP public key")
    key = serialization.load_pem_public_key(public_key.encode("ascii"))
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise ValueError("CHIP public key must use RSA with at least 2048 bits")
    return key


_public_key_lock = Lock()


def get_public_key(config: ChipConfig) -> str:
    """Decode the company key used by success_callback, not a Webhook's own key."""
    with _public_key_lock:
        public_key = _cached_public_key(config, int(monotonic() // 300))
    if public_key is None:
        raise ChipAPIError("CHIP callback public key is unavailable")
    return public_key


@lru_cache(maxsize=4)
def _cached_public_key(config: ChipConfig, _cache_window: int) -> str | None:
    # Cache key failures too, so unsigned traffic cannot amplify a provider outage.
    # ponytail: one lock per worker; use configured public keys at higher throughput.
    try:
        public_key = _get_json(config, "public_key/")
        _rsa_public_key(public_key)
    except (ChipAPIError, ValueError, TypeError, UnicodeError, UnsupportedAlgorithm):
        return None
    return public_key


def verify_webhook_signature(raw_body: bytes, signature: str, public_key: str) -> bool:
    """Verify base64 RSA PKCS1v15/SHA256 over the unmodified HTTP request bytes."""
    if not isinstance(raw_body, bytes) or not isinstance(signature, str) or not signature or len(signature) > 16384:
        return False
    try:
        decoded = base64.b64decode(signature, validate=True)
        _rsa_public_key(public_key).verify(decoded, raw_body, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError, UnicodeError, binascii.Error, UnsupportedAlgorithm):
        return False
    return True


_STATUSES = {
    "created", "sent", "viewed", "error", "cancelled", "overdue", "expired", "blocked",
    "hold", "released", "pending_release", "pending_capture", "preauthorized", "paid",
    "pending_execute", "pending_charge", "cleared", "settled", "chargeback", "pending_refund", "refunded",
}


def normalize_purchase(purchase: dict) -> dict:
    """Normalize payment proof without retaining customer or card details."""
    if not isinstance(purchase, dict) or purchase.get("type") != "purchase":
        raise ValueError("CHIP response must be a purchase")
    purchase_id = _uuid(purchase.get("id"), "purchase ID")
    brand_id = _uuid(purchase.get("brand_id"), "brand ID")
    reference = _reference(purchase.get("reference"))
    status = purchase.get("status")
    if not isinstance(status, str) or status not in _STATUSES or type(purchase.get("is_test")) is not bool:
        raise ValueError("CHIP purchase status or mode is invalid")
    details = purchase.get("purchase")
    if not isinstance(details, dict) or details.get("currency") != "MYR":
        raise ValueError("CHIP purchase currency must be MYR")
    amount = _positive_integer(details.get("total"), "purchase total")
    paid = status in {"paid", "cleared", "settled"}
    paid_at = ""
    if paid:
        payment = purchase.get("payment")
        if not isinstance(payment, dict) or payment.get("currency") != "MYR" or payment.get("is_outgoing") is not False:
            raise ValueError("CHIP purchase has no valid incoming payment")
        if purchase.get("marked_as_paid") is not False or payment.get("payment_type") not in {"purchase", "purchase_charge"}:
            raise ValueError("CHIP purchase has no verified payment transaction")
        if _positive_integer(payment.get("amount"), "payment amount") != amount:
            raise ValueError("CHIP payment does not match the purchase amount")
        timestamp = _positive_integer(payment.get("paid_on"), "paid timestamp")
        try:
            paid_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            raise ValueError("CHIP payment timestamp is invalid") from None
    return {
        "payment_gateway": "chip", "gateway_order_id": purchase_id, "order_reference": reference,
        "payment_reference": purchase_id, "paid": paid, "gateway_status": status,
        "amount_sen": amount, "currency": "MYR", "paid_at": paid_at,
        "brand_id": brand_id, "is_test": purchase["is_test"],
    }


def _validate_purchase(purchase: dict, config: ChipConfig) -> dict:
    normalized = normalize_purchase(purchase)
    if normalized["brand_id"] != config.brand_id or normalized["is_test"] is not config.is_test:
        raise ValueError("CHIP purchase brand or mode does not match configuration")
    return normalized
