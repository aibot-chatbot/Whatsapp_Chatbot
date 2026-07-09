"""toyyibpay_routes.py -- ToyyibPay payment callback endpoint.

This module exposes the ToyyibPay server-to-server callback endpoint
for AI-credit top-up payment notifications and subscription payment
notifications.
"""

import logging

from flask import Blueprint, jsonify, request

from app.services.toyyibpay_service import (
    ToyyibPayConfig,
    ToyyibPayConfigError,
    verify_callback_hash,
    parse_verified_callback,
)
from app.services.ai_credit_topup_callback_service import (
    process_topup_payment_callback,
)
from app.services.subscription_payment_callback_service import (
    process_subscription_payment_callback,
)
from app.database.company_subscription_order_repository import (
    get_subscription_order_by_gateway_id,
)

logger = logging.getLogger(__name__)

toyyibpay_bp = Blueprint('toyyibpay', __name__)


def _is_subscription_callback(payment_gateway, gateway_order_id):
    """Check whether a callback gateway ID corresponds to a subscription order."""
    if not payment_gateway or not gateway_order_id:
        return False
    order = get_subscription_order_by_gateway_id(
        payment_gateway=payment_gateway,
        gateway_order_id=gateway_order_id,
    )
    return order is not None


@toyyibpay_bp.route('/api/billing/toyyibpay/callback', methods=['POST'])
def toyyibpay_callback():
    """Handle ToyyibPay payment callback.

    Detects whether the callback is for a subscription order or an
    AI-credit top-up order and delegates to the appropriate handler.

    This endpoint is called by ToyyibPay after a customer completes payment.
    It verifies the callback hash before processing.

    ToyyibPay may retry on HTTP 500 responses.
    Returns HTTP 200 for successful and idempotent-replay callbacks.
    Returns HTTP 400 for invalid or untrusted callbacks.
    Returns HTTP 500 for temporary internal failures.
    """
    try:
        # Read the raw callback payload
        payload = request.form.to_dict()

        if not payload:
            logger.warning("ToyyibPay callback received empty form data")
            return jsonify({
                "status": "error",
                "message": "Empty callback payload.",
            }), 400

        # Verify the callback hash
        try:
            config = ToyyibPayConfig()
            config.validate_for_hash_verification()
            is_valid = verify_callback_hash(config, payload)
        except ToyyibPayConfigError as exc:
            logger.error(
                "ToyyibPay callback hash config error: %s",
                exc,
            )
            return jsonify({
                "status": "error",
                "message": "Temporary processing failure. ToyyibPay will retry.",
            }), 500
        except ValueError as exc:
            logger.warning(
                "ToyyibPay callback hash verification error: %s",
                exc,
            )
            return jsonify({
                "status": "error",
                "message": "Invalid callback data.",
            }), 400

        if not is_valid:
            logger.warning("ToyyibPay callback has invalid hash")
            return jsonify({
                "status": "error",
                "message": "Invalid callback hash.",
            }), 400

        # Parse the verified callback
        try:
            parsed = parse_verified_callback(payload)
        except ValueError as exc:
            logger.warning(
                "ToyyibPay callback parsing failed: %s",
                exc,
            )
            return jsonify({
                "status": "error",
                "message": "Invalid callback data.",
            }), 400

        # Detect callback type: subscription or AI-credit top-up
        payment_gateway = parsed.get("payment_gateway")
        gateway_order_id = parsed.get("gateway_order_id")

        if _is_subscription_callback(payment_gateway, gateway_order_id):
            # Process subscription payment callback
            try:
                result = process_subscription_payment_callback(parsed)
            except ValueError as exc:
                logger.warning(
                    "Subscription callback rejected: %s",
                    exc,
                )
                return jsonify({
                    "status": "error",
                    "message": str(exc),
                }), 400
            except RuntimeError as exc:
                logger.error(
                    "Subscription callback processing failed: %s",
                    exc,
                )
                return jsonify({
                    "status": "error",
                    "message": "Temporary processing failure. ToyyibPay will retry.",
                }), 500

            logger.info(
                "Subscription callback processed: billcode %s, order %s, status %s",
                gateway_order_id,
                result.get("order_reference"),
                result.get("status"),
            )
            return jsonify({"status": "success"}), 200

        # Process AI-credit top-up payment callback
        try:
            result = process_topup_payment_callback(parsed)
        except ValueError as exc:
            logger.warning(
                "ToyyibPay top-up callback processing rejected: %s",
                exc,
            )
            return jsonify({
                "status": "error",
                "message": str(exc),
            }), 400
        except RuntimeError as exc:
            logger.error(
                "ToyyibPay top-up callback processing failed: %s",
                exc,
            )
            return jsonify({
                "status": "error",
                "message": "Temporary processing failure. ToyyibPay will retry.",
            }), 500

        # Return success
        logger.info(
            "ToyyibPay top-up callback processed: billcode %s, order %s, status %s",
            parsed.get("gateway_order_id"),
            result.get("order_reference"),
            result.get("status"),
        )

        return jsonify({"status": "success"}), 200

    except Exception:
        logger.exception(
            "Unexpected error processing ToyyibPay callback from %s",
            request.remote_addr,
        )
        return jsonify({
            "status": "error",
            "message": "Unexpected processing failure. ToyyibPay will retry.",
        }), 500