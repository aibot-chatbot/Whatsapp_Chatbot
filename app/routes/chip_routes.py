"""CHIP callbacks verify exact request bytes and re-fetch provider state."""

import json

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.observability import capture_payment_failure
from app.rate_limit import limiter
from app.database.company_subscription_order_repository import get_subscription_order_by_gateway_id
from app.services.chip_service import (
    ChipConfig, ChipConfigError, ChipAPIError, get_public_key, get_purchase,
    verify_webhook_signature,
)
from app.services.chip_payment_service import process_chip_purchase
from app.services.chip_topup_payment_service import process_chip_topup_purchase

chip_bp = Blueprint("chip", __name__, url_prefix="/api/billing/chip")
_MAX_WEBHOOK_BYTES = 1024 * 1024
_REVIEW_EVENTS = {
    "purchase.pending_refund", "purchase.refund_failure", "payment.refunded",
    "payment.charged_back", "payment.chargeback_reversed",
}


class _CallbackIdentityError(ValueError):
    """A signed payload from another brand or another CHIP mode, e.g. after a mode flip."""


@chip_bp.post("/callback")
@chip_bp.post("/webhook")
@limiter.limit(lambda: current_app.config.get("RATELIMIT_CHIP_CALLBACK", "120/minute"))
def chip_callback():
    mode = "unknown"
    try:
        if request.content_length is not None and request.content_length > _MAX_WEBHOOK_BYTES:
            raise RequestEntityTooLarge()
        raw = request.stream.read(_MAX_WEBHOOK_BYTES + 1)
        if len(raw) > _MAX_WEBHOOK_BYTES:
            raise RequestEntityTooLarge()
        signature = request.headers.get("X-Signature", "")
        if not signature or len(signature) > 16384:
            return jsonify(status="error", message="Invalid callback signature."), 401
        config = ChipConfig.from_env()
        mode = config.environment
        config.validate_for_api()
        is_webhook = request.path.endswith("/webhook")
        if is_webhook:
            key = config.webhook_public_key
            if not key:
                raise ChipConfigError("Webhook public key is not configured")
        else:
            key = config.callback_public_key or get_public_key(config)
        if not verify_webhook_signature(raw, signature, key):
            capture_payment_failure("webhook", reason="invalid_signature", mode=mode)
            return jsonify(status="error", message="Invalid callback signature."), 401
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Invalid JSON callback") from None
        if not isinstance(payload, dict):
            raise ValueError("Invalid callback object")
        event = payload.get("event_type")
        if is_webhook and event not in _REVIEW_EVENTS | {
            "purchase.paid", "purchase.cancelled", "purchase.payment_failure", "purchase.expired",
        }:
            return jsonify(status="ignored"), 200
        if payload.get("is_test") is not config.is_test or payload.get("brand_id") != config.brand_id:
            raise _CallbackIdentityError("Callback brand or environment mismatch")
        review_required = is_webhook and event in _REVIEW_EVENTS
        purchase_id = payload.get("id")
        if review_required and event.startswith("payment."):
            related = payload.get("related_to")
            if payload.get("type") != "payment" or not isinstance(related, dict) or related.get("type") != "purchase":
                raise ValueError("Payment event does not reference a purchase")
            purchase_id = related.get("id")
        authoritative = get_purchase(config, purchase_id)
        subscription = get_subscription_order_by_gateway_id("chip", authoritative["id"])
        if subscription:
            result = process_chip_purchase(authoritative, config=config, review_required=review_required)
        else:
            result = process_chip_topup_purchase(authoritative, config, review_required=review_required)
        if result.get("status") not in {
            "activated_and_credited", "legacy_order_activated", "already_activated",
            "credited", "already_credited", "test_paid", "pending", "cancelled", "expired",
        }:
            capture_payment_failure("fulfillment", reason="status_review" if review_required else "fulfillment", mode=mode)
            return jsonify(status="error", message="Payment requires reconciliation."), 500
        return jsonify(status="success", result=result.get("status")), 200
    except RequestEntityTooLarge:
        return jsonify(status="error", message="Callback body is too large."), 413
    except ChipConfigError as exc:
        capture_payment_failure("webhook", reason="configuration", mode=mode, exc=exc)
        return jsonify(status="error", message="Temporary processing failure."), 500
    except _CallbackIdentityError as exc:
        # Reported apart from the generic bucket: Sentry redacts the message, so only
        # this tag separates a stale-mode callback from malformed or unfulfillable data.
        capture_payment_failure("webhook", reason="brand_mismatch", mode=mode, exc=exc)
        return jsonify(status="error", message="Invalid callback data."), 400
    except ValueError as exc:
        capture_payment_failure("webhook", reason="mismatch", mode=mode, exc=exc)
        return jsonify(status="error", message="Invalid callback data."), 400
    except ChipAPIError as exc:
        capture_payment_failure("webhook", reason="provider_unavailable", mode=mode, exc=exc)
        return jsonify(status="error", message="Temporary processing failure."), 500
    except Exception as exc:
        capture_payment_failure("webhook", reason="unexpected", mode=mode, exc=exc)
        return jsonify(status="error", message="Temporary processing failure."), 500
