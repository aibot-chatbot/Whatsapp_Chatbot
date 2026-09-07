"""HitPay pending orders use the existing reconciliation job."""

import unittest
from unittest.mock import patch


class TestHitPayReconciliationJob(unittest.TestCase):
    def test_pending_polls_rotate_without_starving_paid_orders_or_extending_expiry(self):
        from app.jobs import reconcile_subscription_orders as job
        from app.services import subscription_reconciliation_service as service

        orders = {
            ref: {
                "order_reference": ref,
                "status": "paid" if ref == "paid-order" else "pending",
                "payment_gateway": "hitpay",
                "gateway_order_id": ref,
                "amount_sen": 3900,
                "updated_at": f"2026-09-0{index}T00:00:00+00:00",
                "expires_at": "2026-09-08T00:00:00+00:00",
            }
            for index, ref in enumerate(("pending-1", "pending-2", "paid-order"), 1)
        }
        processed = []

        def oldest(status, limit):
            return sorted(
                (order for order in orders.values() if order["status"] == status),
                key=lambda order: order["updated_at"],
            )[:limit]

        def update_fields(ref, **fields):
            orders[ref].update(fields, updated_at=fields["last_reconciliation_at"])

        def lookup(config, request_id):
            return {
                "id": request_id, "reference_number": request_id,
                "status": "pending", "currency": "MYR", "amount": "39.00",
            }

        def reconcile(order_reference, company_id):
            processed.append(order_reference)
            if orders[order_reference]["status"] == "paid":
                orders[order_reference]["status"] = "credited"
                return {"outcome": "reconciled_and_completed"}
            return service._reconcile_pending_hitpay_order(orders[order_reference])

        with (
            patch.dict("os.environ", {"HITPAY_ENABLED": "true"}),
            patch.object(job, "get_reconcilable_subscription_orders", side_effect=lambda limit: oldest("paid", limit)),
            patch.object(job, "get_pending_hitpay_orders", side_effect=lambda limit: oldest("pending", limit)),
            patch.object(job, "reconcile_subscription_order", side_effect=reconcile),
            patch.object(service, "_update_fields", side_effect=update_fields),
            patch("app.services.hitpay_service.get_payment_request", side_effect=lookup),
            patch("app.services.hitpay_payment_service.process_hitpay_payment_request", return_value={"status": "pending"}),
        ):
            for _ in range(4):
                self.assertEqual(job.main(["--batch-size", "1"]), 0)

        self.assertEqual(processed, ["pending-1", "pending-2", "paid-order", "pending-1"])
        self.assertEqual(orders["paid-order"]["status"], "credited")
        for ref in ("pending-1", "pending-2"):
            self.assertIn("last_reconciliation_at", orders[ref])
            self.assertEqual(orders[ref]["expires_at"], "2026-09-08T00:00:00+00:00")
            self.assertEqual(orders[ref]["status"], "pending")

    def test_enabled_hitpay_pending_order_is_reconciled(self):
        from app.jobs import reconcile_subscription_orders as job

        order = {
            "order_reference": "hitpay-order-1",
            "status": "pending",
            "updated_at": "2026-09-04T00:00:00+00:00",
        }
        with (
            patch.dict("os.environ", {"HITPAY_ENABLED": "true"}, clear=False),
            patch.object(job, "get_reconcilable_subscription_orders", return_value=[]),
            patch.object(job, "get_pending_hitpay_orders", return_value=[order]) as pending,
            patch.object(job, "reconcile_subscription_order", return_value={
                "outcome": "hitpay_pending",
                "order_status": "pending",
                "message": "pending",
            }) as reconcile,
        ):
            result = job.main(["--batch-size", "10"])

        self.assertEqual(result, 0)
        pending.assert_called_once_with(limit=10)
        reconcile.assert_called_once_with(
            order_reference="hitpay-order-1", company_id=None
        )


if __name__ == "__main__":
    unittest.main()
