"""billplz_service.py - Internal Billplz Sandbox/Production client.

This module handles Billplz API configuration, Bill creation, and
callback signature verification.  It does not grant AI credit, update
orders, or expose any Flask route.

Configuration is read from environment variables without modifying .env.
All values are validated before any HTTP request.
"""

import hashlib
import hmac
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_ENV_ENV = "BILLPLZ_ENV"
_ENV_API_KEY = "BILLPLZ_API_KEY"
_ENV_X_SIGNATURE_KEY = "BILLPLZ_X_SIGNATURE_KEY"
_ENV_COLLECTION_ID = "BILLPLZ_COLLECTION_ID"
_ENV_CALLBACK_URL = "BILLPLZ_CALLBACK_URL"
_ENV_REDIRECT_URL = "BILLPLZ_REDIRECT_URL"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MICRO_MYR_PER_SEN = 10_000

_SANDBOX_BASE = "https://www.billplz-sandbox.com/api/"
_PRODUCTION_BASE = "https://www.billplz.com/api/"

_BILL_ENDPOINT = "v3/bills"

_VALID_ENVIRONMENTS = frozenset({"sandbox", "production"})

_DEFAULT_TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class BillplzConfig:
    """Validated Billplz configuration loaded from environment variables."""

    def __init__(self) -> None:
        raw_env = os.getenv(_ENV_ENV, "sandbox").strip().lower()

        if raw_env not in _VALID_ENVIRONMENTS:
            raise ValueError(
                f"{_ENV_ENV} must be one of {sorted(_VALID_ENVIRONMENTS)}, "
                f"got {raw_env!r}"
            )

        self.env = raw_env
        self.api_key = os.getenv(_ENV_API_KEY, "").strip()
        self.x_signature_key = os.getenv(_ENV_X_SIGNATURE_KEY, "").strip()
        self.collection_id = os.getenv(_ENV_COLLECTION_ID, "").strip()
        self.callback_url = os.getenv(_ENV_CALLBACK_URL, "").strip()
        self.redirect_url = os.getenv(_ENV_REDIRECT_URL, "").strip()

        if not self.api_key:
            raise ValueError(
                f"{_ENV_API_KEY} is not set. "
                "A valid Billplz API secret key is required."
            )

        if not self.collection_id:
            raise ValueError(
                f"{_ENV_COLLECTION_ID} is not set. "
                "A valid Billplz Collection ID is required."
            )

        if not self.callback_url:
            raise ValueError(
                f"{_ENV_CALLBACK_URL} is not set. "
                "A Billplz server callback URL is required."
            )

        # X-Signature key is required for callback verification.
        if not self.x_signature_key:
            raise ValueError(
                f"{_ENV_X_SIGNATURE_KEY} is not set. "
                "The X-Signature key is required for callback verification."
            )

    @property
    def base_url(self) -> str:
        """Resolve the correct API base URL."""
        if self.env == "sandbox":
            return _SANDBOX_BASE
        return _PRODUCTION_BASE

    @property
    def bills_url(self) -> str:
        """Full URL for the Bill creation endpoint."""
        return self.base_url + _BILL_ENDPOINT

    def _auth(self) -> tuple[str, str]:
        """HTTP Basic Auth credentials: (api_key, '')."""
        return (self.api_key, "")


# ---------------------------------------------------------------------------
# MYR conversion
# ---------------------------------------------------------------------------


def micro_myr_to_sen(amount_micro_myr: int) -> int:
    """Convert internal micro-MYR to Billplz sen.

    Args:
        amount_micro_myr: Amount in micro-MYR (1 MYR = 1,000,000 micro-MYR).

    Returns:
        Equivalent amount in sen (1 sen = 10,000 micro-MYR).

    Raises:
        ValueError: If amount is not a positive integer divisible by 10,000.
    """
    if not isinstance(amount_micro_myr, int):
        raise ValueError(
            f"amount_micro_myr must be an integer, got {amount_micro_myr!r}"
        )
    if amount_micro_myr <= 0:
        raise ValueError(
            f"amount_micro_myr must be a positive integer, got {amount_micro_myr}"
        )
    if amount_micro_myr % _MICRO_MYR_PER_SEN != 0:
        raise ValueError(
            f"amount_micro_myr must be divisible by {_MICRO_MYR_PER_SEN} "
            f"(1 sen), got {amount_micro_myr}"
        )
    return amount_micro_myr // _MICRO_MYR_PER_SEN


