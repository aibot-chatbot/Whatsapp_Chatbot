"""smoke_test_ai_credit_topup_supabase.py - Controlled manual Supabase smoke test
for the AI credit top-up order and checkout RPC flow.

This script exercises the internal top-up order lifecycle:
pending -> claimed -> failed

It does NOT:
- Contact a payment gateway
- Apply AI credit
- Create paid or credited orders
- Modify balance rows
- Modify frontend files

Usage (PowerShell):

    $env:CONFIRM_LIVE_SUPABASE_SMOKE_TEST="YES"
    $env:SMOKE_TEST_COMPANY_ID="<test-company-id>"
    $env:SMOKE_TEST_SUBSCRIPTION_ID="<test-subscription-id>"
    $env:SMOKE_TEST_USER_ID="<test-user-id>"
    python scripts/smoke_test_ai_credit_topup_supabase.py

Optional:

    $env:SMOKE_TEST_AMOUNT_MICRO_MYR="100000"
    $env:SMOKE_TEST_DELETE_ORDER="YES"
"""

import os, sys, uuid as uuid_mod, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger("smoke_test")

_DEFAULT_AMOUNT_MICRO_MYR = 100_000
_MICRO_MYR_DIVISOR = 10_000


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"FAIL: Required env {name} is not set")
        sys.exit(1)
    return value


def parse_positive_int(raw: str, label: str) -> int:
    try:
        value = int(raw)
    except (ValueError, TypeError):
        print(f"FAIL: {label} must be a positive integer, got {raw!r}")
        sys.exit(1)
    if value < 1:
        print(f"FAIL: {label} must be a positive integer, got {value}")
        sys.exit(1)
    return value


def parse_amount_micro_myr(raw: str | None) -> int:
    if not raw or not raw.strip():
        return _DEFAULT_AMOUNT_MICRO_MYR
    value = parse_positive_int(raw.strip(), "SMOKE_TEST_AMOUNT_MICRO_MYR")
    if value % _MICRO_MYR_DIVISOR != 0:
        print(f"FAIL: Amount {value} must be divisible by {_MICRO_MYR_DIVISOR}")
        sys.exit(1)
    return value


def is_cleanup_enabled() -> bool:
    return os.environ.get("SMOKE_TEST_DELETE_ORDER", "").strip().upper() == "YES"


def generate_claim_token() -> str:
    return str(uuid_mod.uuid4())


def generate_idempotency_key() -> str:
    return f"smoke-test-{uuid_mod.uuid4()}"


def _get_supabase():
    from app.database.db import supabase
    return supabase


def check_supabase_config() -> None:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("FAIL: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not configured")
        sys.exit(1)
    print("PASS: Supabase configuration is available")


def check_company_exists(company_id: int) -> None:
    supabase = _get_supabase()
    resp = supabase.table("companies").select("id").eq("id", company_id).limit(1).execute()
    data = resp.data if hasattr(resp, "data") else []
    if not data:
        print(f"FAIL: Company {company_id} not found")
        sys.exit(1)
    print(f"PASS: Company {company_id} exists")


def check_subscription_belongs_to_company(company_id: int, subscription_id: int) -> None:
    supabase = _get_supabase()
    resp = supabase.table("company_subscriptions").select("id,company_id").eq("id", subscription_id).limit(1).execute()
    data = resp.data if hasattr(resp, "data") else []
    if not data:
        print(f"FAIL: Subscription {subscription_id} not found in company_subscriptions")
        sys.exit(1)
    row = data[0]
    if row.get("company_id") != company_id:
        print(f"FAIL: Subscription {subscription_id} belongs to company {row.get('company_id')}, not {company_id}")
        sys.exit(1)
    print(f"PASS: Subscription {subscription_id} belongs to company {company_id}")


def check_user_exists_for_company(user_id: int, company_id: int) -> None:
    """Confirm the user exists in the users table and belongs to the company.

    The project stores application users in the ``users`` table
    (not ``user_profiles``).  The table has a ``company_id`` column
    linking each user directly to their company.
    """
    supabase = _get_supabase()
    resp = supabase.table("users").select("id,company_id").eq("id", user_id).eq("company_id", company_id).limit(1).execute()
    data = resp.data if hasattr(resp, "data") else []
    if not data:
        print(f"FAIL: User {user_id} not found or does not belong to company {company_id}")
        sys.exit(1)
    print(f"PASS: User {user_id} exists and belongs to company {company_id}")


