# ---------------------------------------------------------------------------
#  app/services/toyyibpay_service.py
#  ToyyibPay API client for AI-credit top-up checkout.
# ---------------------------------------------------------------------------

"""toyyibpay_service.py - Internal ToyyibPay API client.

This module handles ToyyibPay configuration, bill creation, and
callback hash verification. It does not grant AI credit, update
orders, or expose any Flask route.

Configuration is read from environment variables without modifying .env.
All values are validated before any HTTP request.
"""

import hashlib
import hmac
import logging
import os
from typing import Any
from decimal import Decimal, InvalidOperation

import requests
import re

logger = logging.getLogger(__name__)

class ToyyibPayConfigError(Exception):
    """Raised when ToyyibPay server-side configuration is invalid or missing.

    Route handlers should map ToyyibPayConfigError to HTTP 500
    and ValueError to HTTP 400.
    """

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_ENV_ENV = "TOYYIBPAY_ENV"
_ENV_SECRET_KEY = "TOYYIBPAY_USER_SECRET_KEY"
_ENV_CATEGORY_CODE = "TOYYIBPAY_CATEGORY_CODE"
_ENV_CALLBACK_URL = "TOYYIBPAY_CALLBACK_URL"
_ENV_RETURN_URL = "TOYYIBPAY_RETURN_URL"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MICRO_MYR_PER_CENT = 10_000

# Production-only: no sandbox URL defined
_PRODUCTION_BASE = "https://toyyibpay.com"

_CREATE_BILL_PATH = "/index.php/api/createBill"
# _VALID_ENVIRONMENTS removed: production-only

_DEFAULT_TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ToyyibPayConfig:
    """Validated ToyyibPay configuration loaded from environment variables."""

    def __init__(self) -> None:
        raw_env = os.getenv(_ENV_ENV, "").strip().lower()
        if raw_env != "production":
            raise ToyyibPayConfigError(
                f"{_ENV_ENV} must be set to production, got {raw_env!r}"
            )
        self.env = raw_env
        self.secret_key = os.getenv(_ENV_SECRET_KEY, "").strip()
        self.category_code = os.getenv(_ENV_CATEGORY_CODE, "").strip()
        self.callback_url = os.getenv(_ENV_CALLBACK_URL, "").strip()
        self.return_url = os.getenv(_ENV_RETURN_URL, "").strip()

    def validate_for_bill_creation(self) -> None:
        """Raise ToyyibPayConfigError if required config is missing for bill creation."""
        if not self.secret_key:
            raise ToyyibPayConfigError("TOYYIBPAY_USER_SECRET_KEY is not configured")
        if not self.category_code:
            raise ToyyibPayConfigError("TOYYIBPAY_CATEGORY_CODE is not configured")
        if not self.callback_url:
            raise ToyyibPayConfigError("TOYYIBPAY_CALLBACK_URL is not configured")

    def validate_for_hash_verification(self) -> None:
        """Raise ToyyibPayConfigError if required config is missing for hash verification."""
        if not self.secret_key:
            raise ToyyibPayConfigError("TOYYIBPAY_USER_SECRET_KEY is not configured")

    @property
    def base_url(self) -> str:
        return _PRODUCTION_BASE

    @property
    def create_bill_url(self) -> str:
        return self.base_url + _CREATE_BILL_PATH

# ---------------------------------------------------------------------------
# Amount conversion
# ---------------------------------------------------------------------------

