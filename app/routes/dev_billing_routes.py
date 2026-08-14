"""dev_billing_routes.py — Development-only billing routes.

This blueprint is registered only when ENABLE_DEV_BILLING_ROUTES is true.
It must never be available in production.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from flask import Blueprint, current_app, jsonify, g, request
from app.decorators.auth_decorator import token_required

logger = logging.getLogger(__name__)

dev_billing_bp = Blueprint("dev_billing", __name__, url_prefix="/api/billing/dev")


def _is_debug_enabled() -> bool:
    return os.getenv("FLASK_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")


def _synthetic_gateway_order_id(reference: str) -> str:
    return f"DEV_TEST_PAYMENT:{reference}"


def _dev_billing_enabled_response():
    if current_app.config.get("ENABLE_DEV_BILLING_ROUTES") and _is_debug_enabled():
        return None
    return jsonify({
        "status": "error",
        "message": "This endpoint is only available in development billing mode."
    }), 404


@dev_billing_bp.route("/subscription-orders/prepare", methods=["POST"])
@token_required
def dev_prepare_subscription_order():
    """DEV ONLY: Create a pending subscription order without ToyyibPay."""
    gate_response = _dev_billing_enabled_response()
    if gate_response:
        return gate_response

    try:
        company_id = g.company_id
        user_id = g.user_id
        if not company_id or not user_id:
            return jsonify({
                "status": "error",
                "message": "Company or user not found in authentication token."
            }), 401

        payload = request.get_json(silent=True) or {}
        plan_code = payload.get("plan_code")
        if not isinstance(plan_code, str) or not plan_code.strip():
            return jsonify({
                "status": "error",
                "message": "plan_code is required."
            }), 400

        from app.services.subscription_checkout_service import (
            prepare_subscription_checkout_order,
        )

        result = prepare_subscription_checkout_order(
            company_id=company_id,
            user_id=user_id,
            plan_code=plan_code,
            allow_existing_reusable_checkout=False,
        )

        return jsonify({
            "status": "success",
            "message": "DEV: Subscription order prepared without payment gateway.",
            "data": {
                "order_reference": result.get("order_reference"),
                "amount_sen": result.get("amount_sen"),
                "plan_code": result.get("plan_code"),
                "plan_id": result.get("plan_id"),
                "subscription_id": result.get("subscription_id"),
                "activation_type": result.get("activation_type"),
                "activation_sequence_key": result.get("activation_sequence_key"),
                "expires_at": result.get("expires_at"),
                "status": "pending",
                "gateway_order_id": None,
                "checkout_url": None,
            },
        }), 201
    except ValueError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 400
    except Exception:
        logger.exception("DEV prepare subscription order failed")
        return jsonify({
            "status": "error",
            "message": "DEV route processing failed."
        }), 500


@dev_billing_bp.route("/subscription-orders/<reference>/complete", methods=["POST"])
@token_required
def dev_complete_subscription_order(reference):
    """DEV ONLY: Complete a pending subscription order without real payment.

    This endpoint simulates a successful ToyyibPay callback by reusing the
    production process_subscription_payment_callback() flow.
    """
    try:
        gate_response = _dev_billing_enabled_response()
        if gate_response:
            return gate_response

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

        payment_gateway = (order.get("payment_gateway") or "").strip().lower()
        amount_sen = order.get("amount_sen")
        if (
            payment_gateway != "toyyibpay"
            or isinstance(amount_sen, bool)
            or not isinstance(amount_sen, int)
            or amount_sen <= 0
            or not order.get("subscription_id")
            or not order.get("new_plan_id")
        ):
            return jsonify({
                "status": "error",
                "message": "Subscription order is incomplete and cannot be completed by the dev route."
            }), 409

        gateway_order_id = (order.get("gateway_order_id") or "").strip()
        if not gateway_order_id:
            gateway_order_id = _synthetic_gateway_order_id(reference)
            order = update_subscription_order_status(
                reference,
                "pending",
                gateway_order_id=gateway_order_id,
            )

        # Simulate ToyyibPay callback
        from app.services.subscription_payment_callback_service import (
            process_subscription_payment_callback,
        )

        callback_payload = {
            "payment_gateway": "toyyibpay",
            "gateway_order_id": gateway_order_id,
            "payment_reference": "DEV_TEST_PAYMENT",
            "paid": True,
            "amount_sen": amount_sen,
            "paid_at": datetime.now(timezone.utc).isoformat(),
        }

        result = process_subscription_payment_callback(callback_payload)

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