def get_balance_before(company_id: int) -> dict | None:
    from app.database.ai_credit_repository import get_company_credit_balance
    try:
        return get_company_credit_balance(company_id)
    except Exception as exc:
        print(f"FAIL: Could not read balance: {exc}")
        sys.exit(1)


def get_transactions_before(company_id: int) -> list[dict]:
    from app.database.ai_credit_repository import list_company_credit_transactions
    try:
        return list_company_credit_transactions(company_id, limit=50)
    except Exception as exc:
        print(f"FAIL: Could not read transactions: {exc}")
        sys.exit(1)


def compare_balance_unchanged(before: dict | None, after: dict | None) -> None:
    if before is None and after is None:
        print("PASS: No balance row exists (unchanged)"); return
    if before is None:
        print("FAIL: Balance row created unexpectedly"); sys.exit(1)
    if after is None:
        print("FAIL: Balance row deleted unexpectedly"); sys.exit(1)
    for field in ["included_balance_micro_myr", "topup_balance_micro_myr"]:
        if before.get(field) != after.get(field):
            print(f"FAIL: {field} changed from {before.get(field)} to {after.get(field)}")
            sys.exit(1)
    print("PASS: Company AI credit balance is unchanged")


def confirm_no_new_transaction(before: list[dict], after: list[dict]) -> None:
    before_ids = {t.get("id") for t in before}
    for txn in after:
        if txn.get("id") not in before_ids and txn.get("transaction_type") == "topup_purchase":
            print("FAIL: New topup_purchase transaction created")
            sys.exit(1)
    print("PASS: No new topup_purchase transaction was created")


