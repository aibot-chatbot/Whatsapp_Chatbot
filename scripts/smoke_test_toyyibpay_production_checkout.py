
"""smoke_test_toyyibpay_production_checkout.py -- Manual ToyyibPay production checkout script.

This script creates a pending AI-credit top-up order and a ToyyibPay bill
in PRODUCTION mode.  This creates a REAL bill.  Payment may involve real money.


Prerequisites:
- TOYYIBPAY_ENV=production
- TOYYIBPAY_USER_SECRET_KEY, TOYYIBPAY_CATEGORY_CODE must be set
- CONFIRM_TOYYIBPAY_PRODUCTION_TEST=YES
- All required SMOKE_TEST_* variables

Usage (PowerShell):
    $env:TOYYIBPAY_ENV="production"
    $env:CONFIRM_TOYYIBPAY_PRODUCTION_TEST="YES"
    $env:SMOKE_TEST_COMPANY_ID="<test-company-id>"
    $env:SMOKE_TEST_SUBSCRIPTION_ID="<test-subscription-id>"
    $env:SMOKE_TEST_USER_ID="<test-user-id>"
    $env:SMOKE_TEST_CUSTOMER_NAME="Test User"
    $env:SMOKE_TEST_CUSTOMER_EMAIL="test@example.com"
    $env:SMOKE_TEST_CUSTOMER_PHONE="+60123456789"
    $env:SMOKE_TEST_AMOUNT_MICRO_MYR="2000000"
    python scripts/smoke_test_toyyibpay_production_checkout.py

Requires activation of the project virtual environment.
"""

import os
import sys

from dotenv import load_dotenv
_CONFIRM_VAR = "CONFIRM_TOYYIBPAY_PRODUCTION_TEST"
_CONFIRM_EXPECTED = "YES"


def _is_confirmed() -> bool:
    return os.getenv(_CONFIRM_VAR, "").strip() == _CONFIRM_EXPECTED


def _require_confirmation() -> None:
    if not _is_confirmed():
        print("ERROR: {0} is not set to '{1}'.".format(_CONFIRM_VAR, _CONFIRM_EXPECTED))
        print("This script creates a REAL ToyyibPay bill in production mode.")
        print("It creates a real bill that may involve real money.")
        print("Set {0}={1} to confirm.".format(_CONFIRM_VAR, _CONFIRM_EXPECTED))
        sys.exit(1)


def _require_production_env() -> None:
    env = os.getenv("TOYYIBPAY_ENV", "").strip().lower()
    if env != "production":
        print("ERROR: TOYYIBPAY_ENV={0!r}. This script only runs with TOYYIBPAY_ENV=production.".format(env))
        sys.exit(1)


def _get_env_int(name: str) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise ValueError("{0} is required but not set".format(name))
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ValueError("{0} must be a valid integer, got {1!r}".format(name, raw))
    if value < 1:
        raise ValueError("{0} must be a positive integer, got {1}".format(name, value))
    return value


def _get_env_str(name: str, optional: bool = False) -> str | None:
    value = os.getenv(name, "").strip()
    if not value and not optional:
        raise ValueError("{0} is required but not set".format(name))
    return value if value else None


def _validate_amount(amount_micro_myr: int) -> None:
    if amount_micro_myr < 1:
        print("ERROR: SMOKE_TEST_AMOUNT_MICRO_MYR must be positive, got {0}".format(amount_micro_myr))
        sys.exit(1)
    if amount_micro_myr < 1010000:
        print("ERROR: SMOKE_TEST_AMOUNT_MICRO_MYR must be at least 1010000 (RM1.01).")
        print("Got {0} (RM{1:.2f}). Recommend 2000000 (RM2.00).".format(amount_micro_myr, amount_micro_myr / 1000000))
        sys.exit(1)
    if amount_micro_myr % 10000 != 0:
        print("ERROR: SMOKE_TEST_AMOUNT_MICRO_MYR must be divisible by 10000, got {0}".format(amount_micro_myr))
        sys.exit(1)


def _print_production_warning() -> None:
    print()
    print("=" * 64)
    print("  WARNING: PRODUCTION MODE")
    print("=" * 64)
    print("  This script will create a REAL ToyyibPay bill.")
    print("  Payment may involve REAL MONEY.")
    print("  Settlement may depend on your account verification.")
    print("  This is NOT a sandbox test.")
    print("=" * 64)
    print()


def main(checkout_service=None) -> None:
    load_dotenv()
    _require_confirmation()
    _require_production_env()
    _print_production_warning()

    company_id = _get_env_int("SMOKE_TEST_COMPANY_ID")
    subscription_id = _get_env_int("SMOKE_TEST_SUBSCRIPTION_ID")
    user_id = _get_env_int("SMOKE_TEST_USER_ID")
    customer_name = _get_env_str("SMOKE_TEST_CUSTOMER_NAME")
    customer_email = _get_env_str("SMOKE_TEST_CUSTOMER_EMAIL")
    customer_phone = _get_env_str("SMOKE_TEST_CUSTOMER_PHONE", optional=True)

    raw_amount = os.getenv("SMOKE_TEST_AMOUNT_MICRO_MYR", "").strip()
    if not raw_amount:
        print("ERROR: SMOKE_TEST_AMOUNT_MICRO_MYR is required.")
        print("Set SMOKE_TEST_AMOUNT_MICRO_MYR to the amount in micro-MYR.")
        print("Recommended: 2000000 (RM2.00). Minimum: 1010000 (RM1.01).")
        sys.exit(1)
    try:
        amount_micro_myr = int(raw_amount)
    except (ValueError, TypeError):
        print("ERROR: SMOKE_TEST_AMOUNT_MICRO_MYR must be a valid integer, got {0!r}".format(raw_amount))
        sys.exit(1)
    _validate_amount(amount_micro_myr)

    idempotency_key = "prod-smoke-test-{0}-{1}-{2}".format(
        company_id, subscription_id, os.urandom(4).hex()
    )

    if checkout_service is None:
        from app.services.ai_credit_topup_checkout_service import create_toyyibpay_topup_checkout
        checkout_service = create_toyyibpay_topup_checkout

    result = checkout_service(
        company_id=company_id,
        subscription_id=subscription_id,
        created_by_user_id=user_id,
        amount_micro_myr=amount_micro_myr,
        customer_email=customer_email,
        customer_name=customer_name,
        customer_phone=customer_phone,
        idempotency_key=idempotency_key,
    )

    print("Status:              {0}".format(result.get("status")))
    print("Order Reference:     {0}".format(result.get("order_reference")))
    print("Gateway Order ID:    {0}".format(result.get("gateway_order_id")))
    print("Checkout URL:        {0}".format(result.get("checkout_url")))
    print("Amount (micro-MYR):  {0}".format(result.get("amount_micro_myr")))
    print("Payment Gateway:     {0}".format(result.get("payment_gateway")))
    print("Expires At:          {0}".format(result.get("expires_at")))

    if not result.get("gateway_order_id"):
        print("WARNING: No gateway_order_id (BillCode) was returned.")
        sys.exit(1)

    if not result.get("checkout_url"):
        print("WARNING: No checkout URL was returned.")
        sys.exit(1)

    print()
    print("Checkout created successfully in PRODUCTION.")
    print("Open the checkout URL in a browser to complete payment.")
    print("After payment, ToyyibPay will call the callback URL.")
    print("This script does NOT automatically process the callback or apply credit.")
if __name__ == "__main__":
    main()

