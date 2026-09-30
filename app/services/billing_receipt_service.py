"""
billing_receipt_service.py - Canonical receipt-building helpers.
"""

import csv
import io
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

from app.database.company_subscription_order_repository import (
    get_subscription_order_by_reference_and_company,
    list_subscription_orders_for_company,
)
from app.database.ai_credit_topup_order_repository import get_topup_order_by_reference_and_company
from app.database.company_repository import get_company_by_id
from app.database.subscription_plan_repository import get_plan_by_id
from app.database.user_repository import get_company_billing_contact, get_company_user_contact
from app.database.ai_credit_repository import (
    get_company_credit_balance,
    list_company_credit_transactions as _list_txns,
)
from app.services.receipt_email_service import (
    format_micro_myr,
    format_paid_at,
    format_sen,
    is_single_mailbox,
    send_receipt_email,
)

logger = logging.getLogger(__name__)

_CSV_INJECTION_CHARS = frozenset([chr(61), chr(43), chr(45), chr(64)])
RECEIPT_NOTICE = "This is a payment receipt, not a tax invoice."


def _neutralize_csv(value):
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in _CSV_INJECTION_CHARS:
        return "'" + s
    return s


def build_subscription_receipt(company_id, order_reference):
    """Build a canonical receipt dictionary from an order."""
    order = get_subscription_order_by_reference_and_company(
        order_reference, company_id,
    )
    if order is None:
        return None
    return _receipt_from_order(order, company_id)


def _receipt_from_order(order, company_id):
    plan = get_plan_by_id(order.get("new_plan_id"))
    plan_data = None
    if plan:
        plan_data = {"id": plan.get("id"), "code": plan.get("code"), "name": plan.get("name")}
    return {
        "company_id": company_id,
        "order_reference": order.get("order_reference"),
        "plan": plan_data,
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
        "notice": RECEIPT_NOTICE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _receipt_recipients(purchaser, owner):
    """Return (to, cc) contacts: the purchaser, with the owner copied when it is someone else.

    A contact whose address is not a single plain mailbox counts as unreachable.
    With no reachable purchaser the owner becomes the recipient instead, so a
    paid order is never left without a receipt just because one user was
    deactivated or has a bad address.
    """
    buyer = purchaser if purchaser and is_single_mailbox(purchaser.get("email")) else None
    boss = owner if owner and is_single_mailbox(owner.get("email")) else None
    if buyer is None:
        return boss, None
    if boss is not None and boss["email"].lower() != buyer["email"].lower():
        return buyer, boss
    return buyer, None


def _send_receipt(company_id, order, order_reference, item_rows, summary):
    """Work out who gets this order's receipt, then send it. Shared by plan and top-up receipts."""
    to, cc = _receipt_recipients(
        get_company_user_contact(order.get("created_by_user_id"), company_id),
        get_company_billing_contact(company_id),
    )
    if to is None:
        logger.info("Receipt email skipped for order %s: no reachable recipient", order_reference)
        return False
    company = get_company_by_id(company_id) or {}
    base = (os.getenv("FRONTEND_URL") or "").rstrip("/")
    rows = [
        ("Receipt for order", order_reference),
        ("Billed to", company.get("company_name") or "your workspace"),
        *item_rows,
        ("Payment reference", order.get("payment_reference")),
    ]
    return send_receipt_email(
        to["email"],
        order_reference=order_reference,
        rows=rows,
        recipient_name=to["full_name"],
        summary=summary,
        notice=RECEIPT_NOTICE,
        cc_email=cc["email"] if cc else None,
        action_url=(base + "/billing.html") if base else None,
    )


def email_subscription_receipt(company_id, order_reference):
    """Email the purchaser a receipt for a paid subscription order.

    Returns True when the message is handed to the SMTP server. Never raises:
    the payment is already recorded, and a mail or lookup failure must not
    disturb the callback that triggered this. The order is fetched by reference
    AND company, so a reference from another tenant finds nothing.
    """
    try:
        order = get_subscription_order_by_reference_and_company(order_reference, company_id)
        if order is None:
            logger.warning("Receipt email skipped: order %s not found for company %s", order_reference, company_id)
            return False
        receipt = _receipt_from_order(order, company_id)
        item_rows = [
            ("Plan", (receipt.get("plan") or {}).get("name") or "Subscription"),
            ("Amount paid", format_sen(receipt.get("amount_sen"))),
            # paid_at can be stored empty (chip_service writes ""), so fall back to the credit time.
            ("Paid on", format_paid_at(receipt.get("payment_date") or receipt.get("credited_at"))),
        ]
        return _send_receipt(
            company_id, order, order_reference, item_rows,
            "your payment was received and your plan is active.",
        )
    except Exception as exc:
        logger.warning("Receipt email failed for order %s: %s", order_reference, type(exc).__name__)
        return False


def email_topup_receipt(company_id, order_reference):
    """Email the purchaser a receipt for a credited AI-credit top-up. Same contract as above."""
    try:
        order = get_topup_order_by_reference_and_company(order_reference, company_id)
        if order is None:
            logger.warning("Top-up receipt skipped: order %s not found for company %s", order_reference, company_id)
            return False
        amount = format_micro_myr(order.get("amount_micro_myr"))
        item_rows = [
            ("Item", "AI credit top-up"),
            ("Amount paid", amount),
            ("AI credit added", amount),
            ("Paid on", format_paid_at(order.get("paid_at") or order.get("credited_at"))),
        ]
        return _send_receipt(
            company_id, order, order_reference, item_rows,
            "your payment was received and the AI credit has been added to your workspace.",
        )
    except Exception as exc:
        logger.warning("Top-up receipt failed for order %s: %s", order_reference, type(exc).__name__)
        return False


def _micro_myr_to_myr(micro):
    if micro is None:
        return "0.00"
    from decimal import Decimal
    return f"{Decimal(micro) / 1000000:.2f}"
