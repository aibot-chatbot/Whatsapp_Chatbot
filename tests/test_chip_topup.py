"""CHIP top-up identity, mode, checkout claims, and retry safety."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import httpx
import requests

import app.database.ai_credit_topup_order_repository as repository
import app.services.ai_credit_topup_checkout_service as checkout
import app.services.chip_topup_payment_service as payment
from app.services.chip_service import ChipAmbiguousError, ChipConfig, ChipRequestRejectedError

BRAND = "00000000-0000-4000-8000-000000000001"
PURCHASE = "00000000-0000-4000-8000-000000000002"
REFERENCE = "00000000-0000-4000-8000-000000000003"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network call in mocked payment tests")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(httpx.Client, "request", blocked)


def config(mode="live"):
    return ChipConfig(enabled=True, environment=mode, live_enabled=True, api_key="synthetic-api-key",
                      brand_id=BRAND, redirect_url="https://app.example/billing",
                      webhook_url="https://app.example/api/billing/chip/callback")


def order(mode="live", **changes):
    return {
        "id": 4, "company_id": 42, "subscription_id": 8, "created_by_user_id": 1,
        "order_reference": REFERENCE, "gateway_order_id": PURCHASE,
        "payment_gateway": "chip", "gateway_environment": mode, "gateway_brand_id": BRAND,
        "amount_micro_myr": 2_000_000, "currency": "MYR", "status": "pending", **changes,
    }


def purchase(mode="live", status="paid"):
    return {
        "type": "purchase", "id": PURCHASE, "brand_id": BRAND, "reference": REFERENCE,
        "status": status, "is_test": mode == "test", "marked_as_paid": False,
        "purchase": {"total": 200, "currency": "MYR"},
        "payment": {"amount": 200, "currency": "MYR", "is_outgoing": False,
                    "payment_type": "purchase", "paid_on": 1789000000},
    }


@pytest.fixture
def processing(monkeypatch):
    stored = order()
    monkeypatch.setattr(payment, "get_topup_order_by_gateway_order_id", lambda *args: stored)
    fulfill = Mock(return_value={"status": "credited", "idempotent": False})
    close = Mock(side_effect=lambda reference, status, reason: {**stored, "status": status, "failure_reason": reason})
    monkeypatch.setattr(payment, "process_topup_payment_callback", fulfill)
    monkeypatch.setattr(payment, "close_chip_topup_order", close)
    return stored, fulfill, close


@pytest.mark.parametrize("field,value", [
    ("gateway_order_id", "other-id"), ("order_reference", "other-reference"),
    ("gateway_brand_id", "other-brand"), ("gateway_environment", "test"),
    ("gateway_environment", None), ("payment_gateway", "hitpay"), ("currency", "USD"),
    ("amount_micro_myr", True), ("amount_micro_myr", 2_000_000.0),
    ("amount_micro_myr", 1_990_000), ("amount_micro_myr", 2_010_000),
    ("amount_micro_myr", 2_000_001), ("amount_micro_myr", 0),
    ("payment_reference", "another-payment"),
])
def test_topup_mismatch_never_grants_credit(processing, field, value):
    stored, fulfill, close = processing
    stored[field] = value
    with pytest.raises(ValueError):
        payment.process_chip_topup_purchase(purchase(), config())
    fulfill.assert_not_called()
    close.assert_not_called()


def test_live_topup_uses_guarded_existing_credit_callback(processing):
    _, fulfill, close = processing
    assert payment.process_chip_topup_purchase(purchase(), config())["status"] == "credited"
    assert fulfill.call_args.args[0]["amount_sen"] == 200
    close.assert_not_called()


@pytest.fixture
def review_storage(processing, monkeypatch):
    stored, fulfill, close = processing
    write = Mock()

    class Query:
        def __init__(self):
            self.matches = True

        def update(self, changes):
            self.changes = changes
            return self

        def eq(self, key, value):
            self.matches &= stored.get(key) == value
            return self

        def execute(self):
            if not self.matches:
                return SimpleNamespace(data=[])
            write(self.changes)
            stored.update(self.changes)
            return SimpleNamespace(data=[dict(stored)])

    def table(name):
        assert name == repository.TABLE
        return Query()

    monkeypatch.setattr(repository, "supabase", SimpleNamespace(table=table))
    return stored, fulfill, close, write


@pytest.mark.parametrize("status", ["pending", "paid", "credited", "cancelled", "expired", "failed"])
def test_reversal_review_preserves_payment_and_credit_history(review_storage, status):
    stored, fulfill, close, write = review_storage
    stored.update(status=status, paid_at="2026-09-01T12:00:00Z",
                  credited_at="2026-09-01T12:01:00Z", credit_transaction_id=89,
                  gateway_payment_id=PURCHASE, payment_reference=PURCHASE,
                  failure_reason="previous_reason", updated_at="2026-09-01T12:01:00Z")
    before = dict(stored)
    result = payment.process_chip_topup_purchase(purchase(), config(), review_required=True)
    assert result == {"status": "manual_review_required"}
    assert stored["failure_reason"] == "chip_status_review"
    assert stored["updated_at"] != before["updated_at"]
    assert {key: value for key, value in stored.items() if key not in {"failure_reason", "updated_at"}} == {
        key: value for key, value in before.items() if key not in {"failure_reason", "updated_at"}
    }
    assert set(write.call_args.args[0]) == {"failure_reason", "updated_at"}
    fulfill.assert_not_called()
    close.assert_not_called()


@pytest.mark.parametrize("status", ["paid", "cancelled", "created", "refunded"])
@pytest.mark.parametrize("mode", ["live", "test"])
def test_review_marker_blocks_later_processing_and_replay(review_storage, status, mode):
    stored, fulfill, close, write = review_storage
    stored["gateway_environment"] = mode
    payment.process_chip_topup_purchase(purchase(mode), config(mode), review_required=True)
    marked = dict(stored)
    assert payment.process_chip_topup_purchase(purchase(mode, status), config(mode)) == {
        "status": "manual_review_required"
    }
    assert payment.process_chip_topup_purchase(purchase(mode), config(mode), review_required=True) == {
        "status": "manual_review_required"
    }
    assert stored == marked
    write.assert_called_once()
    fulfill.assert_not_called()
    close.assert_not_called()


def test_review_persistence_failure_can_retry_without_fulfillment(review_storage):
    stored, fulfill, close, write = review_storage
    before = dict(stored)
    write.side_effect = RuntimeError("synthetic storage failure")
    with pytest.raises(RuntimeError, match="synthetic storage failure"):
        payment.process_chip_topup_purchase(purchase(), config(), review_required=True)
    assert stored == before
    fulfill.assert_not_called()
    close.assert_not_called()
    write.side_effect = None
    assert payment.process_chip_topup_purchase(purchase(), config(), review_required=True)["status"] == "manual_review_required"
    assert payment.process_chip_topup_purchase(purchase(), config())["status"] == "manual_review_required"
    assert stored["failure_reason"] == "chip_status_review"
    fulfill.assert_not_called()
    close.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("gateway_order_id", "another-purchase"), ("order_reference", "another-reference"),
    ("payment_gateway", "toyyibpay"),
])
def test_review_repository_rejects_identity_mismatch_without_write(review_storage, field, value):
    stored, _, _, write = review_storage
    stored[field] = value
    before = dict(stored)
    with pytest.raises(RuntimeError, match="review could not be recorded"):
        repository.mark_chip_topup_order_for_review(REFERENCE, PURCHASE)
    assert stored == before
    write.assert_not_called()


@pytest.mark.parametrize("returned", [None, {}, order(failure_reason="unchanged"),
                                    order(failure_reason="chip_status_review", gateway_order_id="wrong")])
def test_review_cannot_succeed_without_confirmed_persisted_row(review_storage, monkeypatch, returned):
    _, fulfill, close, _ = review_storage
    monkeypatch.setattr(repository, "_single_row", Mock(return_value=returned))
    with pytest.raises(RuntimeError, match="review could not be recorded"):
        payment.process_chip_topup_purchase(purchase(), config(), review_required=True)
    fulfill.assert_not_called()
    close.assert_not_called()


@pytest.mark.parametrize("field,value", [("gateway_brand_id", "other-brand"), ("amount_micro_myr", 1_990_000)])
def test_reversal_validation_failure_does_not_mark_review(review_storage, field, value):
    stored, fulfill, close, write = review_storage
    stored[field] = value
    with pytest.raises(ValueError):
        payment.process_chip_topup_purchase(purchase(), config(), review_required=True)
    write.assert_not_called()
    fulfill.assert_not_called()
    close.assert_not_called()


def test_unknown_provider_status_is_durably_held_for_review(review_storage):
    stored, fulfill, close, write = review_storage
    assert payment.process_chip_topup_purchase(purchase(status="refunded"), config())["status"] == "manual_review_required"
    assert stored["failure_reason"] == "chip_status_review"
    assert payment.process_chip_topup_purchase(purchase(), config())["status"] == "manual_review_required"
    write.assert_called_once()
    fulfill.assert_not_called()
    close.assert_not_called()


def test_failed_paid_claim_never_grants_chip_credit(monkeypatch):
    import app.services.ai_credit_topup_callback_service as callback
    from app.services.chip_service import normalize_purchase

    monkeypatch.setattr(callback, "_get_order_by_gateway", Mock(return_value=order()))
    monkeypatch.setattr(callback, "_mark_order_paid", Mock(side_effect=RuntimeError("claim failed")))
    grant = Mock()
    monkeypatch.setattr(callback, "_add_topup_credit", grant)
    with pytest.raises(RuntimeError, match="claim failed"):
        callback.process_topup_payment_callback(normalize_purchase(purchase()))
    grant.assert_not_called()


def test_test_payment_never_grants_credit(processing):
    stored, fulfill, close = processing
    stored["gateway_environment"] = "test"
    assert payment.process_chip_topup_purchase(purchase("test"), config("test"))["status"] == "test_paid"
    close.assert_called_once_with(REFERENCE, "cancelled", "chip_test_paid")
    fulfill.assert_not_called()


def test_test_payment_duplicate_has_no_second_write(processing):
    stored, fulfill, close = processing
    stored.update(gateway_environment="test", status="cancelled", failure_reason="chip_test_paid")
    result = payment.process_chip_topup_purchase(purchase("test"), config("test"))
    assert result["status"] == "test_paid" and result["idempotent"] is True
    close.assert_not_called()
    fulfill.assert_not_called()


def test_test_payment_cannot_claim_success_when_storage_fails(processing):
    stored, fulfill, close = processing
    stored["gateway_environment"] = "test"
    close.side_effect = None
    close.return_value = None
    with pytest.raises(RuntimeError):
        payment.process_chip_topup_purchase(purchase("test"), config("test"))
    fulfill.assert_not_called()


@pytest.mark.parametrize("status", ["created", "error", "pending_execute", "pending_charge"])
def test_retriable_unpaid_purchase_does_not_close_local_order(processing, status):
    _, fulfill, close = processing
    result = payment.process_chip_topup_purchase(purchase(status=status), config())
    assert result["status"] in {"pending", "manual_review_required"}
    close.assert_not_called()
    fulfill.assert_not_called()


@pytest.fixture
def creation(monkeypatch):
    cfg = config("test")
    stored = order("test", gateway_order_id=None)
    monkeypatch.setattr(checkout.ChipConfig, "from_env", lambda: cfg)
    monkeypatch.setattr(checkout, "_create_pending_order", lambda **kwargs: stored)
    claim = Mock(return_value=stored)
    provider = Mock(return_value={"gateway_order_id": PURCHASE, "checkout_url": "https://gate.chip-in.asia/b/test/"})
    complete = Mock(return_value={"gateway_order_id": PURCHASE, "checkout_url": "https://gate.chip-in.asia/b/test/"})
    fail = Mock()
    monkeypatch.setattr(checkout, "claim_chip_topup_checkout", claim)
    monkeypatch.setattr(checkout, "create_purchase", provider)
    monkeypatch.setattr(checkout, "_complete_checkout", complete)
    monkeypatch.setattr(checkout, "_fail_checkout", fail)

    def create():
        return checkout.create_chip_topup_checkout(
            company_id=42, subscription_id=8, created_by_user_id=1, amount_micro_myr=2_000_000,
            customer_email="test@example.test", customer_name="Test User", idempotency_key="synthetic-attempt",
        )

    return stored, claim, provider, complete, fail, create


def test_checkout_creates_integer_sen_purchase_without_credit(creation):
    _, claim, provider, complete, fail, create = creation
    result = create()
    assert result["amount_micro_myr"] == 2_000_000 and result["is_test"] is True
    assert provider.call_args.kwargs["amount_sen"] == 200
    assert complete.call_args.kwargs["claim_token"] == claim.call_args.args[1]
    fail.assert_not_called()


def test_ambiguous_create_keeps_claim_and_retry_never_creates_second_purchase(creation):
    _, claim, provider, complete, fail, create = creation
    claim.side_effect = [{"order_reference": REFERENCE}, None]
    provider.side_effect = ChipAmbiguousError("outcome unknown")
    with pytest.raises(RuntimeError):
        create()
    with pytest.raises(RuntimeError):
        create()
    provider.assert_called_once()
    complete.assert_not_called()
    fail.assert_not_called()


def test_checkout_persistence_failure_keeps_provider_claim(creation):
    _, _, provider, complete, fail, create = creation
    complete.side_effect = RuntimeError("private-db-secret")
    with pytest.raises(RuntimeError, match="reconciliation"):
        create()
    provider.assert_called_once()
    fail.assert_not_called()


def test_definitive_rejection_closes_attempt(creation):
    _, _, provider, complete, fail, create = creation
    provider.side_effect = ChipRequestRejectedError("rejected")
    with pytest.raises(checkout.CheckoutRestartRequired, match="rejected"):
        create()
    fail.assert_called_once()
    complete.assert_not_called()


def test_existing_checkout_is_reused_without_new_provider_request(creation):
    stored, claim, provider, _, _, create = creation
    stored.update(gateway_order_id=PURCHASE, checkout_url="https://gate.chip-in.asia/b/test/")
    assert create()["gateway_order_id"] == PURCHASE
    claim.assert_not_called()
    provider.assert_not_called()


def test_old_ambiguous_repository_claim_cannot_be_stolen(monkeypatch):
    stored = order("test", gateway_order_id=None, checkout_claim_token="original-token",
                   checkout_claimed_at="2020-01-01T00:00:00Z")

    class Query:
        def __init__(self):
            self.matches = True
        def update(self, changes):
            self.changes = changes
            return self
        def eq(self, key, value):
            self.matches &= stored.get(key) == value
            return self
        def is_(self, key, value):
            assert value == "null"
            self.matches &= stored.get(key) is None
            return self
        def execute(self):
            if self.matches:
                stored.update(self.changes)
            return SimpleNamespace(data=[stored] if self.matches else [])

    monkeypatch.setattr(repository, "supabase", SimpleNamespace(table=lambda name: Query()))
    assert repository.claim_chip_topup_checkout(REFERENCE, "new-token", "test", BRAND) is None
    assert stored["checkout_claim_token"] == "original-token"


@pytest.fixture
def reconciliation(monkeypatch):
    monkeypatch.setattr(payment.ChipConfig, "from_env", lambda: config())
    pending = Mock(return_value=[order()])
    fetch = Mock(return_value=purchase())
    process = Mock(return_value={"status": "credited"})
    report = Mock()
    monkeypatch.setattr(payment, "get_pending_chip_topup_orders", pending)
    monkeypatch.setattr(payment, "get_purchase", fetch)
    monkeypatch.setattr(payment, "process_chip_topup_purchase", process)
    monkeypatch.setattr(payment, "capture_payment_failure", report)
    monkeypatch.setattr(payment, "touch_chip_topup_reconciliation", Mock())
    return pending, fetch, process, report


def test_reconciliation_recovers_missed_callback_by_persisted_id(reconciliation):
    pending, fetch, process, report = reconciliation
    assert payment.reconcile_chip_topups(limit=8) == 0
    pending.assert_called_once_with("live", BRAND, 8)
    assert fetch.call_args.args[1] == PURCHASE
    process.assert_called_once_with(fetch.return_value, fetch.call_args.args[0])
    report.assert_not_called()


def test_reconciliation_never_fetches_other_mode_purchase(reconciliation):
    pending, fetch, process, _ = reconciliation
    pending.return_value = [order("test")]
    assert payment.reconcile_chip_topups() == 0
    fetch.assert_not_called()
    process.assert_not_called()


def test_reconciliation_missing_purchase_id_keeps_claim_for_manual_review(reconciliation):
    pending, fetch, process, report = reconciliation
    stored = order(gateway_order_id=None, checkout_claim_token="permanent-token")
    pending.return_value = [stored]
    assert payment.reconcile_chip_topups() == 1
    assert stored["checkout_claim_token"] == "permanent-token"
    assert report.call_args.kwargs["reason"] == "persistence"
    fetch.assert_not_called()
    process.assert_not_called()


def test_reconciliation_provider_failure_does_not_skip_other_orders(reconciliation):
    pending, fetch, process, report = reconciliation
    pending.return_value = [order(), order()]
    fetch.side_effect = [RuntimeError("provider unavailable"), purchase()]
    assert payment.reconcile_chip_topups() == 1
    assert fetch.call_count == 2
    process.assert_called_once()
    assert report.call_args.kwargs["reason"] == "unexpected"


def test_reconciliation_timestamp_failure_does_not_skip_other_orders(reconciliation, monkeypatch):
    pending, fetch, process, report = reconciliation
    pending.return_value = [order(), order()]
    monkeypatch.setattr(payment, "touch_chip_topup_reconciliation", Mock(side_effect=[RuntimeError("storage unavailable"), None]))
    assert payment.reconcile_chip_topups() == 1
    assert fetch.call_count == 2
    assert process.call_count == 2
    assert report.called


def test_reconciliation_review_outcome_reports_failure(reconciliation):
    _, _, process, report = reconciliation
    process.return_value = {"status": "manual_review_required"}
    assert payment.reconcile_chip_topups() == 1
    assert report.call_args.kwargs["reason"] == "invalid_response"


def test_disabled_chip_reconciliation_does_no_provider_or_storage_work(reconciliation, monkeypatch):
    pending, fetch, process, _ = reconciliation
    monkeypatch.setattr(payment.ChipConfig, "from_env", lambda: ChipConfig())
    assert payment.reconcile_chip_topups() == 0
    pending.assert_not_called()
    fetch.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize("subscription_result,topup_failures,expected", [(0, 0, 0), (1, 0, 1), (0, 2, 1)])
def test_existing_scheduler_reconciles_both_payment_types(monkeypatch, subscription_result, topup_failures, expected):
    from app.jobs import reconcile_subscription_orders
    from app.services.billing_scheduler_service import _run_reconcile

    subscriptions = Mock(return_value=subscription_result)
    topups = Mock(return_value=topup_failures)
    monkeypatch.setattr(reconcile_subscription_orders, "main", subscriptions)
    monkeypatch.setattr(payment, "reconcile_chip_topups", topups)
    assert _run_reconcile() == expected
    subscriptions.assert_called_once_with([])
    topups.assert_called_once_with()


def test_scheduler_records_topup_reconciliation_exception(monkeypatch):
    from app.jobs import reconcile_subscription_orders
    from app.services.billing_scheduler_service import _run_reconcile
    import app.observability as observability

    monkeypatch.setattr(reconcile_subscription_orders, "main", lambda args: 0)
    monkeypatch.setattr(payment, "reconcile_chip_topups", Mock(side_effect=RuntimeError("private-provider-details")))
    report = Mock()
    monkeypatch.setattr(observability, "capture_payment_failure", report)
    assert _run_reconcile() == 1
    assert report.call_args.args == ("reconciliation",)
