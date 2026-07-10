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

        data = {
            "order_reference": order.get("order_reference"),
            "status": order.get("status"),
            "amount_sen": order.get("amount_sen"),
            "plan_id": order.get("new_plan_id"),
            "payment_gateway": order.get("payment_gateway"),
            "created_at": order.get("created_at"),
            "paid_at": order.get("paid_at"),
            "credited_at": order.get("credited_at"),
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
