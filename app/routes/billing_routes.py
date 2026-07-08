import logging
import re

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
import uuid
from app.services.ai_credit_topup_checkout_service import (
    create_toyyibpay_topup_checkout,
)
from app.services.ai_access_policy import resolve_ai_access
from app.database.user_repository import get_user_by_id
from app.database.ai_credit_topup_order_repository import get_topup_order_by_reference_and_company

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
        logging.exception("Failed to list plans")
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
        logging.exception("Failed to fetch subscription")
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
        logging.exception("Failed to fetch usage")
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

        limit = request.args.get("limit", 20)
        if isinstance(limit, str):
            if not limit.isdigit():
                return jsonify({
                    "status": "error",
                    "message": "limit must be a positive integer."
                }), 400
            limit = int(limit)
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
                "ai_usage_type": txn.get("ai_usage_type"),
                "included_delta_micro_myr": txn.get("included_delta_micro_myr"),
                "topup_delta_micro_myr": txn.get("topup_delta_micro_myr"),
                "included_balance_after_micro_myr": txn.get("included_balance_after_micro_myr"),
                "topup_balance_after_micro_myr": txn.get("topup_balance_after_micro_myr"),
                "customer_charge_micro_myr": txn.get("customer_charge_micro_myr"),
                "uncovered_charge_micro_myr": txn.get("uncovered_charge_micro_myr"),
                "ai_usage_log_id": txn.get("ai_usage_log_id"),
                "order_reference": txn.get("order_reference"),
                "description": txn.get("description"),
                "created_at": txn.get("created_at"),
            })

        return jsonify({
            "status": "success",
            "data": {
                "transactions": safe_transactions,
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


# ---------------------------------------------------------------------------
# ToyyibPay AI-credit top-up checkout
# ---------------------------------------------------------------------------

@billing_bp.route("/toyyibpay/checkout", methods=["POST"])
@token_required
def toyyibpay_checkout():
    """Create a ToyyibPay bill for AI-credit top-up.

    Resolves company_id, user_id, customer name, and email from the
    authenticated JWT token.  Never accepts company_id from request body.
    """
    try:
        company_id = g.company_id
        user_id = g.user_id

        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        if not user_id:
            return jsonify({
                "status": "error",
                "message": "User not found in authentication token."
            }), 401

        # ------------------------------------------------------------------
        # Parse and validate request body
        # ------------------------------------------------------------------
        body = request.get_json(silent=True)
        if not body:
            return jsonify({
                "status": "error",
                "message": "Request body must be valid JSON."
            }), 400

        amount = body.get("amount_micro_myr")

        if isinstance(amount, bool):
            return jsonify({
                "status": "error",
                "message": "amount_micro_myr must be an integer, got boolean."
            }), 400

        if not isinstance(amount, int):
            return jsonify({
                "status": "error",
                "message": "amount_micro_myr must be a positive integer."
            }), 400

        if amount < 1:
            return jsonify({
                "status": "error",
                "message": "amount_micro_myr must be positive."
            }), 400

        if amount % 10000 != 0:
            return jsonify({
                "status": "error",
                "message": "amount_micro_myr must be divisible by 10000."
            }), 400

        if amount < 1010000:
            return jsonify({
                "status": "error",
                "message": "amount_micro_myr must be at least 1010000 (RM1.01)."
            }), 400

        # ------------------------------------------------------------------
        # Resolve authenticated user details
        # ------------------------------------------------------------------
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({
                "status": "error",
                "message": "Authenticated user not found."
            }), 401

        customer_name = (user.get("full_name") or user.get("email") or str(user_id)).strip()
        customer_phone = user.get("phone") or None
        customer_email = (user.get("email") or "").strip()
        if not customer_email:
            return jsonify({
                "status": "error",
                "message": "Authenticated user has no email."
            }), 400


        # Validate phone before proceeding
        if not customer_phone:
            return jsonify({
                "status": "error",
                "message": "A valid phone number is required before creating a ToyyibPay checkout."
            }), 400
        stripped_phone = re.sub(r"[\s\-\(\)]", "", customer_phone)
        if not re.match(r"^\+?\d+$", stripped_phone):
            return jsonify({
                "status": "error",
                "message": "A valid phone number is required before creating a ToyyibPay checkout."
            }), 400
        digits_phone = stripped_phone.lstrip("+")
        if len(digits_phone) < 8 or len(digits_phone) > 15:
            return jsonify({
                "status": "error",
                "message": "A valid phone number is required before creating a ToyyibPay checkout."
            }), 400

        # Resolve subscription_id
        subscription = get_current_subscription(company_id)
        subscription_id = (subscription or {}).get("id")
        if not subscription_id:
            return jsonify({
                "status": "error",
                "message": "Company has no active subscription."
            }), 400

        # Check AI access policy for top-up eligibility
        policy = resolve_ai_access(company_id)
        if not policy.top_up_allowed:
            return jsonify({
                "status": "error",
                "message": policy.denial_reason or "AI credit top-up is not available on your current plan.",
            }), 403

        # ------------------------------------------------------------------
        # Create the checkout
        # ------------------------------------------------------------------
        idempotency_key = str(uuid.uuid4())

        result = create_toyyibpay_topup_checkout(
            company_id=company_id,
            subscription_id=subscription_id,
            created_by_user_id=user_id,
            amount_micro_myr=amount,
            customer_email=customer_email,
            customer_name=customer_name,
            idempotency_key=idempotency_key,
            customer_phone=customer_phone,
        )

        return jsonify({
            "status": "success",
            "data": result,
        }), 201

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 400

    except Exception:
        logging.exception("ToyyibPay checkout creation failed")
        return jsonify({
            "status": "error",
            "message": "Unable to create checkout. Please try again later.",
        }), 500

@billing_bp.route('/toyyibpay/orders/<order_reference>', methods=['GET'])
@token_required
def toyyibpay_order_status(order_reference):
    """Return the status of an AI-credit top-up order.

    The order is looked up by its internal UUID reference and scoped
    to the authenticated company.
    """
    try:
        company_id = g.company_id

        if not company_id:
            return jsonify({
                'status': 'error',
                'message': 'Company not found in authentication token.'
            }), 401

        # Validate UUID format
        try:
            uuid.UUID(order_reference)
        except (ValueError, AttributeError):
            return jsonify({
                'status': 'error',
                'message': 'Invalid order reference format.'
            }), 400

        # Look up the order scoped to the authenticated company
        order = get_topup_order_by_reference_and_company(
            order_reference=order_reference,
            company_id=company_id,
        )

        if order is None:
            return jsonify({
                'status': 'error',
                'message': 'Order not found.'
            }), 404

        # Compute the credited flag from stored status
        is_credited = order.get('status') == 'credited'

        # Build safe response
        data = {
            'order_reference': order.get('order_reference'),
            'status': order.get('status'),
            'amount_micro_myr': order.get('amount_micro_myr'),
            'currency': order.get('currency', 'MYR'),
            'payment_gateway': order.get('payment_gateway'),
            'credited': is_credited,
            'created_at': order.get('created_at'),
            'paid_at': order.get('paid_at'),
            'credited_at': order.get('credited_at'),
        }

        return jsonify({
            'status': 'success',
            'data': data,
        }), 200

    except ValueError as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
        }), 400

    except Exception:
        logging.exception('Failed to fetch top-up order status')
        return jsonify({
            'status': 'error',
            'message': 'Unable to retrieve order status.'
        }), 500