# ---------------------------------------------------------------------------
# Bill creation
# ---------------------------------------------------------------------------


def create_bill(
    order_reference: str,
    amount_micro_myr: int,
    customer_email: str,
    customer_name: str,
    description: str,
) -> dict:
    """Create a Billplz Bill for an AI-credit top-up order.

    This function is intended for authenticated internal use only.  It is
    not exposed directly via any public API endpoint.

    Args:
        order_reference: Internal top-up order reference.
        amount_micro_myr: Amount in micro-MYR (converted to sen).
        customer_email: Customer email for the bill.
        customer_name: Customer name for the bill.
        description: Human-readable bill description.

    Returns:
        Dictionary with keys:
        - bill_id (str)
        - checkout_url (str)
        - amount (int): Amount in sen.
        - state (str)
        - collection_id (str)
        - paid (bool)
        - paid_amount (int or None)
        - transaction_id (str or None)

    Raises:
        ValueError: If input is invalid.
        RuntimeError: If config or API request fails.
    """
    if not order_reference or not isinstance(order_reference, str) or not order_reference.strip():
        raise ValueError("order_reference must be a non-empty string")
    if not customer_email or not isinstance(customer_email, str):
        raise ValueError("customer_email must be a non-empty string")
    if not customer_name or not isinstance(customer_name, str):
        raise ValueError("customer_name must be a non-empty string")
    if not description:
        description = "AI Credit Top-Up"

    amount_sen = micro_myr_to_sen(amount_micro_myr)

    config = BillplzConfig()

    payload = {
        "collection_id": config.collection_id,
        "email": customer_email.strip(),
        "name": customer_name.strip(),
        "amount": amount_sen,
        "description": description.strip(),
        "callback_url": config.callback_url,
        "reference_1": order_reference.strip(),
        "reference_1_label": "AI Credit Order",
    }

    if config.redirect_url:
        payload["redirect_url"] = config.redirect_url

    logger.info(
        "Creating Billplz bill for order %s, amount %d sen",
        order_reference,
        amount_sen,
    )

    try:
        response = requests.post(
            config.bills_url,
            auth=config._auth(),
            data=payload,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Billplz bill creation timed out after {_DEFAULT_TIMEOUT_SECONDS}s "
            f"for order {order_reference!r}"
        )
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            f"Billplz connection failed for order {order_reference!r}: {exc}"
        )

    if not response.ok:
        _log_safe_error(response)
        raise RuntimeError(
            f"Billplz bill creation returned HTTP {response.status_code} "
            f"for order {order_reference!r}"
        )

    try:
        data = response.json()
    except (ValueError, TypeError):
        raise RuntimeError(
            f"Billplz returned non-JSON response for order {order_reference!r}"
        )

    bill_id = data.get("id")
    checkout_url = data.get("url")

    if not bill_id or not checkout_url:
        raise RuntimeError(
            f"Billplz response missing bill ID or checkout URL for order "
            f"{order_reference!r}"
        )

    return {
        "bill_id": str(bill_id),
        "checkout_url": str(checkout_url),
        "amount": data.get("amount"),
        "state": data.get("state"),
        "collection_id": data.get("collection_id"),
        "paid": bool(data.get("paid", False)),
        "paid_amount": data.get("paid_amount"),
        "transaction_id": data.get("transaction_id"),
    }


# ---------------------------------------------------------------------------
# Callback signature verification
# ---------------------------------------------------------------------------


def verify_callback_signature(payload: dict[str, Any]) -> bool:
    """Verify the Billplz callback X-Signature.

    The Billplz callback is a form-encoded POST with an ``x_signature``
    field.  The signature is computed over all other fields sorted
    case-insensitively, concatenated as ``key + value``, joined with ``|``,
    and HMAC-SHA256 signed with the configured X-Signature key.

    Args:
        payload: Raw callback payload as a dictionary. Must include
            ``x_signature``.

    Returns:
        True when the signature matches, False otherwise.

    Raises:
        ValueError: If the X-Signature key is not configured or
            ``x_signature`` is missing from the payload.
    """
    config = BillplzConfig()

    x_sig = payload.get("x_signature")
    if not x_sig:
        raise ValueError(
            "Billplz callback payload is missing required field 'x_signature'"
        )

    # Build sorted key-value pairs excluding x_signature
    # Sort the concatenated ``key + value`` strings ascending.
    # This matches the official Billplz X-Signature specification.
    pairs = []
    for key in payload:
        if key == "x_signature":
            continue
        value = payload[key]
        if value is None:
            value = ""
        else:
            value = str(value)
        pairs.append(key + value)
    pairs.sort(key=str.lower)  # ascending, case-insensitive per Billplz spec

    source = "|".join(pairs)

    expected = hmac.new(
        config.x_signature_key.encode("utf-8"),
        source.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, x_sig)


