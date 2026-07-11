import logging
import re

from flask import Blueprint, jsonify, g, request

import csv
import io
from datetime import datetime
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
from app.services.subscription_checkout_service import (
    create_subscription_checkout,
)
from app.services.ai_access_policy import resolve_ai_access
from app.database.subscription_plan_repository import get_plan_by_code as _get_plan_by_code
from app.database.user_repository import get_user_by_id
from app.database.ai_credit_topup_order_repository import get_topup_order_by_reference_and_company
from app.services.subscription_lifecycle_service import (
    schedule_cancellation as _schedule_cancellation,
    clear_scheduled_cancellation as _clear_scheduled_cancellation,
    undo_subscription_cancellation as _undo_subscription_cancellation,
    schedule_subscription_downgrade as _schedule_downgrade,
    clear_scheduled_downgrade as _clear_scheduled_downgrade,
)
from app.database.subscription_plan_repository import get_plan_by_code as _get_plan_by_code_v2
from app.database.subscription_plan_repository import get_plan_by_id as _get_plan_by_id



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



@billing_bp.route("/subscription/renewal-status", methods=["GET"])
@token_required
def fetch_subscription_renewal_status():
    """Return renewal status, grace period, and pending renewal info.

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

        from app.services.subscription_lifecycle_service import get_subscription_renewal_status

        renewal_status = get_subscription_renewal_status(company_id)

        return jsonify({
            "status": "success",
            "data": renewal_status
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception:
        logging.exception("Failed to fetch renewal status")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve renewal information."
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


@billing_bp.route("/subscription/checkout", methods=["POST"])
@token_required
def subscription_checkout():
    """Create a subscription payment checkout (ToyyibPay bill).

    Request body:
        plan_code: Required, lowercase plan code ("essential", "advanced", "pro").

    Response:
        order_reference: UUID string for the created order.
        checkout_url:    ToyyibPay payment page URL.
        amount_sen:      Amount billed in sen.

    Does not activate the subscription or grant AI credits.
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

        body = request.get_json(silent=True)
        if not body:
            return jsonify({
                "status": "error",
                "message": "Request body must be valid JSON."
            }), 400

        plan_code = body.get("plan_code", "").strip()
        if not plan_code:
            return jsonify({
                "status": "error",
                "message": "plan_code is required."
            }), 400

        # Resolve authenticated user details
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

        result = create_subscription_checkout(
            company_id=company_id,
            user_id=user_id,
            plan_code=plan_code,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
        )

        return jsonify({
            "status": "success",
            "data": {
                "order_reference": result["order_reference"],
                "checkout_url": result["checkout_url"],
                "amount_sen": result["amount_sen"],
            },
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 400

    except RuntimeError as e:
        logging.error("Subscription checkout failed: %s", e)
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 502

    except Exception:
        logging.exception("Unexpected error creating subscription checkout")
        return jsonify({
            "status": "error",
            "message": "Unable to create checkout. Please try again later."
        }), 500
@billing_bp.route("/subscription/orders", methods=["GET"])
@token_required
def list_subscription_orders():
    """Return paginated subscription order history for the authenticated company.

    This is a read-only endpoint. It never modifies subscription data.
    The company_id is taken from the authenticated JWT token only.
    """
    try:
        company_id = g.company_id

        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        limit_arg = request.args.get("limit", 20)
        if isinstance(limit_arg, str):
            if not limit_arg.isdigit():
                return jsonify({"status": "error", "message": "limit must be a positive integer."}), 400
            limit_arg = int(limit_arg)
            if limit_arg < 1:
                return jsonify({"status": "error", "message": "limit must be a positive integer."}), 400
            if limit_arg > 100:
                limit_arg = 100

        offset_arg = request.args.get("offset", 0)
        if isinstance(offset_arg, str):
            if not offset_arg.isdigit():
                return jsonify({"status": "error", "message": "offset must be a non-negative integer."}), 400
            offset_arg = int(offset_arg)
            if offset_arg < 0:
                return jsonify({"status": "error", "message": "offset must be a non-negative integer."}), 400

        status_filter = request.args.get("status")
        valid_statuses = {"pending", "paid", "failed", "expired", "credited"}
        if status_filter and status_filter not in valid_statuses:
            return jsonify({
                "status": "error",
                "message": f"Invalid status filter. Valid values: {', '.join(sorted(valid_statuses))}."
            }), 400

        from app.database.company_subscription_order_repository import (
            list_subscription_orders_for_company,
        )
        from app.database.subscription_plan_repository import get_plan_by_id

        from app.database.company_subscription_order_repository import list_subscription_orders_for_company
        orders = list_subscription_orders_for_company(
            company_id=company_id,
            limit=limit_arg,
            offset=offset_arg,
            status=status_filter,
        )

        safe_orders = []
        for order in orders:
            plan = get_plan_by_id(order.get("new_plan_id"))
            activation_status = order.get("activation_status")
            activation_error_code = order.get("activation_error_code")
            safe_message = _safe_activation_message(activation_status, activation_error_code)
            retry_allowed = (
                order.get("status") in ("paid",)
                or activation_status in ("not_started", "claimed", "activated", "credit_pending", "failed")
            )
            safe_orders.append({
                "order_reference": order.get("order_reference"),
                "plan": {
                    "id": plan.get("id") if plan else None,
                    "code": plan.get("code") if plan else None,
                    "name": plan.get("name") if plan else None,
                } if plan else None,
                "amount_sen": order.get("amount_sen"),
                "currency": "MYR",
                "payment_status": order.get("status"),
                "activation_status": activation_status,
                "customer_status_message": safe_message,
                "created_at": order.get("created_at"),
                "paid_at": order.get("paid_at"),
                "credited_at": order.get("credited_at"),
                "expires_at": order.get("expires_at"),
                "payment_reference": order.get("payment_reference"),
                "gateway_order_id": order.get("gateway_order_id"),
                "retry_allowed": retry_allowed,
                "reconciliation_required": order.get("reconciliation_required", False),
            })

        has_more = len(orders) >= limit_arg

        return jsonify({
            "status": "success",
            "data": {
                "orders": safe_orders,
                "pagination": {
                    "limit": limit_arg,
                    "offset": offset_arg,
                    "has_more": has_more,
                },
            },
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 400

    except Exception:
        logging.exception("Failed to list subscription orders")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve order history."
        }), 500



@billing_bp.route("/subscription/orders/<reference>", methods=["GET"])
@token_required
def fetch_subscription_order_status(reference):
    """Return the status of a subscription order.

    This is a read-only endpoint used for payment return polling.
    It never modifies the subscription or grants credits.
    The company_id is taken from the authenticated JWT token only.
    """
    try:
        company_id = g.company_id

        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        # Validate UUID format
        try:
            uuid.UUID(reference)
        except (ValueError, AttributeError):
            return jsonify({
                "status": "error",
                "message": "Invalid order reference format."
            }), 400

        from app.database.company_subscription_order_repository import (
            get_subscription_order_by_reference_and_company,
        )

        order = get_subscription_order_by_reference_and_company(
            order_reference=reference,
            company_id=company_id,
        )

        if order is None:
            return jsonify({
                "status": "error",
                "message": "Order not found."
            }), 404

        activation_status = order.get("activation_status")
        activation_error_code = order.get("activation_error_code")
        reconciliation_required = order.get("reconciliation_required", False)
        safe_message = _safe_activation_message(activation_status, activation_error_code)
        retry_allowed = (
            order.get("status") in ("paid",)
            or activation_status in ("not_started", "claimed", "activated", "credit_pending", "failed")
        )
        from app.database.subscription_plan_repository import get_plan_by_id as _get_plan_by_id_ref
        plan_ref = _get_plan_by_id_ref(order.get("new_plan_id"))
        data = {
            "order_reference": order.get("order_reference"),
            "status": order.get("status"),
            "amount_sen": order.get("amount_sen"),
            "amount_myr": (order.get("amount_sen") or 0) / 100,
            "plan": {
                "id": plan_ref.get("id") if plan_ref else None,
                "code": plan_ref.get("code") if plan_ref else None,
                "name": plan_ref.get("name") if plan_ref else None,
            } if plan_ref else None,
            "plan_id": order.get("new_plan_id"),
            "payment_gateway": order.get("payment_gateway"),
            "payment_reference": order.get("payment_reference"),
            "gateway_order_id": order.get("gateway_order_id"),
            "created_at": order.get("created_at"),
            "paid_at": order.get("paid_at"),
            "credited_at": order.get("credited_at"),
            "expires_at": order.get("expires_at"),
            "activation_status": activation_status,
            "activation_claimed_at": order.get("activation_claimed_at"),
            "activation_completed_at": order.get("activation_completed_at"),
            "credit_granted_at": order.get("credit_granted_at"),
            "currency": "MYR",
            "reconciliation_required": reconciliation_required,
            "activation_error_code": activation_error_code,
            "retry_allowed": retry_allowed,
            "message": safe_message,
    }

        return jsonify({
            "status": "success",
            "data": data,
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 400

    except Exception:
        logging.exception("Failed to fetch subscription order status")
        return jsonify({
            "status": "error",
            "message": "Unable to retrieve order status."
        }), 500


def _safe_activation_message(activation_status, activation_error_code):
    if activation_status is None or activation_status == "not_started":
        return "Payment confirmed. Subscription activation is in progress."
    if activation_status == "claimed":
        return "Payment confirmed. Subscription activation is in progress."
    if activation_status == "activated":
        return "Subscription activated. AI credit allocation is being processed."
    if activation_status == "credit_pending":
        return "Payment confirmed. Completing activation..."
    if activation_status == "completed":
        return "Subscription activation completed."
    if activation_status == "conflict":
        return "This payment needs support review. Please contact support with your order reference."
    if activation_status == "failed":
        return "This payment needs support review. Please contact support with your order reference."
    return "Payment confirmed."



@billing_bp.route("/subscription/orders/<order_reference>/receipt", methods=["GET"])
@token_required
def subscription_order_receipt(order_reference):
    """Return a customer-facing payment receipt as JSON.

    This is not a tax invoice. It shows the verified payment details
    from the payment gateway callback and the subscription order record.
    """
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({"status": "error", "message": "Company not found."}), 401

        try:
            uuid.UUID(order_reference)
        except (ValueError, AttributeError):
            return jsonify({"status": "error", "message": "Invalid order reference format."}), 400

        from app.database.company_subscription_order_repository import (
            get_subscription_order_by_reference_and_company,
        )
        from app.database.subscription_plan_repository import get_plan_by_id

        order = get_subscription_order_by_reference_and_company(
            order_reference=order_reference,
            company_id=company_id,
        )

        if order is None:
            return jsonify({"status": "error", "message": "Order not found."}), 404

        plan = get_plan_by_id(order.get("new_plan_id"))

        receipt = {
            "company_id": company_id,
            "order_reference": order.get("order_reference"),
            "plan": {
                "id": plan.get("id") if plan else None,
                "code": plan.get("code") if plan else None,
                "name": plan.get("name") if plan else None,
            } if plan else None,
            "amount_sen": order.get("amount_sen"),
            "amount_myr": (order.get("amount_sen") or 0) / 100,
            "currency": "MYR",
            "payment_status": order.get("status"),
            "activation_status": order.get("activation_status"),
            "payment_reference": order.get("payment_reference"),
            "gateway_reference": order.get("gateway_order_id"),
            "payment_date": order.get("paid_at"),
            "created_at": order.get("created_at"),
            "credited_at": order.get("credited_at"),
            "billing_period_start": order.get("source_period_start"),
            "billing_period_end": order.get("source_period_end"),
        }

        return jsonify({
            "status": "success",
            "data": {
                "receipt": receipt,
                "notice": "This is a payment receipt, not a tax invoice.",
            },
        }), 200

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    except Exception:
        logging.exception("Failed to generate subscription order receipt")
        return jsonify({"status": "error", "message": "Unable to generate receipt."}), 500

@billing_bp.route("/subscription/orders/<order_reference>/retry", methods=["POST"])
@token_required
def retry_subscription_order(order_reference):
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({"status": "error", "message": "Company not found."}), 401
        from app.services.subscription_reconciliation_service import reconcile_subscription_order
        result = reconcile_subscription_order(order_reference=order_reference, company_id=company_id)
        outcome = result.get("outcome")
        order_status = result.get("order_status")
        if outcome in ("reconciled_and_completed", "credit_retry_completed"):
            return jsonify({"status": "success", "data": {"outcome": outcome, "order_status": order_status}}), 200
        if outcome == "already_completed":
            return jsonify({"status": "success", "data": {"outcome": outcome, "order_status": order_status}}), 200
        if outcome in ("activation_already_claimed", "source_subscription_changed"):
            return jsonify({"status": "error", "code": outcome, "message": result.get("message", "This payment needs support review.")}), 409
        if outcome == "manual_review_required":
            return jsonify({"status": "error", "code": "manual_review_required", "message": "This payment requires support review."}), 409
        if outcome == "malformed_order":
            return jsonify({"status": "error", "code": "malformed_order", "message": "This order has incomplete data. Support review required."}), 409
        if outcome == "unpaid_order_not_reconcilable":
            return jsonify({"status": "error", "code": "unpaid_order", "message": "This order has not been paid and cannot be retried."}), 400
        return jsonify({"status": "error", "code": "unknown_outcome", "message": "Unexpected reconciliation result."}), 500
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception:
        logging.exception("Failed to retry subscription order")
        return jsonify({"status": "error", "message": "Unable to retry order."}), 500


@billing_bp.route("/dev/subscription-orders/<reference>/complete", methods=["POST"])
@token_required
def dev_complete_subscription_order(reference):
    """DEV ONLY: Complete a pending subscription order without real payment.

    This endpoint is only available when FLASK_DEBUG is set to a truthy value.
    It simulates a successful ToyyibPay callback by reusing the production
    process_subscription_payment_callback() flow.
    """
    import os
    debug_val = os.getenv("FLASK_DEBUG", "0").strip().lower()
    if debug_val not in ("1", "true", "yes", "on"):
        return jsonify({
            "status": "error",
            "message": "This endpoint is only available in development mode."
        }), 403

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

        if order is None:
            return jsonify({
                "status": "error",
                "message": "Order not found."
            }), 404

        order_status = order.get("status", "")
        if order_status in ("failed", "expired", "cancelled"):
            return jsonify({
                "status": "error",
                "message": f"Order has status '{order_status}' and cannot be completed."
            }), 400

        if order_status == "credited":
            return jsonify({
                "status": "success",
                "data": {
                    "order_reference": reference,
                    "subscription_status": "already_activated",
                    "plan": order.get("new_plan_id"),
                    "message": "Order is already credited. Subscription was previously activated."
                },
            }), 200

        gateway_order_id = order.get("gateway_order_id", "") or reference

        if not order.get("gateway_order_id"):
            update_subscription_order_status(
                reference, order_status,
                gateway_order_id=reference,
            )
            gateway_order_id = reference

        from app.services.subscription_payment_callback_service import (
            process_subscription_payment_callback,
        )

        callback_payload = {
            "payment_gateway": "toyyibpay",
            "gateway_order_id": gateway_order_id,
            "payment_reference": "DEV_TEST_PAYMENT",
            "paid": True,
            "amount_sen": order.get("amount_sen", 0),
        }

        result = process_subscription_payment_callback(callback_payload)

        return jsonify({
            "status": "success",
            "data": {
                "order_reference": result.get("order_reference", reference),
                "subscription_status": result.get("status"),
                "plan": result.get("plan_code"),
                "message": (
                    "Subscription activated successfully (DEV completion)."
                    if result.get("status") == "activated"
                    else "Subscription was already activated."
                ),
            },
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 400

    except RuntimeError as e:
        logging.error("DEV subscription order completion failed: %s", e)
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 502

    except Exception:
        logging.exception("Unexpected error completing subscription order in dev mode")
        return jsonify({
            "status": "error",
            "message": "Unable to complete order. Please try again later."
        }), 500
@billing_bp.route("/subscription/downgrade-check/<target_plan_code>", methods=["GET"])
@token_required
def subscription_downgrade_check(target_plan_code):
    return _subscription_downgrade_check(target_plan_code)

@billing_bp.route("/subscription/cancel", methods=["POST"])
@token_required
def cancel_subscription():
    try:
        company_id = g.company_id
        if not company_id:
            return (jsonify({"status": "error", "message": "Company not found in authentication token."}), 401)
        result = _schedule_cancellation(company_id=company_id)
        return (jsonify({"status": "success", "data": {"cancellation_scheduled": True, "cancellation_effective_at": result.get("cancellation_effective_at"), "cancellation_scheduled_at": result.get("cancellation_scheduled_at"), "plan_id": result.get("plan_id")}}), 200)
    except ValueError as e:
        return (jsonify({"status": "error", "message": str(e)}), 409)
    except Exception:
        logging.exception("Failed to cancel subscription")
        return (jsonify({"status": "error", "message": "Unable to process cancellation."}), 500)

@billing_bp.route("/subscription/undo-cancel", methods=["POST"])
@token_required
def undo_cancel_subscription():
    try:
        company_id = g.company_id
        if not company_id:
            return (jsonify({"status": "error", "message": "Company not found in authentication token."}), 401)
        result = _undo_subscription_cancellation(company_id=company_id)
        return (jsonify({"status": "success", "data": {"cancellation_undone": True, "cancellation_scheduled_at": result.get("cancellation_scheduled_at"), "cancellation_effective_at": result.get("cancellation_effective_at")}}), 200)
    except ValueError as e:
        return (jsonify({"status": "error", "message": str(e)}), 409)
    except Exception:
        logging.exception("Failed to undo cancellation")
        return (jsonify({"status": "error", "message": "Unable to process undo cancellation."}), 500)

@billing_bp.route("/subscription/downgrade", methods=["POST"])
@token_required
def schedule_downgrade():
    try:
        company_id = g.company_id
        if not company_id:
            return (jsonify({"status": "error", "message": "Company not found in authentication token."}), 401)
        data = request.get_json(silent=True) or {}
        target_code = (data.get("target_plan_code") or "").strip().lower()
        if not target_code:
            return (jsonify({"status": "error", "message": "target_plan_code is required."}), 400)
        valid_paid = {"essential": 1, "advanced": 2, "pro": 3}
        if target_code not in valid_paid:
            return (jsonify({"status": "error", "message": "Invalid downgrade target. Only Essential, Advanced or Pro are valid targets."}), 400)
        target_plan = _get_plan_by_code(target_code)
        if not target_plan or not target_plan.get("is_active", False):
            return (jsonify({"status": "error", "message": f"Plan '{target_code}' is not available."}), 400)
        target_plan_id = target_plan["id"]
        result = _schedule_downgrade(company_id=company_id, target_plan_id=target_plan_id)
        return (jsonify({"status": "success", "data": {"downgrade_scheduled": True, "target_plan": target_code, "plan_change_effective_at": result.get("plan_change_effective_at")}}), 200)
    except ValueError as e:
        return (jsonify({"status": "error", "message": str(e)}), 409)
    except Exception:
        logging.exception("Failed to schedule downgrade")
        return (jsonify({"status": "error", "message": "Unable to schedule downgrade."}), 500)

@billing_bp.route("/subscription/downgrade", methods=["DELETE"])
@token_required
def clear_downgrade():
    try:
        company_id = g.company_id
        if not company_id:
            return (jsonify({"status": "error", "message": "Company not found in authentication token."}), 401)
        result = _clear_scheduled_downgrade(company_id=company_id)
        return (jsonify({"status": "success", "data": {"downgrade_cleared": True, "pending_plan_id": result.get("pending_plan_id"), "plan_change_effective_at": result.get("plan_change_effective_at")}}), 200)
    except ValueError as e:
        return (jsonify({"status": "error", "message": str(e)}), 409)
    except Exception:
        logging.exception("Failed to clear scheduled downgrade")
        return (jsonify({"status": "error", "message": "Unable to clear downgrade schedule."}), 500)


def _subscription_downgrade_check(target_plan_code):
    """Check whether the company can downgrade to a lower paid plan.

    Returns eligibility, current usage vs target limits, and any blocking
    items. This is a read-only endpoint and never modifies the subscription.

    Only paid plans (essential, advanced, pro) are valid downgrade targets.
    Free is not a valid target. The current plan must be higher-ranked than
    the target.
    """
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({
                "status": "error",
                "message": "Company not found in authentication token."
            }), 401

        target_code = (target_plan_code or "").strip().lower()
        valid_paid = {"essential": 1, "advanced": 2, "pro": 3}
        plan_rank = {"free": 0, "essential": 1, "advanced": 2, "pro": 3}

        if target_code not in valid_paid:
            return jsonify({
                "status": "error",
                "message": "Invalid downgrade target. Only Essential, Advanced or Pro are valid targets."
            }), 400

        target_plan = _get_plan_by_code(target_code)
        if not target_plan or not target_plan.get("is_active", False):
            return jsonify({
                "status": "error",
                "message": f"Plan '{target_code}' is not available."
            }), 400

        subscription = get_current_subscription(company_id)
        if not subscription:
            return jsonify({
                "status": "error",
                "message": "No active subscription found."
            }), 404

        current_plan = subscription.get("plan") or {}
        current_code = (current_plan.get("code") or "").lower()

        if current_code not in plan_rank:
            return jsonify({
                "status": "error",
                "message": "Current plan is not recognised."
            }), 400

        current_rank = plan_rank[current_code]
        target_rank = plan_rank[target_code]

        if target_rank >= current_rank:
            return jsonify({
                "status": "error",
                "message": f"Target plan '{target_code}' is not lower than current plan '{current_code}'."
            }), 400

        # Get current usage
        usage = get_company_usage(company_id)
        u = usage.get("usage", {}) if usage else {}

        # Target plan limits
        target_limits = {
            "chatbots": target_plan.get("chatbot_limit"),
            "team_members": target_plan.get("team_member_limit"),
            "knowledge_files": target_plan.get("knowledge_file_limit"),
            "knowledge_storage_bytes": target_plan.get("knowledge_storage_limit_bytes"),
            "channels": target_plan.get("channel_limit"),
        }

        # Build blocking items
        blocking_items = []

        def _check(label, used_key, limit_key, inner_key=None):
            u_data = u.get(used_key) or {}
            used = u_data.get(inner_key or "used", 0) or 0
            limit = target_limits.get(limit_key)
            if limit is not None and used > limit:
                blocking_items.append({
                    "resource": label,
                    "used": used,
                    "limit": limit,
                    "excess": used - limit,
                })

        _check("chatbots", "chatbots", "chatbots")
        _check("team_members", "team_members", "team_members")
        _check("knowledge_files", "knowledge_files", "knowledge_files")
        _check("knowledge_storage_bytes", "knowledge_storage_bytes", "knowledge_storage_bytes")
        _check("channels", "channels", "channels")

        # Include pending invitations in team usage
        pending_invites = u.get("team_members", {}).get("pending_invitations", 0) or 0
        team_used = (u.get("team_members", {}).get("used", 0) or 0) + pending_invites
        tm_limit = target_limits.get("team_members")
        if tm_limit is not None and team_used > tm_limit:
            blocking_items.append({
                "resource": "team_members_including_pending",
                "used": team_used,
                "limit": tm_limit,
                "excess": team_used - tm_limit,
            })

        # Effective date (end of current period)
        effective_at = subscription.get("current_period_end")
        eligible = len(blocking_items) == 0

        return jsonify({
            "status": "success",
            "data": {
                "eligible": eligible,
                "target_plan": target_code,
                "effective_at": effective_at,
                "blocking_items": blocking_items,
                "message": "Downgrade is available." if eligible else "Downgrade is blocked by usage that exceeds the target plan limits.",
            },
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 400

    except Exception:
        logging.exception("Failed to check downgrade eligibility")
        return jsonify({
            "status": "error",
            "message": "Unable to check downgrade eligibility."
        }), 500

# =============================================================================
# Phase 4H — Printable receipt, CSV exports, and usage summary
# =============================================================================


@billing_bp.route("/subscription/orders/<order_reference>/receipt/print", methods=["GET"])
@token_required
def printable_subscription_receipt(order_reference):
    """Return a printable HTML payment receipt.

    This is not a tax invoice. It shows the verified payment details
    from the payment gateway callback and the subscription order record.
    """
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({"status": "error", "message": "Company not found."}), 401

        try:
            import uuid
            uuid.UUID(order_reference)
        except (ValueError, AttributeError):
            return jsonify({"status": "error", "message": "Invalid order reference format."}), 400

        from app.services.billing_receipt_service import build_subscription_receipt

        receipt = build_subscription_receipt(company_id, order_reference)
        if receipt is None:
            return jsonify({"status": "error", "message": "Order not found."}), 404

        plan = receipt.get("plan") or {}
        plan_name = plan.get("name") or "N/A"
        order_ref = receipt.get("order_reference") or ""
        amount = receipt.get("amount_myr") or 0
        currency = receipt.get("currency", "MYR")
        payment_status = receipt.get("payment_status") or ""
        activation_status = receipt.get("activation_status") or ""
        payment_ref = receipt.get("payment_reference") or ""
        gateway_ref = receipt.get("gateway_reference") or ""
        created_at = receipt.get("created_at") or ""
        paid_at = receipt.get("payment_date") or ""
        credited_at = receipt.get("credited_at") or ""
        notice = receipt.get("notice", "")

        def _safe(s):
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Payment Receipt - {_safe(order_ref)}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #1a1a1a; padding: 20px; }}
  .receipt-container {{ max-width: 680px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); overflow: hidden; }}
  .receipt-header {{ background: linear-gradient(135deg, #1e3a5f, #2563eb); color: #fff; padding: 28px 32px; }}
  .receipt-header h1 {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 4px; }}
  .receipt-header p {{ font-size: 0.85rem; opacity: 0.85; }}
  .receipt-body {{ padding: 28px 32px; }}
  .receipt-notice {{ background: #fef3c7; border: 1px solid #fde68a; border-radius: 8px; padding: 12px 16px; font-size: 0.82rem; color: #92400e; margin-bottom: 24px; }}
  .detail-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e5e7eb; font-size: 0.88rem; }}
  .detail-row:last-child {{ border-bottom: none; }}
  .detail-label {{ color: #6b7280; font-weight: 500; }}
  .detail-value {{ color: #1a1a1a; font-weight: 600; text-align: right; }}
  .amount-value {{ font-size: 1.2rem; color: #059669; }}
  .section-title {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; color: #9ca3af; margin: 20px 0 10px; }}
  .receipt-footer {{ padding: 20px 32px; background: #f9fafb; border-top: 1px solid #e5e7eb; font-size: 0.78rem; color: #9ca3af; text-align: center; line-height: 1.5; }}
  .btn-row {{ display: flex; gap: 12px; margin-top: 20px; justify-content: center; }}
  .btn {{ display: inline-flex; align-items: center; gap: 6px; padding: 10px 24px; border-radius: 8px; font-size: 0.88rem; font-weight: 600; cursor: pointer; border: none; text-decoration: none; }}
  .btn-primary {{ background: #2563eb; color: #fff; }}
  .btn-primary:hover {{ background: #1d4ed8; }}
  .btn-secondary {{ background: #e5e7eb; color: #374151; }}
  .btn-secondary:hover {{ background: #d1d5db; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .receipt-container {{ box-shadow: none; border-radius: 0; }}
    .btn-row {{ display: none; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="receipt-container">
  <div class="receipt-header">
    <h1>Payment Receipt</h1>
    <p>AI Chatbot Platform</p>
  </div>
  <div class="receipt-body">
    <div class="receipt-notice">{_safe(notice)}</div>

    <div class="section-title">Order Details</div>
    <div class="detail-row"><span class="detail-label">Plan</span><span class="detail-value">{_safe(plan_name)}</span></div>
    <div class="detail-row"><span class="detail-label">Amount</span><span class="detail-value amount-value">{currency} {amount:.2f}</span></div>
    <div class="detail-row"><span class="detail-label">Order Reference</span><span class="detail-value" style="font-family:monospace;font-size:0.8rem;">{_safe(order_ref)}</span></div>

    <div class="section-title">Status</div>
    <div class="detail-row"><span class="detail-label">Payment Status</span><span class="detail-value">{_safe(payment_status)}</span></div>
    <div class="detail-row"><span class="detail-label">Activation Status</span><span class="detail-value">{_safe(activation_status)}</span></div>

    <div class="section-title">Payment Details</div>
    <div class="detail-row"><span class="detail-label">Payment Reference</span><span class="detail-value" style="font-family:monospace;font-size:0.8rem;">{_safe(payment_ref)}</span></div>
    <div class="detail-row"><span class="detail-label">Gateway Reference</span><span class="detail-value" style="font-family:monospace;font-size:0.8rem;">{_safe(gateway_ref)}</span></div>
"""

        if created_at:
            html += f"""    <div class="detail-row"><span class="detail-label">Order Created</span><span class="detail-value">{_safe(created_at)}</span></div>\n"""
        if paid_at:
            html += f"""    <div class="detail-row"><span class="detail-label">Payment Date</span><span class="detail-value">{_safe(paid_at)}</span></div>\n"""
        if credited_at:
            html += f"""    <div class="detail-row"><span class="detail-label">Credit Date</span><span class="detail-value">{_safe(credited_at)}</span></div>\n"""

        html += """    <div class="section-title">Billing Period</div>
    <div class="detail-row"><span class="detail-label">Period Start</span><span class="detail-value">{}</span></div>
    <div class="detail-row"><span class="detail-label">Period End</span><span class="detail-value">{}</span></div>
""".format(
    _safe(receipt.get("billing_period_start") or ""),
    _safe(receipt.get("billing_period_end") or ""),
)

        html += """    <div class="btn-row no-print">
      <button class="btn btn-primary" onclick="window.print()">Print / Save PDF</button>
      <button class="btn btn-secondary" onclick="window.close()">Close</button>
    </div>
  </div>
  <div class="receipt-footer">
    Generated {gen_date}<br>
    For support, contact us with your order reference.
  </div>
</div>
</body>
</html>""".format(gen_date=_safe(receipt.get("generated_at", "")))

        from flask import make_response
        resp = make_response(html)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception:
        logging.exception("Failed to generate printable receipt")
        return jsonify({"status": "error", "message": "Unable to generate receipt."}), 500


@billing_bp.route("/subscription/orders/export.csv", methods=["GET"])
@token_required
def export_subscription_orders_csv():
    """Export company subscription orders as CSV."""
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({"status": "error", "message": "Company not found."}), 401

        limit_str = request.args.get("limit", "500")
        try:
            export_limit = min(int(limit_str), 2000)
        except (ValueError, TypeError):
            export_limit = 500
        if export_limit < 1:
            export_limit = 500

        from app.database.company_subscription_order_repository import list_subscription_orders_for_company
        orders = list_subscription_orders_for_company(
            company_id=company_id,
            limit=export_limit,
            offset=0,
        )

        from app.services.billing_receipt_service import _neutralize_csv

        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow([
            "order_date", "payment_date", "plan", "amount_myr", "currency",
            "payment_status", "activation_status", "order_reference",
            "payment_reference", "gateway_reference",
        ])
        for o in orders:
            plan = o.get("plan") or {}
            plan_name = _neutralize_csv(plan.get("name"))
            writer.writerow([
                _neutralize_csv(o.get("created_at")),
                _neutralize_csv(o.get("paid_at")),
                plan_name,
                f"{(o.get('amount_sen') or 0) / 100:.2f}",
                "MYR",
                _neutralize_csv(o.get("status")),
                _neutralize_csv(o.get("activation_status")),
                _neutralize_csv(o.get("order_reference")),
                _neutralize_csv(o.get("payment_reference")),
                _neutralize_csv(o.get("gateway_order_id")),
            ])

        csv_data = output.getvalue()
        output.close()

        from flask import make_response
        resp = make_response(csv_data)
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = f"attachment; filename=subscription-payment-history-{datetime.now().strftime('%Y-%m-%d')}.csv"
        return resp

    except Exception:
        logging.exception("Failed to export subscription orders CSV")
        return jsonify({"status": "error", "message": "Unable to export data."}), 500


@billing_bp.route("/ai-credit/transactions/export.csv", methods=["GET"])
@token_required
def export_ai_credit_transactions_csv():
    """Export company AI-credit transactions as CSV."""
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({"status": "error", "message": "Company not found."}), 401

        limit_str = request.args.get("limit", "500")
        try:
            export_limit = min(int(limit_str), 2000)
        except (ValueError, TypeError):
            export_limit = 500
        if export_limit < 1:
            export_limit = 500

        txns = list_credit_transactions(company_id, limit=export_limit)

        from app.services.billing_receipt_service import _neutralize_csv, _micro_myr_to_myr

        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow([
            "date", "transaction_type", "included_delta_myr", "topup_delta_myr",
            "total_delta_myr", "included_balance_after_myr", "topup_balance_after_myr",
            "total_balance_after_myr", "description", "payment_reference",
        ])
        for t in txns:
            inc_delta = t.get("included_delta_micro_myr") or 0
            top_delta = t.get("topup_delta_micro_myr") or 0
            inc_after = t.get("included_balance_after_micro_myr") or 0
            top_after = t.get("topup_balance_after_micro_myr") or 0
            writer.writerow([
                _neutralize_csv(t.get("created_at")),
                _neutralize_csv(t.get("transaction_type")),
                _micro_myr_to_myr(inc_delta),
                _micro_myr_to_myr(top_delta),
                _micro_myr_to_myr(inc_delta + top_delta),
                _micro_myr_to_myr(inc_after),
                _micro_myr_to_myr(top_after),
                _micro_myr_to_myr(inc_after + top_after),
                _neutralize_csv(t.get("description")),
                _neutralize_csv(t.get("payment_reference")),
            ])

        csv_data = output.getvalue()
        output.close()

        from flask import make_response
        resp = make_response(csv_data)
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = f"attachment; filename=ai-credit-activity-{datetime.now().strftime('%Y-%m-%d')}.csv"
        return resp

    except Exception:
        logging.exception("Failed to export AI-credit CSV")
        return jsonify({"status": "error", "message": "Unable to export data."}), 500


@billing_bp.route("/ai-credit/usage-summary", methods=["GET"])
@token_required
def get_ai_credit_usage_summary():
    """Return an AI-credit usage summary for the current billing period."""
    try:
        company_id = g.company_id
        if not company_id:
            return jsonify({"status": "error", "message": "Company not found."}), 401

        from app.database.ai_credit_repository import get_company_credit_balance
        balance = get_company_credit_balance(company_id)
        if not balance:
            return jsonify({
                "status": "success",
                "data": {
                    "period": {"start": None, "end": None},
                    "balances": {"included_myr": 0, "topup_myr": 0, "total_myr": 0},
                    "activity": {
                        "included_granted_myr": 0, "included_expired_myr": 0,
                        "topup_added_myr": 0, "usage_spent_myr": 0, "adjustments_myr": 0,
                    },
                    "transaction_count": 0,
                },
            }), 200

        period_start = balance.get("period_start")
        period_end = balance.get("period_end")
        included_bal = balance.get("included_balance_micro_myr") or 0
        topup_bal = balance.get("topup_balance_micro_myr") or 0

        included_granted = 0
        included_expired = 0
        topup_added = 0
        usage_spent = 0
        adjustments = 0

        txns = list_credit_transactions(company_id, limit=500)
        txn_count = 0
        for t in txns:
            txn_count += 1
            ttype = (t.get("transaction_type") or "").strip().lower()
            inc_delta = t.get("included_delta_micro_myr") or 0
            top_delta = t.get("topup_delta_micro_myr") or 0
            if ttype == "subscription_included":
                included_granted += inc_delta
            elif ttype == "topup":
                topup_added += top_delta
            elif ttype == "usage":
                usage_spent += abs(inc_delta) + abs(top_delta)
            elif ttype == "expiry":
                included_expired += abs(inc_delta)
            elif ttype in ("adjustment", "reversal"):
                adjustments += inc_delta + top_delta

        from app.services.billing_receipt_service import _micro_myr_to_myr

        return jsonify({
            "status": "success",
            "data": {
                "period": {
                    "start": period_start,
                    "end": period_end,
                },
                "balances": {
                    "included_myr": _micro_myr_to_myr(included_bal),
                    "topup_myr": _micro_myr_to_myr(topup_bal),
                    "total_myr": _micro_myr_to_myr(included_bal + topup_bal),
                },
                "activity": {
                    "included_granted_myr": _micro_myr_to_myr(included_granted),
                    "included_expired_myr": _micro_myr_to_myr(included_expired),
                    "topup_added_myr": _micro_myr_to_myr(topup_added),
                    "usage_spent_myr": _micro_myr_to_myr(usage_spent),
                    "adjustments_myr": _micro_myr_to_myr(adjustments),
                },
                "transaction_count": txn_count,
            },
        }), 200

    except Exception:
        logging.exception("Failed to generate AI-credit usage summary")
        return jsonify({"status": "error", "message": "Unable to generate usage summary."}), 500


@billing_bp.route("/health", methods=["GET"])
def billing_health_check():
    """Safe billing health check endpoint.

    Verifies that required environment variables and dependencies
    are available without exposing secret values.
    """
    try:
        import os
        checks = {
            "secret_key": bool(os.environ.get("SECRET_KEY")),
            "supabase_url": bool(os.environ.get("SUPABASE_URL")),
            "supabase_key": bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
            "toyyibpay_secret_key": bool(os.environ.get("TOYYIBPAY_USER_SECRET_KEY")),
            "toyyibpay_category_code": bool(os.environ.get("TOYYIBPAY_CATEGORY_CODE")),
        }

        from app.database.db import supabase
        supabase_ok = False
        try:
            supabase.table("subscription_plans").select("id").limit(1).execute()
            supabase_ok = True
        except Exception:
            pass
        checks["supabase_connectivity"] = supabase_ok

        from app.services.subscription_reconciliation_service import reconcile_subscription_order
        checks["reconciliation_service_loaded"] = callable(reconcile_subscription_order)

        all_ok = all(checks.values())
        return jsonify({
            "status": "ok" if all_ok else "degraded",
            "checks": {k: v for k, v in checks.items() if k != "supabase_key"},
        }), 200 if all_ok else 200

    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": "Health check failed: " + str(type(exc).__name__),
        }), 500
