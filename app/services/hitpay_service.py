"""Small server-side adapter for HitPay hosted payment requests."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse

import requests


class HitPayConfigError(ValueError):
    """HitPay is selected but its server-side configuration is incomplete."""


class HitPayRequestRejectedError(RuntimeError):
    """HitPay definitively rejected a request before creating a checkout."""


class HitPayAmbiguousError(RuntimeError):
    """The request may have reached HitPay and must be reconciled before retry."""


class HitPayAPIError(RuntimeError):
    """HitPay could not provide authoritative payment status."""


@dataclass(frozen=True)
class HitPayConfig:
    enabled: bool
    environment: str
    api_key: str
    webhook_salt: str
    redirect_url: str
    webhook_url: str

    @classmethod
    def from_env(cls) -> "HitPayConfig":
        return cls(
            enabled=_env_bool("HITPAY_ENABLED", False),
            environment=os.getenv("HITPAY_ENV", "sandbox").strip().lower(),
            api_key=os.getenv("HITPAY_API_KEY", "").strip(),
            webhook_salt=os.getenv("HITPAY_WEBHOOK_SALT", "").strip(),
            redirect_url=os.getenv("HITPAY_REDIRECT_URL", "").strip(),
            webhook_url=os.getenv("HITPAY_WEBHOOK_URL", "").strip(),
        )

    @property
    def base_url(self) -> str:
        if self.environment == "sandbox":
            return "https://api.sandbox.hit-pay.com"
        if self.environment == "production":
            return "https://api.hit-pay.com"
        raise HitPayConfigError("HITPAY_ENV must be 'sandbox' or 'production'")

    def validate_for_checkout(self) -> None:
        if not self.enabled:
            raise HitPayConfigError("HitPay is not enabled")
        if not self.api_key:
            raise HitPayConfigError("HITPAY_API_KEY is required")
        _require_https_url(self.redirect_url, "HITPAY_REDIRECT_URL")
        _require_https_url(self.webhook_url, "HITPAY_WEBHOOK_URL")

    def validate_for_api(self) -> None:
        if not self.enabled:
            raise HitPayConfigError("HitPay is not enabled")
        if not self.api_key:
            raise HitPayConfigError("HITPAY_API_KEY is required")
        _ = self.base_url

    def validate_for_webhook(self) -> None:
        if not self.enabled:
            raise HitPayConfigError("HitPay is not enabled")
        if not self.webhook_salt:
            raise HitPayConfigError("HITPAY_WEBHOOK_SALT is required")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise HitPayConfigError(f"{name} must be a boolean")


def _require_https_url(value: str, name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HitPayConfigError(f"{name} must be an absolute HTTPS URL")


def validate_checkout_url(value: object, environment: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HitPayAmbiguousError("HitPay returned no checkout URL")
    url = value.strip()
    parsed = urlparse(url)
    expected_host = (
        "securecheckout.sandbox.hit-pay.com"
        if environment == "sandbox"
        else "securecheckout.hit-pay.com"
    )
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise HitPayAmbiguousError("HitPay returned an unexpected checkout URL")
    return url


def create_payment_request(
    *,
    config: HitPayConfig,
    order_reference: str,
    amount_sen: int,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None,
    description: str,
    expires_after: str | None = None,
) -> dict:
    """Create one non-repeatable HitPay hosted checkout."""
    config.validate_for_checkout()
    if not order_reference:
        raise ValueError("order_reference is required")
    if not isinstance(amount_sen, int) or isinstance(amount_sen, bool) or amount_sen <= 0:
        raise ValueError("amount_sen must be a positive integer")

    payload = {
        "amount": str((Decimal(amount_sen) / Decimal(100)).quantize(Decimal("0.01"))),
        "currency": "MYR",
        "email": customer_email,
        "name": customer_name,
        "purpose": description,
        "reference_number": order_reference,
        "redirect_url": config.redirect_url,
        "allow_repeated_payments": False,
        "send_email": False,
        "send_sms": False,
        "metadata": {"order_reference": order_reference},
    }
    if customer_phone:
        payload["phone"] = customer_phone
    if expires_after:
        payload["expires_after"] = expires_after

    try:
        response = requests.post(
            f"{config.base_url}/v1/payment-requests",
            headers={
                "X-BUSINESS-API-KEY": config.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(5, 20),
        )
    except requests.RequestException as exc:
        raise HitPayAmbiguousError("HitPay payment request outcome is unknown") from exc

    if 400 <= response.status_code < 500:
        raise HitPayRequestRejectedError(
            f"HitPay rejected the payment request (HTTP {response.status_code})"
        )
    if response.status_code < 200 or response.status_code >= 300:
        raise HitPayAmbiguousError(
            f"HitPay payment request outcome is unknown (HTTP {response.status_code})"
        )

    try:
        body = response.json()
    except (ValueError, TypeError) as exc:
        raise HitPayAmbiguousError("HitPay returned an invalid response") from exc
    if not isinstance(body, dict):
        raise HitPayAmbiguousError("HitPay returned an invalid response")

    gateway_order_id = str(body.get("id") or "").strip()
    if not gateway_order_id:
        raise HitPayAmbiguousError("HitPay returned no payment request ID")
    if str(body.get("reference_number") or "").strip() != order_reference:
        raise HitPayAmbiguousError("HitPay returned a mismatched order reference")
    try:
        returned_amount_sen = _amount_to_sen(body.get("amount"))
    except ValueError as exc:
        raise HitPayAmbiguousError("HitPay returned an invalid amount") from exc
    if returned_amount_sen != amount_sen:
        raise HitPayAmbiguousError("HitPay returned a mismatched amount")
    if str(body.get("currency") or "").strip().upper() != "MYR":
        raise HitPayAmbiguousError("HitPay returned a mismatched currency")
    repeated = body.get("allow_repeated_payments")
    if not (repeated is False or repeated == 0 or repeated in ("false", "0")):
        raise HitPayAmbiguousError("HitPay enabled repeated payments unexpectedly")

    return {
        "gateway_order_id": gateway_order_id,
        "checkout_url": validate_checkout_url(body.get("url"), config.environment),
        "gateway_status": str(body.get("status") or "pending").strip().lower(),
    }


def verify_webhook_signature(raw_body: bytes, signature: str, webhook_salt: str) -> bool:
    """Verify an event webhook HMAC over the exact request bytes."""
    if not isinstance(raw_body, bytes) or not signature or not webhook_salt:
        return False
    expected = hmac.new(
        webhook_salt.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _request_json(response: requests.Response, *, operation: str) -> object:
    if response.status_code < 200 or response.status_code >= 300:
        raise HitPayAPIError(
            f"HitPay {operation} failed (HTTP {response.status_code})"
        )
    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise HitPayAPIError(f"HitPay {operation} returned invalid JSON") from exc


def get_payment_request(config: HitPayConfig, request_id: str) -> dict:
    """Fetch authoritative state for one HitPay payment request."""
    config.validate_for_api()
    if not request_id:
        raise ValueError("request_id is required")
    try:
        response = requests.get(
            f"{config.base_url}/v1/payment-requests/{request_id}",
            headers={"X-BUSINESS-API-KEY": config.api_key},
            timeout=(5, 20),
        )
    except requests.RequestException as exc:
        raise HitPayAPIError("HitPay payment status lookup failed") from exc
    body = _request_json(response, operation="payment status lookup")
    if not isinstance(body, dict) or str(body.get("id") or "").strip() != request_id:
        raise HitPayAPIError("HitPay payment status response did not match the request")
    return body


def find_payment_request_by_reference(
    config: HitPayConfig, order_reference: str
) -> dict | None:
    """Find an ambiguous checkout by the unique internal reference."""
    config.validate_for_api()
    if not order_reference:
        raise ValueError("order_reference is required")
    try:
        response = requests.get(
            f"{config.base_url}/v1/payment-requests",
            headers={"X-BUSINESS-API-KEY": config.api_key},
            params={"search": order_reference, "per_page": 100, "current_page": 1},
            timeout=(5, 20),
        )
    except requests.RequestException as exc:
        raise HitPayAPIError("HitPay payment request search failed") from exc
    body = _request_json(response, operation="payment request search")
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict):
        rows = body.get("data") or body.get("payment_requests") or []
    else:
        rows = []
    if not isinstance(rows, list):
        raise HitPayAPIError("HitPay payment request search returned an invalid response")
    exact = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("reference_number") or "").strip() == order_reference
    ]
    if len(exact) > 1:
        raise HitPayAPIError("Multiple HitPay requests share one internal reference")
    return exact[0] if exact else None


def _amount_to_sen(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("HitPay amount is invalid")
    try:
        amount = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError("HitPay amount is invalid") from exc
    if amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("HitPay amount is invalid")
    return int(amount * 100)


def normalize_payment_request(payment_request: dict) -> dict:
    """Normalize one authoritative HitPay payment request for billing."""
    if not isinstance(payment_request, dict):
        raise ValueError("HitPay payment request must be an object")
    request_id = str(payment_request.get("id") or "").strip()
    order_reference = str(payment_request.get("reference_number") or "").strip()
    status = str(payment_request.get("status") or "").strip().lower()
    currency = str(payment_request.get("currency") or "").strip().upper()
    if not request_id or not order_reference or not status:
        raise ValueError("HitPay payment request is missing required fields")
    if currency != "MYR":
        raise ValueError("HitPay payment currency does not match MYR")

    payments = payment_request.get("payments") or []
    if not isinstance(payments, list):
        raise ValueError("HitPay payments must be a list")
    succeeded = [
        payment for payment in payments
        if isinstance(payment, dict)
        and str(payment.get("status") or "").strip().lower() in {"succeeded", "completed"}
    ]
    if status == "completed" and not succeeded:
        raise ValueError("Completed HitPay request has no successful payment")
    payment = succeeded[0] if succeeded else {}
    payment_reference = str(payment.get("id") or request_id).strip()

    return {
        "payment_gateway": "hitpay",
        "gateway_order_id": request_id,
        "order_reference": order_reference,
        "payment_reference": payment_reference,
        "paid": status == "completed",
        "gateway_status": status,
        "amount_sen": _amount_to_sen(payment_request.get("amount")),
        "currency": currency,
        "paid_at": payment.get("updated_at") or payment_request.get("updated_at") or "",
    }
