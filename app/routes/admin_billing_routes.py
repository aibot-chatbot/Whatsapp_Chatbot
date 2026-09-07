"""
admin_billing_routes.py

Protected billing support endpoints for company owners and administrators.

All endpoints require authenticated company-owner/admin role.
Cross-company access is NOT available because no platform-admin role exists.
Platform-admin endpoints are intentionally deferred until a secure
server-side authorization framework is implemented.

Current authorization model:
- JWT role values: "admin", "owner", "member"
- Company owners/admins can access their own company's billing data
- Normal members and unauthenticated requests are denied
- No platform-level admin role exists in the current schema
"""

import logging

from flask import Blueprint, jsonify, g, request

from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.database.company_subscription_order_repository import (
    get_subscription_order_by_reference_and_company,
    list_subscription_orders_for_company,
    list_subscription_orders_for_support,
    find_subscription_order_for_support,
)
from app.database.ai_credit_repository import (
    get_company_credit_balance,
    list_company_credit_transactions,
)
from app.services.subscription_reconciliation_service import (
    reconcile_subscription_order,
)
from app.utils.admin_audit_logger import log_admin_action

logger = logging.getLogger(__name__)

admin_billing_bp = Blueprint("admin_billing", __name__, url_prefix="/api/admin/billing")


# =============================================================================
# Company-scoped support routes (for company owner/admin)
# =============================================================================


