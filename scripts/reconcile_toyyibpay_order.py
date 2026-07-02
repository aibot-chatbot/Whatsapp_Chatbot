#!/usr/bin/env python3
"""One-time guarded reconciliation script for a successful ToyyibPay payment.

This script should be run ONLY when the callback webhook failed to process
a payment that the customer has already completed.

It fetches the transaction details from the ToyyibPay Get Bill Transactions API,
normalizes the response into the same callback structure the webhook expects,
and calls process_topup_payment_callback() to safely apply credit through
the normal service path.

It NEVER directly updates Supabase tables or grants credit bypassing
the callback service.
"""

import os
import sys
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Malaysia is UTC+8 (no tzdata/zoneinfo dependency required)
MALAYSIA_TZ = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Safety checks before any application import
# ---------------------------------------------------------------------------


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        print(f"ERROR: {var_name} is required.", file=sys.stderr)
        sys.exit(1)
    return value


def _require_production_env() -> None:
    env = os.getenv("TOYYIBPAY_ENV", "").strip().lower()
    if env != "production":
        print(
            f"ERROR: TOYYIBPAY_ENV must be 'production', got {env!r}.",
            file=sys.stderr,
        )
        sys.exit(1)


def _require_confirmation() -> None:
    confirm = os.getenv("CONFIRM_TOYYIBPAY_RECONCILE", "").strip()
    if confirm != "YES":
        print(
            "ERROR: Set CONFIRM_TOYYIBPAY_RECONCILE=YES to proceed.",
            file=sys.stderr,
        )
        sys.exit(1)


def _print_warning() -> None:
    print("=" * 72)
    print("  WARNING: This script will make a LIVE request to")
    print("  ToyyibPay production API using your Secret Key.")
    print()
    print("  It will then call the normal callback-processing service")
    print("  to grant AI credit for the matched order.")
    print()
    print("  This processes an existing paid transaction and may grant AI credit.")
    print("  It does not create a new bill or charge the customer again.")
    print("=" * 72)
    print()


def main(reconciliation_service=None):
    """Run the guarded reconciliation flow.

    Args:
        reconciliation_service: Optional replacement for testing.
            If omitted, imports the real toyiybpay and callback services.
    """
    load_dotenv()
    _require_confirmation()
    _require_production_env()

    order_reference = _require_env("RECONCILE_ORDER_REFERENCE")
    bill_code = _require_env("RECONCILE_BILL_CODE")

    _print_warning()

    if reconciliation_service is None:
        reconciliation_service = _reconcile_with_live_api

    result = reconciliation_service(order_reference, bill_code)
    _print_safe_result(result)
    return result


