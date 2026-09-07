"""Focused authoritative-status tests for HitPay subscription payments."""

import unittest
from unittest.mock import patch


_SERVICE = "app.services.hitpay_payment_service"


def _request(status="completed", amount="39.00"):
    return {
        "id": "hp-request-1",
        "reference_number": "order-1",
        "status": status,
        "currency": "MYR",
        "amount": amount,
        "updated_at": "2026-09-04T00:00:00+00:00",
        "payments": [
            {
                "id": "hp-payment-1",
                "status": "succeeded",
                "updated_at": "2026-09-04T00:00:00+00:00",
            }
        ] if status == "completed" else [],
    }


class TestHitPayPaymentService(unittest.TestCase):
    def setUp(self):
        self.order = {
            "id": 7,
            "order_reference": "order-1",
            "payment_gateway": "hitpay",
            "gateway_order_id": "hp-request-1",
            "amount_sen": 3900,
            "status": "pending",
            "activation_sequence_key": "company:42:initial",
        }

    def test_completed_request_uses_existing_callback_activation_path(self):
        from app.services.hitpay_payment_service import process_hitpay_payment_request

        with (
            patch(_SERVICE + ".get_subscription_order_by_gateway_id", return_value=self.order),
            patch(_SERVICE + ".process_subscription_payment_callback", return_value={
                "status": "activated", "order_reference": "order-1"
            }) as callback,
        ):
            result = process_hitpay_payment_request(_request())

        self.assertEqual(result["status"], "activated")
        callback.assert_called_once()
        self.assertEqual(callback.call_args.args[0]["payment_gateway"], "hitpay")

    def test_exact_amount_is_required_before_activation(self):
        from app.services.hitpay_payment_service import process_hitpay_payment_request

        with (
            patch(_SERVICE + ".get_subscription_order_by_gateway_id", return_value=self.order),
            patch(_SERVICE + ".process_subscription_payment_callback") as callback,
        ):
            with self.assertRaises(ValueError):
                process_hitpay_payment_request(_request(amount="40.00"))

        callback.assert_not_called()

    def test_failed_request_terminalizes_only_pending_order(self):
        from app.services.hitpay_payment_service import process_hitpay_payment_request

        with (
            patch(_SERVICE + ".get_subscription_order_by_gateway_id", return_value=self.order),
            patch(_SERVICE + ".transition_pending_subscription_order_terminal", return_value={
                **self.order, "status": "failed"
            }) as transition,
        ):
            result = process_hitpay_payment_request(_request(status="failed"))

        self.assertEqual(result["status"], "failed")
        transition.assert_called_once()
        self.assertEqual(transition.call_args.kwargs["target_status"], "failed")

    def test_pending_request_is_fail_open_for_user_state(self):
        from app.services.hitpay_payment_service import process_hitpay_payment_request

        with (
            patch(_SERVICE + ".get_subscription_order_by_gateway_id", return_value=self.order),
            patch(_SERVICE + ".transition_pending_subscription_order_terminal") as transition,
            patch(_SERVICE + ".process_subscription_payment_callback") as callback,
        ):
            result = process_hitpay_payment_request(_request(status="pending"))

        self.assertEqual(result["status"], "pending")
        transition.assert_not_called()
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