@admin_billing_bp.route("/orders", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_admin_orders():
    """List subscription orders for the current company with optional filters."""
    company_id = g.company_id
    try:
        limit = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid pagination parameters"}), 400

    payment_status = request.args.get("payment_status") or None
    activation_status = request.args.get("activation_status") or None
    reconciliation_raw = request.args.get("reconciliation_required")
    reconciliation_required = None
    if reconciliation_raw and reconciliation_raw.lower() in ("true", "1", "yes"):
        reconciliation_required = True
    elif reconciliation_raw and reconciliation_raw.lower() in ("false", "0", "no"):
        reconciliation_required = False

    if payment_status or activation_status or reconciliation_required is not None:
        orders = list_subscription_orders_for_support(
            company_id=company_id,
            payment_status=payment_status,
            activation_status=activation_status,
            reconciliation_required=reconciliation_required,
            limit=limit,
            offset=offset,
        )
    else:
        orders = list_subscription_orders_for_company(
            company_id=company_id,
            limit=limit,
            offset=offset,
        )

    log_admin_action(
        action="list_orders",
        actor_user_id=g.user_id,
        target_company_id=company_id,
        result="success",
    )

    safe_orders = [_safe_order(o) for o in orders]
    return jsonify({
        "status": "success",
        "data": {
            "orders": safe_orders,
            "count": len(safe_orders),
        },
    }), 200


@admin_billing_bp.route("/orders/<order_reference>", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_admin_order_detail(order_reference):
    """Get detailed order information for the current company."""
    company_id = g.company_id
    order = get_subscription_order_by_reference_and_company(order_reference, company_id)

    if not order:
        return jsonify({"status": "error", "message": "Order not found"}), 404

    log_admin_action(
        action="view_order",
        actor_user_id=g.user_id,
        target_company_id=company_id,
        order_reference=order_reference,
        result="success",
    )

    return jsonify({
        "status": "success",
        "data": _safe_order(order),
    }), 200


@admin_billing_bp.route("/orders/<order_reference>/reconcile", methods=["POST"])
@token_required
@role_required("admin", "owner")
def admin_reconcile_order(order_reference):
    """Reconcile a paid-but-incomplete subscription order for the current company.

    This endpoint uses the same canonical reconciliation service as the
    customer retry endpoint.  It does NOT bypass payment confirmation,
    activation atomicity, or included-credit idempotency.

    Reconciliation is idempotent: already-completed orders return success.
    """
    company_id = g.company_id

    result = reconcile_subscription_order(
        order_reference=order_reference,
        company_id=company_id,
        force=False,
    )

    outcome = result.get("outcome", "unknown")
    success_outcomes = {"reconciled_and_completed", "credit_retry_completed",
                        "already_completed", "activation_retry_completed"}

    log_admin_action(
        action="reconcile_order",
        actor_user_id=g.user_id,
        target_company_id=company_id,
        order_reference=order_reference,
        result=outcome,
    )

    if outcome in success_outcomes:
        return jsonify({
            "status": "success",
            "data": {
                "outcome": outcome,
                "order_status": result.get("order_status"),
                "message": result.get("message", "Reconciliation completed."),
            },
        }), 200

    if outcome == "manual_review_required":
        return jsonify({
            "status": "error",
            "code": "manual_review_required",
            "message": result.get("message", "This payment requires support review."),
        }), 409

    return jsonify({
        "status": "error",
        "code": outcome,
        "message": result.get("message", "Reconciliation could not be completed."),
    }), 400


# =============================================================================
# Company AI-credit support inspection (company owner/admin)
# =============================================================================


@admin_billing_bp.route("/ai-credit", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_admin_credit_summary():
    """Get the current company's AI-credit balance summary."""
    company_id = g.company_id
    balance = get_company_credit_balance(company_id)

    if not balance:
        return jsonify({
            "status": "error",
            "message": "AI credit not found for this company.",
        }), 404

    log_admin_action(
        action="view_credit_summary",
        actor_user_id=g.user_id,
        target_company_id=company_id,
        result="success",
    )

    return jsonify({
        "status": "success",
        "data": {
            "company_id": company_id,
            "included_balance_micro_myr": balance.get("included_balance_micro_myr", 0),
            "topup_balance_micro_myr": balance.get("topup_balance_micro_myr", 0),
            "total_balance_micro_myr": balance.get("total_balance_micro_myr", 0),
            "period_start": balance.get("period_start"),
            "period_end": balance.get("period_end"),
        },
    }), 200


@admin_billing_bp.route("/ai-credit/transactions", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_admin_credit_transactions():
    """Get recent AI-credit transactions for the current company."""
    company_id = g.company_id
    try:
        limit = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid pagination parameters"}), 400

    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    transactions = list_company_credit_transactions(company_id, limit=limit, offset=offset)

    log_admin_action(
        action="view_credit_transactions",
        actor_user_id=g.user_id,
        target_company_id=company_id,
        result="success",
    )

    safe_txns = []
    for t in transactions:
        safe_txns.append({
            "id": t.get("id"),
            "type": t.get("transaction_type"),
            "description": t.get("description"),
            "net_delta_micro_myr": t.get("net_delta_micro_myr"),
            "included_balance_after_micro_myr": t.get("included_balance_after_micro_myr"),
            "topup_balance_after_micro_myr": t.get("topup_balance_after_micro_myr"),
            "idempotency_key": t.get("idempotency_key"),
            "payment_reference": t.get("payment_reference"),
            "created_at": t.get("created_at"),
        })

    return jsonify({
        "status": "success",
        "data": {
            "transactions": safe_txns,
            "count": len(safe_txns),
        },
    }), 200


# =============================================================================
# Helpers
# =============================================================================


def _safe_order(order: dict) -> dict:
    """Build a safe order dictionary without exposing internal fields."""
    if not order:
        return {}
    plan = order.get("plan") or {}
    return {
        "order_reference": order.get("order_reference"),
        "company_id": order.get("company_id"),
        "plan": {
            "id": plan.get("id"),
            "code": plan.get("code"),
            "name": plan.get("name"),
        } if plan else {
            "id": order.get("new_plan_id"),
        },
        "amount_myr": (order.get("amount_sen") or 0) / 100,
        "payment_status": order.get("status"),
        "activation_status": order.get("activation_status"),
        "reconciliation_required": order.get("reconciliation_required", False),
        "reconciliation_attempt_count": order.get("reconciliation_attempt_count", 0),
        "created_at": order.get("created_at"),
        "paid_at": order.get("paid_at"),
        "credited_at": order.get("credited_at"),
        "payment_reference": order.get("payment_reference"),
        "payment_gateway": order.get("payment_gateway"),
        "gateway_order_id": order.get("gateway_order_id"),
        "retry_allowed": _retry_allowed(order),
        "customer_message": _customer_message(order),
    }


def _retry_allowed(order: dict) -> bool:
    """Determine whether a retry/reconciliation is allowed for this order."""
    status = (order.get("status") or "").strip().lower()
    act_status = (order.get("activation_status") or "").strip().lower()
    if status == "credited" and act_status == "completed":
        return False
    if status in ("paid",) or act_status in ("not_started", "claimed", "activated",
                                              "credit_pending"):
        return True
    if order.get("reconciliation_required"):
        return True
    return False


def _customer_message(order: dict) -> str | None:
    """Generate a customer-safe status message for this order."""
    status = (order.get("status") or "").strip().lower()
    act_status = (order.get("activation_status") or "").strip().lower()

    if act_status == "completed" and status == "credited":
        return None
    if act_status == "conflict":
        return "This payment needs support review."
    if order.get("reconciliation_required") or act_status == "credit_pending":
        return "Payment confirmed. Completing activation."
    if status == "paid" and act_status in ("not_started", "claimed"):
        return "Payment confirmed. Activating subscription."
    if status == "pending":
        return "Waiting for payment confirmation."
    if status == "failed":
        return "Payment failed."
    if status == "expired":
        return "Payment session expired."
    return None