def _reconcile_with_live_api(order_reference: str, bill_code: str) -> dict:
    """Fetch ToyyibPay transaction and process it through callback service."""
    from app.services.ai_credit_topup_callback_service import (
        process_topup_payment_callback,
    )
    from app.services.toyyibpay_service import ToyyibPayConfig, ToyyibPayConfigError
    import requests

    # Load and validate config
    try:
        config = ToyyibPayConfig()
    except ToyyibPayConfigError as exc:
        print(f"ERROR: ToyyibPay configuration failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not config.secret_key:
        print("ERROR: TOYYIBPAY_USER_SECRET_KEY is not configured.", file=sys.stderr)
        sys.exit(1)

    # Call Get Bill Transactions API
    url = f"{config.base_url}/index.php/api/getBillTransactions"
    payload = {
        "userSecretKey": config.secret_key,
        "billCode": bill_code,
    }

    print(f"Fetching ToyyibPay transaction for bill code {bill_code}...")
    try:
        response = requests.post(url, data=payload, timeout=30)
    except requests.RequestException as exc:
        print(f"ERROR: API request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        print(
            f"ERROR: API returned HTTP {response.status_code}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = response.json()
    except ValueError as exc:
        print(f"ERROR: API returned non-JSON response: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list) or len(data) == 0:
        print(
            f"ERROR: API returned empty or unexpected response: {data!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    transaction = data[0]

    # Validate the transaction
    _validate_transaction(transaction, order_reference, bill_code)

    # Normalize to callback structure
    normalized = _normalize_transaction(transaction, bill_code)

    # Process through the normal callback service
    print("Processing through callback service...")
    result = process_topup_payment_callback(normalized)
    return result


def _validate_transaction(transaction: dict, expected_order_ref: str, expected_bill_code: str) -> None:
    """Validate the transaction matches expectations.

    The requested bill_code was already sent as the POST parameter.
    The API response does not include billCode, so we validate
    against the expected value passed by the caller.

    Real response fields used:
    - billExternalReferenceNo: must match the expected order reference
    - billpaymentStatus: must be "1" (successful)
    - billpaymentInvoiceNo: must be present (becomes payment_reference)
    """
    ext_ref = (transaction.get("billExternalReferenceNo") or "").strip()

    if ext_ref != expected_order_ref:
        print(
            f"ERROR: Transaction external reference {ext_ref!r} "
            f"does not match expected order {expected_order_ref!r}.",
            file=sys.stderr,
        )
        sys.exit(1)

    billpayment_status = (transaction.get("billpaymentStatus") or "").strip()
    if billpayment_status != "1":
        print(
            f"ERROR: Transaction status is {billpayment_status!r}, "
            f"expected '1' (successful).",
            file=sys.stderr,
        )
        sys.exit(1)

    invoice_no = (transaction.get("billpaymentInvoiceNo") or "").strip()
    if not invoice_no:
        print(
            "ERROR: Transaction has no billpaymentInvoiceNo.",
            file=sys.stderr,
        )
        sys.exit(1)


def _parse_toyyibpay_date(raw_date: str) -> str:
    """Parse ToyyibPay billPaymentDate (DD/MM/YYYY) into ISO 8601 timestamp.

    ToyyibPay returns dates in DD/MM/YYYY format, e.g.
    "02/07/2026 14:14:29" or "02/07/2026 02:14:29 PM".

    Args:
        raw_date: Raw date string from ToyyibPay API.

    Returns:
        ISO 8601 timezone-aware timestamp string,
        e.g. "2026-07-02T06:14:29+00:00" for 02/07/2026 14:14:29 MYT.

    Raises:
        SystemExit: If the date cannot be parsed.
    """
    cleaned = raw_date.strip()
    if not cleaned:
        return ""

    # Expected formats from ToyyibPay
    formats = [
        "%d/%m/%Y %H:%M:%S",      # 02/07/2026 14:14:29
        "%d/%m/%Y %I:%M:%S %p",   # 02/07/2026 02:14:29 PM
        "%d/%m/%Y",                # 02/07/2026
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            # ToyyibPay timestamps are in Malaysia time (UTC+8)
            local_dt = dt.replace(tzinfo=MALAYSIA_TZ)
            utc_dt = local_dt.astimezone(timezone.utc)
            return utc_dt.isoformat()
        except ValueError:
            continue

    print(
        f"ERROR: Unable to parse ToyyibPay date {raw_date!r}. "
        f"Expected DD/MM/YYYY format.",
        file=sys.stderr,
    )
    sys.exit(1)

def _normalize_transaction(transaction: dict, expected_bill_code: str) -> dict:
    """Normalize a Get Bill Transactions response into callback structure.

    Uses the real API response field names:
    - billExternalReferenceNo
    - billpaymentInvoiceNo
    - billpaymentAmount
    - billPaymentDate
    - billpaymentStatus

    The gateway_order_id comes from the expected_bill_code parameter
    because the API response does not include billCode.
    """
    ext_ref = (transaction.get("billExternalReferenceNo") or "").strip()
    invoice_no = (transaction.get("billpaymentInvoiceNo") or "").strip()
    status = "1"
    amount_raw = transaction.get("billpaymentAmount")
    raw_date = (transaction.get("billPaymentDate") or "").strip()
    payment_date = _parse_toyyibpay_date(raw_date)

    # Parse amount using Decimal
    try:
        amount_str = str(amount_raw).strip() if amount_raw else ""
        if not amount_str:
            print("ERROR: Missing billpaymentAmount in transaction.", file=sys.stderr)
            sys.exit(1)
        d = Decimal(amount_str)
        amount_cent = int(d * 100)
    except (InvalidOperation, ValueError, TypeError) as exc:
        print(f"ERROR: Invalid billpaymentAmount {amount_raw!r}: {exc}", file=sys.stderr)
        sys.exit(1)

    # Build the same normalized structure as parse_verified_callback
    result = {
        "payment_gateway": "toyyibpay",
        "gateway_order_id": expected_bill_code,
        "order_reference": ext_ref,
        "payment_reference": invoice_no,
        "paid": True,
        "gateway_status": status,
        "amount_sen": amount_cent,
        "paid_total_micro_myr": amount_cent * 10000,
        "paid_at": payment_date,
        "failure_reason": None,
    }
    return result


def _print_safe_result(result: dict) -> None:
    """Print only safe fields from the callback service result."""
    safe_fields = [
        "status",
        "order_status",
        "order_reference",
        "gateway_order_id",
        "payment_reference",
        "credit_transaction_id",
        "idempotent",
    ]
    print()
    print("=" * 72)
    print("  RECONCILIATION RESULT")
    print("=" * 72)
    for field in safe_fields:
        if field in result:
            print(f"  {field}: {result[field]}")
    print("=" * 72)


if __name__ == "__main__":
    main()