def micro_myr_to_cent(amount_micro_myr: int) -> int:
    """Convert micro-MYR to ToyyibPay cent.

    ToyyibPay uses cent (1 MYR = 100 cent).
    Internal balance uses micro-MYR (1 MYR = 1,000,000 micro-MYR).

    Therefore: amount_cent = amount_micro_myr // 10_000

    Returns:
        Integer amount in cent.

    Raises:
        ValueError: If amount is not a positive integer, or not divisible by 10,000.
    """
    if isinstance(amount_micro_myr, bool):
        raise ValueError("amount_micro_myr must be an integer, got bool")
    if not isinstance(amount_micro_myr, int):
        raise ValueError(
            f"amount_micro_myr must be an integer, got {type(amount_micro_myr).__name__}"
        )
    if amount_micro_myr < 1:
        raise ValueError(
            f"amount_micro_myr must be positive, got {amount_micro_myr}"
        )
    if amount_micro_myr % _MICRO_MYR_PER_CENT != 0:
        raise ValueError(
            f"amount_micro_myr must be divisible by {_MICRO_MYR_PER_CENT}, "
            f"got {amount_micro_myr}"
        )
    return amount_micro_myr // _MICRO_MYR_PER_CENT

# ---------------------------------------------------------------------------
# Bill creation
# ---------------------------------------------------------------------------

def _get_config() -> ToyyibPayConfig:
    """Lazy-init ToyyibPayConfig (cached in module)."""
    if not hasattr(_get_config, "_config"):
        _get_config._config = ToyyibPayConfig()
    return _get_config._config

def create_bill(
    order_reference: str,
    amount_micro_myr: int,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None = None,
    description: str = "AI Credit Top-Up",
) -> dict:
    """Create a ToyyibPay bill for an AI credit top-up.

    Args:
        order_reference: Canonical UUID order reference (billExternalReferenceNo).
        amount_micro_myr: Amount in micro-MYR.
        customer_name: Customer full name (billTo).
        customer_email: Customer email (billEmail).
        customer_phone: Optional customer phone (billPhone).
        description: Bill description.

    Returns:
        Dictionary containing:
        - gateway_order_id (BillCode)
        - checkout_url (ToyyibPay payment page URL)

    Raises:
        ToyyibPayConfigError: If configuration is invalid.
        ValueError: If input is invalid.
        RuntimeError: If the API request fails or response is malformed.
    """
    config = _get_config()
    config.validate_for_bill_creation()

    if not order_reference or not isinstance(order_reference, str):
        raise ValueError("order_reference must be a non-empty string")
    if not customer_name or not isinstance(customer_name, str) or not customer_name.strip():
        raise ValueError("customer_name must be a non-empty string")
    if not customer_email or not isinstance(customer_email, str) or not customer_email.strip():
        raise ValueError("customer_email must be a non-empty string")
    if not description:
        description = "AI Credit Top-Up"

    amount_cent = micro_myr_to_cent(amount_micro_myr)

    import re
    bill_name = re.sub(r'[^a-zA-Z0-9 _-]', '', description.strip())[:30] or "AI Credit Top-Up"
    bill_safe_description = re.sub(r'[^a-zA-Z0-9 _-]', '', description.strip())[:100] or "AI Credit Top-Up"

    payload = {
        "userSecretKey": config.secret_key,
        "categoryCode": config.category_code,
        "billName": bill_name,
        "billDescription": bill_safe_description,
        "billPriceSetting": "1",  # 1 = fixed price
        "billPayorInfo": "1",  # 1 = collect payer info
        "billAmount": str(amount_cent),
        "billReturnUrl": config.return_url or "",
        "billCallbackUrl": config.callback_url,
        "billExternalReferenceNo": order_reference,
        "billTo": customer_name.strip(),
        "billEmail": customer_email.strip(),
        "billPhone": (customer_phone or "").strip(),
        "billSplitPayment": "0",
        "billSplitPaymentArgs": "",
        "billPaymentChannel": "0",  # 0 = all channels
        "billDisplayMerchant": "1",
        "billContentEmail": f"Thank you for your AI credit top-up of RM{amount_cent // 100} {amount_cent % 100:02d}",
        "billChargeToCustomer": "0",
    }

    logger.info(
        "Creating ToyyibPay bill for order %s, amount %d cent",
        order_reference, amount_cent,
    )

    try:
        response = requests.post(
            config.create_bill_url,
            data=payload,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"ToyyibPay createBill request timed out after "
            f"{_DEFAULT_TIMEOUT_SECONDS}s for order {order_reference!r}"
        )
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            f"ToyyibPay createBill connection failed for order "
            f"{order_reference!r}: {exc}"
        )

    if response.status_code != 200:
        _log_safe_error(response)
        raise RuntimeError(
            f"ToyyibPay createBill returned HTTP {response.status_code} "
            f"for order {order_reference!r}"
        )

    try:
        result = response.json()
    except ValueError:
        body_piece = (response.text or "")[:300].replace(chr(10), " ").replace(chr(13), " ")
        raise RuntimeError(
            f"ToyyibPay createBill returned non-JSON response; "
            f"HTTP {response.status_code}; "
            f"content_type='{response.headers.get('Content-Type', '')}'; "
            f"body='{body_piece}' "
            f"for order {order_reference!r}"
        )

    if not isinstance(result, list) or len(result) == 0:
        raise RuntimeError(
            f"ToyyibPay createBill returned unexpected structure for "
            f"order {order_reference!r}: {result!r}"
        )

    bill = result[0]

    if not isinstance(bill, dict):
        raise RuntimeError(
            "ToyyibPay createBill response first element is not a dictionary"
        )

    raw_bill_code = bill.get("BillCode")

    if raw_bill_code is None or not isinstance(raw_bill_code, str):
        raise RuntimeError(
            "ToyyibPay createBill response has invalid BillCode type"
        )

    bill_code = raw_bill_code.strip()

    if not bill_code:
        raise RuntimeError(
            "ToyyibPay createBill response has empty BillCode"
        )

    # The ToyyibPay checkout URL: base_url/BillCode
    checkout_url = f'{config.base_url}/{bill_code}'

    logger.info(
        "ToyyibPay bill %s created for order %s (amount %d cent)",
        bill_code, order_reference, amount_cent,
    )

    return {
        "gateway_order_id": bill_code,
        "checkout_url": checkout_url,
    }

