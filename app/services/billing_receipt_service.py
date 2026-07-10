"""
billing_receipt_service.py - Canonical receipt-building helpers.
"""

import csv
import io
import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.database.company_subscription_order_repository import (
    get_subscription_order_by_reference_and_company,
    list_subscription_orders_for_company,
)
from app.database.subscription_plan_repository import get_plan_by_id
from app.database.ai_credit_repository import (
    get_company_credit_balance,
    list_company_credit_transactions as _list_txns,
)

logger = logging.getLogger(__name__)

_CSV_INJECTION_CHARS = frozenset([chr(61), chr(43), chr(45), chr(64)])


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
        "notice": "This is a payment receipt, not a tax invoice.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

def _micro_myr_to_myr(micro):
    if micro is None:
        return "0.00"
    from decimal import Decimal
    return f"{Decimal(micro) / 1000000:.2f}"
