import logging

from flask import Blueprint, jsonify, g, request

from app.decorators.auth_decorator import token_required
from app.services.billing_service import (
    list_active_plans,
    get_current_subscription,
    get_company_usage,
)
from app.services.ai_credit_service import (
    get_company_ai_credit_summary,
    list_credit_transactions,
)

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")


@billing_bp.route("/plans", methods=["GET"])
@token_required
def fetch_plans():
    """Return all active subscription plans available for selection."""
    try:
        plans = list_active_plans()

        return jsonify({
            "status": "success",
            "data": plans
        }), 200

    except Exception:
        logging.exception("Failed to fetch billing plans")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve billing information."
        }), 500


@billing_bp.route("/subscription", methods=["GET"])
@token_required
def fetch_subscription():
    """Return the current company subscription including plan details.

    The company_id is taken from the authenticated JWT token only.
    This endpoint never accepts company_id from query parameters or body.
    """
    try:
        company_id = g.company_id

        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        subscription = get_current_subscription(company_id)

        return jsonify({
            "status": "success",
            "data": subscription
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception:
        logging.exception("Failed to fetch company subscription")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve billing information."
        }), 500


@billing_bp.route("/usage", methods=["GET"])
@token_required
def fetch_usage():
    """Return current usage statistics for the authenticated company.

    The company_id is taken from the authenticated JWT token only.
    This endpoint never accepts company_id from query parameters or body.
    """
    try:
        company_id = g.company_id

        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        usage = get_company_usage(company_id)

        return jsonify({
            "status": "success",
            "data": usage
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception:
        logging.exception("Failed to fetch company usage")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve billing information."
        }), 500


@billing_bp.route("/ai-credit/summary", methods=["GET"])
@token_required
def fetch_ai_credit_summary():
    """Return the authenticated company AI-credit balance summary.

    This endpoint is read-only. It never initialises a credit period,
    modifies a balance, or charges usage.

    The company_id is taken from the authenticated JWT token only.
    This endpoint never accepts company_id from query parameters or body.
    """
    try:
        company_id = g.company_id

        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        summary = get_company_ai_credit_summary(company_id)

        return jsonify({
            "status": "success",
            "data": {
                "initialised": summary["initialised"],
                "subscription_id": summary.get("subscription_id"),
                "included_balance_micro_myr": summary.get("included_balance_micro_myr"),
                "topup_balance_micro_myr": summary.get("topup_balance_micro_myr"),
                "total_balance_micro_myr": summary.get("total_balance_micro_myr"),
                "period_start": summary.get("period_start"),
                "period_end": summary.get("period_end"),
                "currency": "MYR",
                "unit": "micro_myr",
            }
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception:
        logging.exception("Failed to fetch AI-credit summary")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve billing information."
        }), 500


@billing_bp.route("/ai-credit/transactions", methods=["GET"])
@token_required
def fetch_ai_credit_transactions():
    """Return AI-credit transaction history for the authenticated company.

    This endpoint is read-only. It never modifies any balance or ledger row.

    The company_id is taken from the authenticated JWT token only.
    This endpoint never accepts company_id from query parameters or body.
    """
    try:
        company_id = g.company_id

        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        raw_limit = request.args.get("limit", "50")

        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            return jsonify({
                "status": "error",
                "message": "limit must be a positive integer."
            }), 400

        if limit < 1:
            return jsonify({
                "status": "error",
                "message": "limit must be a positive integer."
            }), 400

        if limit > 100:
            return jsonify({
                "status": "error",
                "message": "limit must not exceed 100."
            }), 400

        transactions = list_credit_transactions(company_id, limit=limit)

        safe_transactions = []
        for txn in transactions:
            safe_transactions.append({
                "id": txn.get("id"),
                "transaction_type": txn.get("transaction_type"),
                "included_delta_micro_myr": txn.get("included_delta_micro_myr"),
                "topup_delta_micro_myr": txn.get("topup_delta_micro_myr"),
                "included_balance_after_micro_myr": txn.get("included_balance_after_micro_myr"),
                "topup_balance_after_micro_myr": txn.get("topup_balance_after_micro_myr"),
                "customer_charge_micro_myr": txn.get("customer_charge_micro_myr"),
                "uncovered_charge_micro_myr": txn.get("uncovered_charge_micro_myr"),
                "ai_usage_log_id": txn.get("ai_usage_log_id"),
                "reversal_of_transaction_id": txn.get("reversal_of_transaction_id"),
                "period_start": txn.get("period_start"),
                "period_end": txn.get("period_end"),
                "description": txn.get("description"),
                "created_at": txn.get("created_at"),
            })

        return jsonify({
            "status": "success",
            "data": {
                "transactions": safe_transactions,
                "count": len(safe_transactions),
                "limit": limit,
                "currency": "MYR",
                "unit": "micro_myr",
            }
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception:
        logging.exception("Failed to fetch AI-credit transactions")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve billing information."
        }), 500
