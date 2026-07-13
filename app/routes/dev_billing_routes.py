"""dev_billing_routes.py — Development-only billing routes.

This blueprint is registered only when ENABLE_DEV_BILLING_ROUTES is true.
It must never be available in production.
"""

import logging
import uuid
from flask import Blueprint, jsonify, g
from app.decorators.auth_decorator import token_required

logger = logging.getLogger(__name__)

dev_billing_bp = Blueprint("dev_billing", __name__, url_prefix="/api/billing/dev")


@dev_billing_bp.route("/subscription-orders/<reference>/complete", methods=["POST"])
@token_required
def dev_complete_subscription_order(reference):
    """DEV ONLY: Complete a pending subscription order without real payment.

    This endpoint simulates a successful ToyyibPay callback by reusing the
    production process_subscription_payment_callback() flow.
    """
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        try:
            uuid.UUID(reference)
        except (ValueError, AttributeError):
            return jsonify({
                "status": "error",
                "message": "Invalid order reference format."
            }), 400

        from app.database.company_subscription_order_repository import (
            get_subscription_order_by_reference_and_company,
            update_subscription_order_status,
        )

        order = get_subscription_order_by_reference_and_company(
            order_reference=reference,
            company_id=company_id,
        )

        if not order:
            return jsonify({
                "status": "error",
                "message": "Order not found or access denied."
            }), 404

        if order.get("status") != "pending":
            return jsonify({
                "status": "error",
                "message": f"Order status is '{order.get('status')}', expected 'pending'."
            }), 409

        # Simulate ToyyibPay callback
        from app.services.subscription_payment_callback_service import (
            process_subscription_payment_callback,
        )

        result = process_subscription_payment_callback(
            order_reference=reference,
            payment_reference=f"dev-{uuid.uuid4().hex[:16]}",
            gateway_order_id=f"dev-{uuid.uuid4().hex[:16]}",
        )

        return jsonify({
            "status": "success",
            "message": "DEV: Order completed (simulated callback).",
            "result": result,
        }), 200

    except Exception:
        logger.exception("DEV route failed for order %s", reference)
        return jsonify({
            "status": "error",
            "message": "DEV route processing failed."
        }), 500