# ---------------------------------------------------------------------------
# Callback hash verification
# ---------------------------------------------------------------------------

def verify_callback_hash(config: ToyyibPayConfig, payload: dict[str, Any]) -> bool:
    """Verify the ToyyibPay callback hash.

    Official formula (from ToyyibPay API documentation):
        hash = MD5(userSecretKey + status + order_id + refno + "ok")

    Args:
        config: Validated ToyyibPayConfig with secret_key populated.
        payload: Raw callback payload (form-encoded fields from ToyyibPay).
    Returns:
        True when the hash is valid, False otherwise.

    Raises:
        ToyyibPayConfigError: If server-side secret key is not configured.
        ValueError: If required callback fields are missing.
    """
    config.validate_for_hash_verification()

    hash_value = payload.get("hash", "").strip()
    if not hash_value:
        raise ValueError("ToyyibPay callback payload is missing required field 'hash'")

    status = payload.get("status", "").strip()
    order_id = payload.get("order_id", "").strip()
    refno = payload.get("refno", "").strip()

    if not status or not order_id or not refno:
        raise ValueError(
            "ToyyibPay callback payload is missing one or more required fields: "
            "status, order_id, refno"
        )

    raw = config.secret_key + status + order_id + refno + "ok"
    expected = hashlib.md5(raw.encode("utf-8")).hexdigest()

    logger.debug("ToyyibPay callback hash verification: expected=%s received=%s",
                expected, hash_value)

    return hmac.compare_digest(expected, hash_value)

# ---------------------------------------------------------------------------
# Callback parsing
# ---------------------------------------------------------------------------

