"""Authoritative CHIP purchase binding and test/live entitlement isolation."""

from unittest.mock import MagicMock, call, patch

import pytest

from app.services.chip_service import ChipConfig
from app.services import chip_payment_service as service
from app.services import subscription_payment_callback_service as callback_service
from app.database import company_subscription_order_repository as order_repository

BRAND = "00000000-0000-4000-8000-000000000001"
PURCHASE = "00000000-0000-4000-8000-000000000002"
REFERENCE = "00000000-0000-4000-8000-000000000003"


def config(mode="live"):
    return ChipConfig(enabled=True, environment=mode, api_key="mock-api-key", brand_id=BRAND, live_enabled=True)


def order(mode="live"):
    return {
        "id": 4, "company_id": 42, "order_reference": REFERENCE,
        "payment_gateway": "chip", "gateway_order_id": PURCHASE,
        "gateway_environment": mode, "gateway_brand_id": BRAND,
        "currency": "MYR", "amount_sen": 3900, "status": "pending",
        "activation_sequence_key": "company:42:initial",
        "new_plan_id": 2, "subscription_id": 8,
    }


def purchase(mode="live", status="paid", amount=3900):
    return {
        "type": "purchase", "id": PURCHASE, "brand_id": BRAND, "reference": REFERENCE,
        "status": status, "is_test": mode == "test", "marked_as_paid": False,
        "purchase": {"total": amount, "currency": "MYR"},
        "payment": {"amount": amount, "currency": "MYR", "is_outgoing": False,
                    "payment_type": "purchase", "paid_on": 1789000000},
    }


def test_live_paid_uses_existing_idempotent_fulfilment():
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=order()), patch.object(
        service, "mark_pending_subscription_order_paid",
        return_value={**order(), "status": "paid", "payment_reference": PURCHASE},
    ) as claim, patch.object(
        service, "process_subscription_payment_callback", return_value={"status": "activated"}
    ) as fulfill:
        assert service.process_chip_purchase(purchase(), config())["status"] == "activated"
    assert fulfill.call_args.args[0]["amount_sen"] == 3900
    assert fulfill.call_args.args[0]["payment_gateway"] == "chip"
    claim.assert_called_once_with(
        order_reference=REFERENCE, payment_reference=PURCHASE,
        paid_at=fulfill.call_args.args[0]["paid_at"],
    )


@pytest.mark.parametrize("field,value", [
    ("payment_gateway", "hitpay"), ("gateway_order_id", "another-purchase"),
    ("order_reference", "another-reference"), ("gateway_environment", "test"),
    ("gateway_environment", None), ("gateway_brand_id", None),
    ("gateway_brand_id", "00000000-0000-4000-8000-000000000099"),
    ("currency", "USD"), ("amount_sen", True), ("amount_sen", 3900.0),
    ("amount_sen", 3899), ("amount_sen", 3901), ("amount_sen", 0),
    ("payment_reference", "different-payment"),
])
def test_mismatches_cannot_reach_fulfilment(field, value):
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value={**order(), field: value}), patch.object(
        service, "process_subscription_payment_callback"
    ) as fulfill:
        with pytest.raises(ValueError):
            service.process_chip_purchase(purchase(), config())
    fulfill.assert_not_called()


def test_test_payment_releases_claim_without_activating_or_crediting():
    stored = order("test")
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=stored), patch.object(
        service, "transition_pending_subscription_order_terminal",
        return_value={**stored, "status": "cancelled", "activation_error_code": "chip_test_paid"},
    ) as terminal, patch.object(service, "process_subscription_payment_callback") as fulfill:
        result = service.process_chip_purchase(purchase("test"), config("test"))
    assert result["status"] == "test_paid"
    assert terminal.call_args.kwargs["error_code"] == "chip_test_paid"
    assert terminal.call_args.kwargs["released_activation_sequence_key"].startswith("released:chip:test-paid:")
    fulfill.assert_not_called()


def test_test_payment_duplicate_is_idempotent():
    stored = {**order("test"), "status": "cancelled", "activation_error_code": "chip_test_paid"}
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=stored), patch.object(
        service, "transition_pending_subscription_order_terminal"
    ) as terminal, patch.object(service, "process_subscription_payment_callback") as fulfill:
        assert service.process_chip_purchase(purchase("test"), config("test"))["idempotent"] is True
    terminal.assert_not_called()
    fulfill.assert_not_called()


@pytest.mark.parametrize("status", ["created", "sent", "viewed", "pending_execute", "pending_charge"])
def test_unpaid_purchase_keeps_claim(status):
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=order()), patch.object(
        service, "transition_pending_subscription_order_terminal"
    ) as terminal, patch.object(service, "process_subscription_payment_callback") as fulfill:
        assert service.process_chip_purchase(purchase(status=status), config())["status"] == "pending"
    terminal.assert_not_called()
    fulfill.assert_not_called()


@pytest.mark.parametrize("status", ["cancelled", "expired"])
def test_provider_confirmed_terminal_state_releases_claim(status):
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=order()), patch.object(
        service, "transition_pending_subscription_order_terminal", return_value={**order(), "status": status}
    ) as terminal:
        assert service.process_chip_purchase(purchase(status=status), config())["status"] == status
    assert terminal.call_args.kwargs["target_status"] == status


