"""CHIP reconciliation preserves purchase identity and historical paid work."""

from unittest.mock import MagicMock, patch

import pytest

from app.database import company_subscription_order_repository as repository
from app.jobs import reconcile_subscription_orders as job
from app.services import subscription_reconciliation_service as service
from app.services.chip_service import ChipConfig, ChipConfigError

BRAND = "00000000-0000-4000-8000-000000000001"
PURCHASE = "00000000-0000-4000-8000-000000000002"
REFERENCE = "00000000-0000-4000-8000-000000000003"
CONFIG = ChipConfig(enabled=True, environment="test", api_key="mock-api-key", brand_id=BRAND)
ORDER = {"company_id": 42, "order_reference": REFERENCE, "payment_gateway": "chip", "gateway_order_id": PURCHASE,
         "gateway_environment": "test", "gateway_brand_id": BRAND, "currency": "MYR", "amount_sen": 3900, "status": "pending"}
RAW = {"type": "purchase", "id": PURCHASE, "brand_id": BRAND, "reference": REFERENCE, "is_test": True,
       "status": "created", "purchase": {"total": 3900, "currency": "MYR"}}


def test_pending_query_only_fetches_chip_in_oldest_first_order():
    client = MagicMock()
    query = client.table.return_value.select.return_value
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value.data = [ORDER]
    with patch.object(repository, "supabase", client):
        assert repository.get_pending_chip_orders(5, environment="test", brand_id=BRAND) == [ORDER]
    query.eq.assert_any_call("payment_gateway", "chip")
    query.eq.assert_any_call("status", "pending")
    query.eq.assert_any_call("gateway_environment", "test")
    query.eq.assert_any_call("gateway_brand_id", BRAND)
    query.order.assert_called_once_with("updated_at", desc=False)


def test_missing_purchase_id_stays_pending_for_operator_verification():
    with patch("app.services.chip_service.ChipConfig.from_env", return_value=CONFIG), patch.object(
        service, "_update_fields"
    ), patch.object(service, "_update_state") as update, patch("app.services.chip_service.get_purchase") as fetch:
        result = service._reconcile_pending_chip_order({**ORDER, "gateway_order_id": None})
    assert result["outcome"] == "manual_review_required"
    assert result["order_status"] == "pending"
    assert update.call_args.kwargs["reconciliation_required"] is True
    fetch.assert_not_called()


def test_pending_purchase_fetches_persisted_id_and_rotates_batch_timestamp():
    with patch("app.services.chip_service.ChipConfig.from_env", return_value=CONFIG), patch.object(
        service, "_update_fields"
    ) as update, patch("app.services.chip_service.get_purchase", return_value=RAW) as fetch, patch(
        "app.services.chip_payment_service.process_chip_purchase", return_value={"status": "pending"}
    ) as process:
        result = service._reconcile_pending_chip_order(ORDER)
    fetch.assert_called_once_with(CONFIG, PURCHASE)
    assert result["outcome"] == "chip_pending"
    assert "last_reconciliation_at" in update.call_args.kwargs
    assert "expires_at" not in update.call_args.kwargs
    process.assert_called_once_with(RAW, config=CONFIG)


@pytest.mark.parametrize("field,value", [("gateway_environment", "live"), ("gateway_brand_id", None)])
def test_mode_or_brand_change_prevents_provider_query(field, value):
    with patch("app.services.chip_service.ChipConfig.from_env", return_value=CONFIG), patch.object(
        service, "_update_fields"
    ), patch("app.services.chip_service.get_purchase") as fetch:
        with pytest.raises(ValueError):
            service._reconcile_pending_chip_order({**ORDER, field: value})
    fetch.assert_not_called()


def test_mismatched_authoritative_identity_cannot_be_processed():
    with patch("app.services.chip_service.ChipConfig.from_env", return_value=CONFIG), patch.object(
        service, "_update_fields"
    ), patch("app.services.chip_service.get_purchase", return_value={**RAW, "reference": "another-reference"}), patch(
        "app.services.chip_payment_service.process_chip_purchase"
    ) as process:
        with pytest.raises(ValueError):
            service._reconcile_pending_chip_order(ORDER)
    process.assert_not_called()


def test_provider_failure_preserves_pending_status_and_reports_sentry():
    with patch.object(service, "_get_order", return_value=ORDER), patch.object(
        service, "_reconcile_pending_chip_order", side_effect=RuntimeError("offline")
    ), patch.object(service, "_update_state") as update, patch.object(service, "capture_payment_failure") as report:
        result = service.reconcile_subscription_order(REFERENCE, company_id=42)
    assert result["outcome"] == "manual_review_required"
    assert result["order_status"] == "pending"
    assert update.call_args.kwargs["reconciliation_required"] is True
    assert report.call_args.args[0] == "reconciliation"


def test_wrong_company_cannot_trigger_provider_reconciliation():
    with patch.object(service, "_get_order", return_value=ORDER), patch.object(service, "_reconcile_pending_chip_order") as reconcile:
        assert service.reconcile_subscription_order(REFERENCE, company_id=99)["outcome"] == "manual_review_required"
    reconcile.assert_not_called()


def test_test_paid_legacy_status_cannot_grant_entitlements():
    with patch.object(service, "_get_order", return_value={**ORDER, "status": "paid", "activation_status": "credit_pending"}), patch(
        "app.services.chip_service.ChipConfig.from_env", return_value=CONFIG
    ), patch.object(service, "_retry_credit") as credit, patch("app.services.chip_service.get_purchase") as fetch:
        assert service.reconcile_subscription_order(REFERENCE)["outcome"] == "manual_review_required"
    credit.assert_not_called()
    fetch.assert_not_called()


def test_cancelled_chip_cannot_be_fulfilled_from_activation_flag():
    with patch.object(service, "_get_order", return_value={**ORDER, "status": "cancelled", "activation_status": "credit_pending"}), patch.object(
        service, "_retry_credit"
    ) as credit:
        assert service.reconcile_subscription_order(REFERENCE)["outcome"] == "unpaid_order_not_reconcilable"
    credit.assert_not_called()


def test_job_keeps_generic_paid_orders_and_adds_chip_pending():
    paid_legacy = {"order_reference": "legacy-paid", "status": "paid", "updated_at": "2026-01-01"}
    with patch.object(job, "get_reconcilable_subscription_orders", return_value=[paid_legacy]), patch.object(
        job, "get_pending_chip_orders", return_value=[ORDER]
    ), patch.object(job.ChipConfig, "from_env", return_value=CONFIG), patch.object(
        job, "reconcile_subscription_order", return_value={"outcome": "already_completed"}
    ) as reconcile:
        assert job.main(["--batch-size", "2"]) == 0
    assert {call.kwargs["order_reference"] for call in reconcile.call_args_list} == {REFERENCE, "legacy-paid"}


def test_invalid_chip_configuration_does_not_stop_legacy_paid_recovery():
    paid_legacy = {"order_reference": "legacy-paid", "status": "paid"}
    with patch.object(job, "get_reconcilable_subscription_orders", return_value=[paid_legacy]), patch.object(
        job.ChipConfig, "from_env", side_effect=ChipConfigError("invalid environment")
    ), patch.object(job, "get_pending_chip_orders") as pending, patch.object(
        job, "reconcile_subscription_order", return_value={"outcome": "credit_retry_completed"}
    ) as reconcile:
        assert job.main([]) == 0
    reconcile.assert_called_once_with(order_reference="legacy-paid", company_id=None)
    pending.assert_not_called()