def _parse_bool(value: Any) -> bool:
    """Parse a ToyyibPay status field into a paid boolean.

    ToyyibPay callback status:
        1 = success -> True
        2 = pending -> False
        3 = failed  -> False
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "1":
            return True
        if cleaned in ("0", "2", "3"):
            return False
    if isinstance(value, int):
        if value == 1:
            return True
        if value in (0, 2, 3):
            return False
    raise ValueError(f"Unrecognised ToyyibPay status value: {value!r}")

def _parse_toyyibpay_amount(value: Any) -> int:
    """Parse a ToyyibPay callback amount (MYR decimal string) into cent.

    ToyyibPay sends the amount as a MYR string like "3.00" (RM3.00).
    This converts to cent: Decimal("3.00") * 100 = 300 cent.

    Args:
        value: The raw amount value from the callback (str or numeric).

    Returns:
        Integer amount in cent.

    Raises:
        ValueError: If value is empty, boolean, negative, zero,
            malformed, or has more than two decimal places.
    """
    if isinstance(value, bool):
        raise ValueError("amount must be an integer or decimal string, got bool")
    if value is None:
        raise ValueError("amount is required but was None")
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        raise ValueError(f"amount must be a string or number, got {type(value).__name__}")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("amount must not be empty")
    try:
        d = Decimal(cleaned)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"amount is not a valid decimal: {value!r}")
    if d <= 0:
        raise ValueError(f"amount must be positive, got {value!r}")
    # Check decimal places
    if d.as_tuple().exponent < -2:
        raise ValueError(f"amount must have at most 2 decimal places, got {value!r}")

    cent = int(d * 100)
    return cent

def parse_verified_callback(payload: dict[str, Any]) -> dict:
    """Parse an already hash-verified ToyyibPay callback payload.

    Args:
        payload: Raw callback fields (signature already verified).

    Returns:
        Normalized dictionary with:
        - payment_gateway: "toyyibpay"
        - gateway_order_id: billcode
        - order_reference: order_id (billExternalReferenceNo)
        - payment_reference: refno (ToyyibPay transaction reference)
        - paid: True when status=1
        - gateway_status: Raw status string
        - amount_sen: Integer amount in cent
        - paid_at: Transaction time when available
        - failure_reason: Reason from callback when applicable

    Raises:
        ValueError: If required fields are missing or malformed.
    """
    billcode = (payload.get("billcode") or "").strip()
    order_id = (payload.get("order_id") or "").strip()
    refno = (payload.get("refno") or "").strip()
    status = (payload.get("status") or "").strip()
    amount_raw = payload.get("amount")
    transaction_time = (payload.get("transaction_time") or "").strip()
    reason = (payload.get("reason") or "").strip()

    if not billcode:
        raise ValueError("Missing billcode in ToyyibPay callback")
    if not order_id:
        raise ValueError("Missing order_id in ToyyibPay callback")
    if not refno:
        raise ValueError("Missing refno in ToyyibPay callback")
    if not status:
        raise ValueError("Missing status in ToyyibPay callback")

    amount_cent_val = _parse_toyyibpay_amount(amount_raw)
    paid = _parse_bool(status)
    result: dict[str, Any] = {
        "payment_gateway": "toyyibpay",
        "gateway_order_id": billcode,
        "order_reference": order_id,
        "payment_reference": refno,
        "paid": paid,
        "gateway_status": status,
        "amount_sen": amount_cent_val,
        "paid_total_micro_myr": amount_cent_val * 10000,
        "paid_at": "",
        "failure_reason": reason if reason else None,
    }

    if transaction_time:
        result["paid_at"] = transaction_time

    return result

# ---------------------------------------------------------------------------
# Safe logging helper
# ---------------------------------------------------------------------------

def _log_safe_error(response: requests.Response) -> None:
    """Log a non-success response without exposing secrets or full customer data."""
    try:
        body = response.text[:500] if response.text else "(empty)"
    except Exception:
        body = "(unreadable)"
    logger.error(
        "ToyyibPay API error: HTTP %d body=%.200s",
        response.status_code, body,
    )
