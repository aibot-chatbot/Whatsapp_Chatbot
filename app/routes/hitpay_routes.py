"""HitPay event webhook endpoint."""

import json
import logging

from flask import Blueprint, jsonify, request

from app.services.hitpay_payment_service import process_hitpay_payment_request
from app.services.hitpay_service import (
    HitPayAPIError,
    HitPayConfig,
    HitPayConfigError,
    get_payment_request,
    verify_webhook_signature,
)


logger = logging.getLogger(__name__)
hitpay_bp = Blueprint("hitpay", __name__, url_prefix="/api/billing/hitpay")


@hitpay_bp.post("/webhook")
def hitpay_webhook():
    """Verify exact bytes, re-fetch authoritative state, then fulfil."""
    try:
        raw_body = request.get_data(cache=True)
        config = HitPayConfig.from_env()
        config.validate_for_webhook()
        signature = request.headers.get("Hitpay-Signature", "")
        if not verify_webhook_signature(raw_body, signature, config.webhook_salt):
            return jsonify({"status": "error", "message": "Invalid webhook signature."}), 401

        event_object = request.headers.get("Hitpay-Event-Object", "").strip().lower()
        event_type = request.headers.get("Hitpay-Event-Type", "").strip().lower()
        if event_type.startswith("payment_request."):
            event_type = event_type.split(".", 1)[1]
        if event_object != "payment_request" or event_type not in {"completed", "failed"}:
            return jsonify({"status": "ignored"}), 200

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("HitPay webhook body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("HitPay webhook body must be an object")
        request_id = str(payload.get("id") or "").strip()
        if not request_id:
            raise ValueError("HitPay webhook is missing payment request ID")

        authoritative = get_payment_request(config, request_id)
        result = process_hitpay_payment_request(authoritative)
        return jsonify({"status": "success", "result": result.get("status")}), 200
    except HitPayConfigError:
        logger.exception("HitPay webhook configuration is unavailable")
        return jsonify({"status": "error", "message": "Temporary processing failure."}), 500
    except ValueError as exc:
        logger.warning("HitPay webhook rejected: %s", exc)
        return jsonify({"status": "error", "message": "Invalid webhook data."}), 400
    except (HitPayAPIError, RuntimeError):
        logger.exception("HitPay webhook processing will require retry")
        return jsonify({"status": "error", "message": "Temporary processing failure."}), 500
    except Exception:
        logger.exception("Unexpected HitPay webhook processing failure")
        return jsonify({"status": "error", "message": "Temporary processing failure."}), 500
