"""Retired fake-payment endpoints. Use the verified CHIP sandbox flow."""

from flask import Blueprint, jsonify
from app.decorators.auth_decorator import token_required

dev_billing_bp = Blueprint("dev_billing", __name__, url_prefix="/api/billing/dev")

@dev_billing_bp.post("/subscription-orders/prepare")
@dev_billing_bp.post("/subscription-orders/<reference>/complete")
@token_required
def retired_payment_simulation(reference=None):
    return jsonify(status="error", message="Use CHIP test checkout to verify payment. Simulated entitlement grants are disabled."), 410
