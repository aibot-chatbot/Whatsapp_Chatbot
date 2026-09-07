"""HitPay pending orders use the existing reconciliation job."""

import unittest
from unittest.mock import patch


class TestHitPayReconciliationJob(unittest.TestCase):
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
