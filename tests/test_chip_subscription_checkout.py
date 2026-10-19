"""One payable CHIP purchase per subscription period, with explicit mode."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import subscription_checkout_service as service
from app.services.chip_service import ChipAmbiguousError, ChipConfig, ChipRequestRejectedError

BRAND = "00000000-0000-4000-8000-000000000001"
PURCHASE = "00000000-0000-4000-8000-000000000002"
REFERENCE = "00000000-0000-4000-8000-000000000003"
URL = f"https://gate.chip-in.asia/p/{PURCHASE}/"
CONFIG = ChipConfig(enabled=True, environment="test", api_key="mock-api-key", brand_id=BRAND,
                    redirect_url="https://app.example/profile", webhook_url="https://app.example/api/billing/chip/callback")
PREPARED = {"order": {"id": 10}, "order_reference": REFERENCE, "amount_sen": 13350,
            "billing_term_months": 1, "monthly_equivalent_sen": 13350,
            "expires_at": "2026-10-05T12:00:00+00:00", "plan_code": "essential",
            "activation_sequence_key": "company:42:initial"}


@pytest.fixture
def configured():
    with patch.object(service.ChipConfig, "from_env", return_value=CONFIG):
        yield


def checkout():
    return service.create_subscription_checkout(42, 7, "essential", "Customer", "customer@example.test")


def test_only_chip_is_selected_even_if_old_environment_remains(monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_PAYMENT_GATEWAY", "toyyibpay")
    monkeypatch.setenv("HITPAY_CANARY_COMPANY_IDS", "42")
    assert service.get_subscription_payment_gateway(42) == "chip"
    with pytest.raises(ValueError):
        service.create_subscription_checkout(42, 7, "essential", "Customer", "customer@example.test", payment_gateway="hitpay")


def test_invalid_plan_is_rejected_before_loading_chip_configuration():
    with patch.object(service.ChipConfig, "from_env") as load:
        with pytest.raises(ValueError, match="plan"):
            service.create_subscription_checkout(42, 7, "invalid", "Customer", "customer@example.test")
    load.assert_not_called()


def test_create_attaches_purchase_and_sends_exact_due(configured):
    with patch.object(service, "prepare_subscription_checkout_order", return_value=PREPARED) as prepare, patch.object(
        service, "create_purchase", return_value={"gateway_order_id": PURCHASE, "checkout_url": URL, "is_test": True, "brand_id": BRAND}
    ) as create, patch.object(service, "attach_pending_subscription_gateway_details") as attach:
        result = checkout()
    assert result["payment_gateway"] == "chip"
    assert result["is_test"] is True
    assert prepare.call_args.kwargs["config"] == CONFIG
    assert create.call_args.kwargs["due"] == int(datetime.fromisoformat(PREPARED["expires_at"]).timestamp())
    attach.assert_called_once_with(order_reference=REFERENCE, payment_gateway="chip", gateway_order_id=PURCHASE, checkout_url=URL)


@pytest.mark.parametrize("error", [ChipAmbiguousError("timeout"), RuntimeError("unknown outcome")])
def test_ambiguous_create_stays_pending_and_cannot_release_claim(configured, error):
    with patch.object(service, "prepare_subscription_checkout_order", return_value=PREPARED), patch.object(
        service, "create_purchase", side_effect=error
    ), patch.object(service, "update_subscription_order_activation_state") as mark, patch.object(
        service, "fail_pending_subscription_order_without_gateway_and_release_key"
    ) as release:
        with pytest.raises(RuntimeError, match="pending verification"):
            checkout()
    assert mark.call_args.kwargs["reconciliation_required"] is True
    release.assert_not_called()


def test_definite_rejection_allows_safe_retry(configured):
    with patch.object(service, "prepare_subscription_checkout_order", return_value=PREPARED), patch.object(
        service, "create_purchase", side_effect=ChipRequestRejectedError("rejected")
    ), patch.object(service, "fail_pending_subscription_order_without_gateway_and_release_key") as release:
        with pytest.raises(RuntimeError, match="creation failed"):
            checkout()
    release.assert_called_once()


def test_attachment_failure_withholds_payable_url_and_keeps_claim(configured):
    with patch.object(service, "prepare_subscription_checkout_order", return_value=PREPARED), patch.object(
        service, "create_purchase", return_value={"gateway_order_id": PURCHASE, "checkout_url": URL, "is_test": True, "brand_id": BRAND}
    ), patch.object(service, "attach_pending_subscription_gateway_details", side_effect=RuntimeError("database unavailable")), patch.object(
        service, "update_subscription_order_activation_state"
    ) as mark, patch.object(service, "fail_pending_subscription_order_without_gateway_and_release_key") as release:
        with pytest.raises(RuntimeError, match="could not be recorded safely"):
            checkout()
    assert mark.call_args.kwargs["reconciliation_required"] is True
    release.assert_not_called()


@pytest.mark.parametrize("gateway", ["toyyibpay", "hitpay", None])
def test_elapsed_legacy_checkout_never_auto_releases(gateway):
    old = {"order_reference": REFERENCE, "payment_gateway": gateway, "gateway_order_id": "old", "status": "pending", "expires_at": "2000-01-01T00:00:00Z"}
    with patch("app.services.subscription_reconciliation_service.reconcile_subscription_order") as reconcile:
        assert service._expire_existing_pending_checkout_if_needed(old, "claimed") is False
    reconcile.assert_not_called()


def test_ambiguous_chip_purchase_without_id_never_auto_releases():
    old = {"order_reference": REFERENCE, "payment_gateway": "chip", "status": "pending", "expires_at": "2000-01-01T00:00:00Z"}
    assert service._expire_existing_pending_checkout_if_needed(old, "claimed") is False


def test_elapsed_chip_purchase_requires_authoritative_terminal_result():
    old = {"order_reference": REFERENCE, "company_id": 42, "payment_gateway": "chip", "gateway_order_id": PURCHASE,
           "status": "pending", "expires_at": "2000-01-01T00:00:00Z", "activation_sequence_key": "claimed"}
    with patch("app.services.subscription_reconciliation_service.reconcile_subscription_order") as reconcile, patch.object(
        service, "get_subscription_order_by_reference", return_value=old
    ) as get:
        assert service._expire_existing_pending_checkout_if_needed(old, "claimed") is False
        get.return_value = {**old, "status": "expired", "activation_sequence_key": "released:chip:expired:claimed"}
        assert service._expire_existing_pending_checkout_if_needed(old, "claimed") is True
    assert reconcile.call_count == 2


@pytest.mark.parametrize("environment", ["live", None])
def test_existing_checkout_from_another_mode_cannot_be_reused(configured, environment):
    old = {"payment_gateway": "chip", "gateway_order_id": PURCHASE, "checkout_url": URL,
           "gateway_brand_id": BRAND, "gateway_environment": environment, "currency": "MYR"}
    assert service._has_usable_checkout(old) is False


@pytest.mark.parametrize(("plan_code", "expected_amount_sen"), [("essential", 13350), ("pro", 56100)])
def test_new_order_stores_mode_brand_and_current_price_before_provider_call(
    configured, plan_code, expected_amount_sen
):
    subscription = {"id": 5, "plan_id": 1, "status": "trialing", "plan": {"code": "free"}, "trial_ends_at": "2026-10-01T00:00:00Z"}
    with patch.object(service, "get_current_subscription", return_value=subscription), patch.object(
        service, "get_plan_by_code", return_value={"id": 2, "is_active": True}
    ), patch.object(service, "get_subscription_order_by_activation_sequence_key", return_value=None), patch(
        "app.database.company_subscription_order_repository.list_subscription_orders_for_company", return_value=[]
    ), patch.object(service, "create_subscription_order", return_value={"id": 10}) as create:
        service.prepare_subscription_checkout_order(42, 7, plan_code, config=CONFIG)
    assert create.call_args.kwargs["gateway_environment"] == "test"
    assert create.call_args.kwargs["gateway_brand_id"] == BRAND
    assert create.call_args.kwargs["currency"] == "MYR"
    assert create.call_args.kwargs["amount_sen"] == expected_amount_sen
    assert create.call_args.kwargs["billing_term_months"] == 1
    assert create.call_args.kwargs["order_schema_version"] == 3


def test_three_month_checkout_uses_full_upfront_amount(configured):
    subscription = {"id": 5, "plan_id": 1, "status": "trialing", "plan": {"code": "free"}, "trial_ends_at": "2026-10-01T00:00:00Z"}
    with patch.object(service, "get_current_subscription", return_value=subscription), patch.object(
        service, "get_plan_by_code", return_value={"id": 2, "is_active": True}
    ), patch.object(service, "get_subscription_order_by_activation_sequence_key", return_value=None), patch(
        "app.database.company_subscription_order_repository.list_subscription_orders_for_company", return_value=[]
    ), patch.object(service, "create_subscription_order", return_value={"id": 10}) as create:
        result = service.prepare_subscription_checkout_order(
            42, 7, "essential", billing_term_months=3, config=CONFIG
        )
    assert result["amount_sen"] == 37_380
    assert result["monthly_equivalent_sen"] == 12_460
    assert create.call_args.kwargs["billing_term_months"] == 3


def test_checkout_due_uses_one_exact_utc_timestamp(monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS", "3")
    assert service._build_checkout_expires_at(datetime(2026, 9, 15, 1, 30, tzinfo=timezone.utc)) == "2026-09-18T01:30:00+00:00"