def test_live_duplicate_still_uses_guarded_shared_fulfilment():
    stored = {**order(), "status": "credited", "payment_reference": PURCHASE}
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=stored), patch.object(
        service, "mark_pending_subscription_order_paid", return_value=stored,
    ), patch.object(
        service, "process_subscription_payment_callback", return_value={"status": "already_activated", "idempotent": True}
    ) as fulfill:
        assert service.process_chip_purchase(purchase(), config())["idempotent"] is True
    fulfill.assert_called_once()


def test_test_purchase_cannot_be_processed_in_live_mode():
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=order()), patch.object(
        service, "process_subscription_payment_callback"
    ) as fulfill:
        with pytest.raises(ValueError):
            service.process_chip_purchase(purchase("test"), config())
    fulfill.assert_not_called()


def test_failed_payment_claim_never_reaches_fulfilment():
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=order()), patch.object(
        service, "mark_pending_subscription_order_paid",
        side_effect=RuntimeError("Payment claim failed"),
    ), patch.object(service, "process_subscription_payment_callback") as fulfill, patch.object(
        service, "capture_payment_failure"
    ) as capture:
        with pytest.raises(RuntimeError, match="Payment claim failed"):
            service.process_chip_purchase(purchase(), config())
    fulfill.assert_not_called()
    assert capture.call_args.kwargs["reason"] == "persistence"


@pytest.mark.parametrize("claimed", [
    None, {}, {**order(), "payment_reference": PURCHASE},
    {**order(), "status": "paid"},
    {**order(), "status": "paid", "payment_reference": "another-payment"},
    {**order("test"), "status": "paid", "payment_reference": PURCHASE},
])
def test_invalid_payment_claim_result_never_reaches_fulfilment(claimed):
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=order()), patch.object(
        service, "mark_pending_subscription_order_paid", return_value=claimed,
    ), patch.object(service, "process_subscription_payment_callback") as fulfill:
        with pytest.raises((ValueError, RuntimeError)):
            service.process_chip_purchase(purchase(), config())
    fulfill.assert_not_called()


@pytest.mark.parametrize("persisted_status", ["paid", "credited"])
def test_stale_pending_snapshot_uses_persisted_claim_without_resetting_activation(persisted_status):
    """Exercise the real CAS repository and shared callback after a concurrent payment."""
    persisted = {
        **order(), "status": persisted_status, "payment_reference": PURCHASE,
        "paid_at": "2026-09-10T00:26:40+00:00",
        "activation_status": "completed" if persisted_status == "credited" else "credit_pending",
        "credited_at": "2026-09-10T00:26:41+00:00" if persisted_status == "credited" else None,
    }
    query = MagicMock()
    query.update.return_value = query
    query.eq.return_value = query
    query.is_.return_value = query
    query.execute.return_value.data = []  # The pending-only update loses to the other process.
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=order()), patch.object(
        order_repository, "supabase"
    ) as database, patch.object(
        order_repository, "get_subscription_order_by_reference", return_value=persisted
    ), patch.object(
        callback_service, "_get_order_by_gateway",
        side_effect=lambda **kwargs: persisted if query.execute.called else order(),
    ), patch.object(
        callback_service, "_update_activation_state"
    ) as update_activation, patch.object(
        callback_service, "_activate_subscription_plan", return_value={"status": "activation_resumed"}
    ) as activate, patch.object(
        callback_service, "_repository_update_order_status"
    ) as update_status, patch("app.services.billing_notification_service.notify_payment_confirmed"), patch(
        "app.services.billing_notification_service.notify_activation_completed"
    ):
        database.table.return_value = query
        result = service.process_chip_purchase(purchase(), config())
    assert query.eq.call_args_list == [call("order_reference", REFERENCE), call("status", "pending")]
    assert query.is_.call_args_list == [call("paid_at", "null"), call("credited_at", "null")]
    update_activation.assert_not_called()
    update_status.assert_not_called()
    if persisted_status == "credited":
        assert result["status"] == "already_activated"
        assert result["idempotent"] is True
        activate.assert_not_called()
    else:
        assert result["status"] == "activation_resumed"
        assert activate.call_args.kwargs["order"]["status"] == "paid"


def _review_branch(order_overrides=None):
    """Drive the operator-review fallthrough with an unclassified CHIP status."""
    stored = {**order(), **(order_overrides or {})}
    with patch.object(service, "get_subscription_order_by_gateway_id", return_value=stored), patch.object(
        service, "update_subscription_order_activation_state"
    ) as flag, patch.object(service, "capture_payment_failure") as report:
        result = service.process_chip_purchase(purchase(status="hold"), config())
    return result, flag, report


def test_unclassified_status_is_flagged_and_reported_once():
    """Entering operator review flags the order and raises one alert."""
    result, flag, report = _review_branch()

    assert result["status"] == "manual_review_required"
    assert flag.call_args.kwargs["activation_error_code"] == "chip_status_review"
    assert flag.call_args.kwargs["reconciliation_required"] is True
    report.assert_called_once_with("fulfillment", reason="invalid_response", mode="live")


def test_rescanning_an_order_already_in_review_does_not_realert():
    """reconciliation_required keeps this order in every 15-minute reconcile scan.

    Re-reporting it each tick is what produced the Sentry storm; the persisted
    flag, not a repeated alert, is what holds the order for the operator.
    """
    result, flag, report = _review_branch({"activation_error_code": "chip_status_review"})

    assert result["status"] == "manual_review_required"
    flag.assert_called_once()
    report.assert_not_called()
