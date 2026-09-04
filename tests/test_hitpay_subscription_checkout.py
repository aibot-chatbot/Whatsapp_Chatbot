"""Focused checkout-routing tests for the HitPay rollout path."""

import unittest
from unittest.mock import patch


_SERVICE = "app.services.subscription_checkout_service"


class TestHitPaySubscriptionCheckout(unittest.TestCase):
    def setUp(self):
        self.prepared = {
            "order": {"id": 10},
            "order_reference": "00000000-0000-4000-8000-000000000001",
            "amount_sen": 3900,
            "expires_at": "2026-09-05T15:59:59+00:00",
            "plan_code": "essential",
            "activation_sequence_key": "company:42:initial",
        }

    def test_hitpay_checkout_uses_server_selected_gateway(self):
        from app.services.subscription_checkout_service import create_subscription_checkout

        with (
            patch(_SERVICE + ".prepare_subscription_checkout_order", return_value=self.prepared) as prepare,
            patch(_SERVICE + ".HitPayConfig.from_env") as config,
            patch(_SERVICE + ".create_payment_request", return_value={
                "gateway_order_id": "hitpay-request-1",
                "checkout_url": "https://securecheckout.sandbox.hit-pay.com/payment-request/@merchant/id/checkout",
            }) as create,
            patch(_SERVICE + ".update_subscription_order_status") as update,
        ):
            result = create_subscription_checkout(
                company_id=42,
                user_id=7,
                plan_code="essential",
                customer_name="Test User",
                customer_email="test@example.com",
                payment_gateway="hitpay",
            )

        self.assertEqual(result["payment_gateway"], "hitpay")
        prepare.assert_called_once_with(
            company_id=42,
            user_id=7,
            plan_code="essential",
            payment_gateway="hitpay",
            allow_existing_reusable_checkout=True,
        )
        create.assert_called_once()
        update.assert_called_once_with(
            self.prepared["order_reference"],
            "pending",
            gateway_order_id="hitpay-request-1",
            checkout_url=result["checkout_url"],
        )
        self.assertIs(create.call_args.kwargs["config"], config.return_value)

    def test_ambiguous_hitpay_create_keeps_order_for_reconciliation(self):
        from app.services.hitpay_service import HitPayAmbiguousError
        from app.services.subscription_checkout_service import create_subscription_checkout

        with (
            patch(_SERVICE + ".prepare_subscription_checkout_order", return_value=self.prepared),
            patch(_SERVICE + ".HitPayConfig.from_env"),
            patch(_SERVICE + ".create_payment_request", side_effect=HitPayAmbiguousError("timeout")),
            patch(_SERVICE + ".update_subscription_order_activation_state") as mark_reconcile,
            patch(_SERVICE + ".fail_pending_subscription_order_without_gateway_and_release_key") as release,
        ):
            with self.assertRaises(RuntimeError):
                create_subscription_checkout(
                    company_id=42,
                    user_id=7,
                    plan_code="essential",
                    customer_name="Test User",
                    customer_email="test@example.com",
                    payment_gateway="hitpay",
                )

        mark_reconcile.assert_called_once_with(
            order_reference=self.prepared["order_reference"],
            activation_error_code="gateway_create_ambiguous",
            activation_error_message="HitPay checkout creation requires reconciliation.",
            reconciliation_required=True,
        )
        release.assert_not_called()

    def test_default_gateway_remains_toyyibpay(self):
        from app.services.subscription_checkout_service import get_subscription_payment_gateway

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_subscription_payment_gateway(company_id=42), "toyyibpay")


if __name__ == "__main__":
    unittest.main()