def main():
    confirm = os.environ.get("CONFIRM_LIVE_SUPABASE_SMOKE_TEST", "").strip()
    if confirm != "YES":
        print("Set CONFIRM_LIVE_SUPABASE_SMOKE_TEST=YES to proceed.")
        sys.exit(1)
    print("=" * 60)
    print("AI Credit Top-Up Smoke Test (Supabase)")
    print("=" * 60)
    company_id = parse_positive_int(get_required_env("SMOKE_TEST_COMPANY_ID"), "SMOKE_TEST_COMPANY_ID")
    subscription_id = parse_positive_int(get_required_env("SMOKE_TEST_SUBSCRIPTION_ID"), "SMOKE_TEST_SUBSCRIPTION_ID")
    user_id = parse_positive_int(get_required_env("SMOKE_TEST_USER_ID"), "SMOKE_TEST_USER_ID")
    amount_micro_myr = parse_amount_micro_myr(os.environ.get("SMOKE_TEST_AMOUNT_MICRO_MYR", ""))
    cleanup = is_cleanup_enabled()
    idempotency_key = generate_idempotency_key()
    order_reference = None
    print(f"Company ID: {company_id}  Sub: {subscription_id}  User: {user_id}")
    print(f"Amount: {amount_micro_myr} micro-MYR  Cleanup: {cleanup}")
    print()
    check_supabase_config()
    check_company_exists(company_id)
    check_subscription_belongs_to_company(company_id, subscription_id)
    check_user_exists_for_company(user_id, company_id)
    print(); print("--- Pre-test state ---")
    balance_before = get_balance_before(company_id)
    txns_before = get_transactions_before(company_id)
    print(f"Existing transactions: {len(txns_before)}")
    print(); print("--- Creating pending order ---")
    try:
        from app.services.ai_credit_topup_order_service import create_pending_topup_order
        order = create_pending_topup_order(
            company_id=company_id, subscription_id=subscription_id,
            created_by_user_id=user_id, amount_micro_myr=amount_micro_myr,
            payment_gateway="database_smoke", idempotency_key=idempotency_key,
        )
    except Exception as exc:
        print(f"FAIL: create_pending_topup_order: {exc}"); sys.exit(1)
    order_reference = order.get("order_reference", "")
    print(f"PASS: Order created  ref={order_reference}  status={order.get('status')}")
    try:
        parsed = uuid_mod.UUID(order_reference)
        assert str(parsed) == order_reference
        assert parsed.version == 4
    except Exception as exc:
        print(f"FAIL: Invalid UUID: {exc}")
        if cleanup: _delete_order(order_reference, company_id)
        sys.exit(1)
    print("PASS: UUID is valid v4 canonical")
    print(); print("--- Verifying stored order ---")
    from app.database.ai_credit_topup_order_repository import get_topup_order_by_reference
    try:
        stored = get_topup_order_by_reference(order_reference)
    except Exception as exc:
        print(f"FAIL: Get order: {exc}")
        if cleanup: _delete_order(order_reference, company_id)
        sys.exit(1)
    if not stored: print("FAIL: Order not found"); sys.exit(1)
    for label, actual, expected in [
        ("company_id", stored.get("company_id"), company_id),
        ("subscription_id", stored.get("subscription_id"), subscription_id),
        ("created_by_user_id", stored.get("created_by_user_id"), user_id),
        ("amount_micro_myr", stored.get("amount_micro_myr"), amount_micro_myr),
        ("currency", stored.get("currency"), "MYR"),
        ("payment_gateway", stored.get("payment_gateway"), "database_smoke"),
        ("status", stored.get("status"), "pending"),
    ]:
        if actual != expected:
            print(f"FAIL: {label} = {actual!r} expected {expected!r}")
            if cleanup: _delete_order(order_reference, company_id)
            sys.exit(1)
    print("PASS: All stored fields match")
    print(); print("--- Claiming checkout ---")
    claim_token = generate_claim_token()
    from app.services.ai_credit_topup_order_service import claim_checkout_creation
    try:
        claim_result = claim_checkout_creation(order_reference=order_reference, claim_token=claim_token, claim_timeout_seconds=300)
    except Exception as exc:
        print(f"FAIL: Claim: {exc}")
        if cleanup: _delete_order(order_reference, company_id)
        sys.exit(1)
    if not claim_result.get("claimed"):
        print(f"FAIL: Claim failed: {claim_result.get('reason')}")
        if cleanup: _delete_order(order_reference, company_id)
        sys.exit(1)
    print(f"PASS: Claimed  reason={claim_result.get('reason')}")
    print(); print("--- Failing checkout ---")
    from app.services.ai_credit_topup_order_service import fail_checkout_creation
    try:
        fail_result = fail_checkout_creation(order_reference=order_reference, claim_token=claim_token, failure_reason="Smoke test fail")
    except Exception as exc:
        print(f"FAIL: Fail: {exc}")
        if cleanup: _delete_order(order_reference, company_id)
        sys.exit(1)
    print(f"PASS: Failed  status={fail_result.get('status')}")
    try:
        stored_after = get_topup_order_by_reference(order_reference)
    except Exception as exc:
        print(f"FAIL: Get after fail: {exc}"); sys.exit(1)
    if not stored_after or stored_after.get("status") != "failed":
        s = stored_after.get("status") if stored_after else "None"
        print(f"FAIL: Expected failed got {s}"); sys.exit(1)
    print("PASS: Status is failed")
    print(); print("--- Credit transaction check ---")
    txns_after = get_transactions_before(company_id)
    confirm_no_new_transaction(txns_before, txns_after)
    print(); print("--- Balance check ---")
    balance_after = get_balance_before(company_id)
    compare_balance_unchanged(balance_before, balance_after)
    print(); print("=" * 60)
    print("SMOKE TEST PASSED"); print("=" * 60)
    print(f"Order: {order_reference}")
    print("Flow: pending -> claimed -> failed")
    print("Balance unchanged: Yes")
    if cleanup and order_reference: _delete_order(order_reference, company_id)
    sys.exit(0)


def _delete_order(order_reference: str, company_id: int) -> None:
    if not order_reference or not company_id:
        print("WARN: Cleanup skipped: missing args"); return
    try:
        supabase = _get_supabase()
        from app.database.ai_credit_topup_order_repository import TABLE
        resp = supabase.table(TABLE).delete().eq("order_reference", order_reference).eq("company_id", company_id).execute()
        data = resp.data if hasattr(resp, "data") else []
        if len(data) == 1: print(f"PASS: Cleanup deleted {order_reference}")
        elif len(data) == 0: print(f"WARN: No order to delete ({order_reference})")
        else: print(f"WARN: Deleted {len(data)} rows (expected 1)")
    except Exception as exc:
        print(f"WARN: Cleanup failed: {exc}")
        print(f"Manual cleanup: {order_reference}")


if __name__ == "__main__":
    main()