# ---------------------------------------------------------------------------
# Callback parsing
# ---------------------------------------------------------------------------


def parse_verified_callback(payload: dict[str, Any]) -> dict:
    """Parse an already-verified Billplz callback.

    This function must be called only after
    :func:`verify_callback_signature` has returned ``True``.

    It does **not** update any order, grant credit, or touch the database.

    Args:
        payload: Verified Billplz callback payload.

    The primary order lookup key is the Billplz **bill ID** (``id`` field).
    The internal ``reference_1`` field is **optional** and may not be present
    in every callback.  Future webhook processing should locate orders by:

        ``payment_gateway = "billplz"``
        plus ``gateway_order_id = <bill ID from callback>``

    Returns:
        Dictionary with keys:
        - bill_id (str or None): Primary lookup value.
        - paid (bool)
        - state (str or None)
        - amount_sen (int or None)
        - paid_amount_sen (int or None)
        - paid_at (str or None)
        - transaction_id (str or None)
        - transaction_status (str or None)
        - order_reference (str or None): Optional, from ``reference_1``.
    """
    bill_id = payload.get("id")
    if not bill_id:
        raise ValueError(
            "Billplz callback is missing required field 'id' (bill ID)"
        )

    paid = _parse_bool(payload.get("paid"))
    amount_sen = _safe_int(payload.get("amount"), label="amount")
    paid_amount_value = payload.get("paid_amount")
    paid_amount_sen = _safe_int(paid_amount_value, label="paid_amount") if paid_amount_value is not None else 0

    return {
        "bill_id": str(bill_id),
        "paid": paid,
        "state": payload.get("state"),
        "amount_sen": amount_sen,
        "paid_amount_sen": paid_amount_sen,
        "paid_at": payload.get("paid_at"),
        "transaction_id": payload.get("transaction_id"),
        "transaction_status": payload.get("transaction_status"),
        "order_reference": payload.get("reference_1"),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: Any) -> bool:
    """Parse a boolean value safely from a callback payload.

    Only accepts the strings ``"true"`` and ``"false"`` (case-insensitive)
    or a native Python ``bool``.  Any other value raises ``ValueError`` so
    that unknown or malformed paid indicators are never silently treated as
    a confirmed payment.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned == "true":
            return True
        if cleaned == "false":
            return False
        raise ValueError(
            f"Cannot parse paid value {value!r}: expected 'true' or 'false'"
        )
    raise ValueError(
        f"Cannot parse paid value {value!r}: expected a string or bool"
    )


def _safe_int(value: Any, label: str = "value") -> int:
    """Parse a non-negative integer strictly, raising on invalid input.

    The future webhook must not silently accept zero, negative or
    malformed numeric values from an already-verified callback.

    Args:
        value: The raw value to parse.
        label: Field name for error messages.

    Returns:
        Non-negative integer.

    Raises:
        ValueError: If value is None, negative, or not a valid integer.
    """
    if value is None:
        raise ValueError(f"{label} is required but was None")
    try:
        parsed = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{label} must be a valid integer, got {value!r}")
    if parsed < 0:
        raise ValueError(f"{label} must be a non-negative integer, got {parsed}")
    return parsed


def _log_safe_error(response: requests.Response) -> None:
    """Log a Billplz error response without exposing secrets."""
    try:
        err_data = response.json()
        safe_errors = err_data.get("error", []) if isinstance(err_data, dict) else []
        if isinstance(safe_errors, list):
            safe_errors = [str(e) for e in safe_errors if isinstance(e, (str, dict))]
        if safe_errors:
            logger.error("Billplz error: %s", "; ".join(safe_errors))
    except (ValueError, TypeError, AttributeError):
        pass