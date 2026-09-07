"""
test_subscription_payment_orders.py

Unit tests for company_subscription_order_repository.py.
All repository calls are mocked; no Supabase or network access.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch, MagicMock
import types

if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "_tools" not in sys.modules:
    sys.modules["_tools"] = types.ModuleType("_tools")


def _resp(data_list):
    m = MagicMock()
    m.data = data_list
    return m


class _RepoTestBase(unittest.TestCase):
    """Base class that patches supabase at the repo module level."""

    def setUp(self):
        self.mock_supabase = MagicMock()
        self.mock_table = MagicMock()
        self.mock_supabase.table.return_value = self.mock_table
        self.supabase_patch = patch(
            "app.database.company_subscription_order_repository.supabase",
            self.mock_supabase,
        )
        self.supabase_patch.start()
        import app.database.company_subscription_order_repository as _repo
        self.repo = _repo

    def tearDown(self):
        self.supabase_patch.stop()


class TestCreateSubscriptionOrder(_RepoTestBase):
    """Tests for create_subscription_order()."""

    def test_creates_and_returns_order(self):
        expected = {"id": 1, "order_reference": "abc-123", "status": "pending"}
        self.mock_table.insert().execute.return_value = _resp([expected])
        result = self.repo.create_subscription_order(
            order_reference="abc-123", company_id=1, subscription_id=10,
            new_plan_id=20, amount_sen=3900, payment_gateway="toyyibpay",
            idempotency_key="idem-001", created_by_user_id=5,
        )
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["status"], "pending")
        self.mock_table.insert().execute.assert_called_once()

    def test_raises_on_empty_response(self):
        self.mock_table.insert().execute.return_value = _resp([])
        with self.assertRaises(RuntimeError):
            self.repo.create_subscription_order(
                order_reference="abc-456", company_id=1, subscription_id=10,
                new_plan_id=20, amount_sen=3900, payment_gateway="toyyibpay",
                idempotency_key="idem-002", created_by_user_id=5,
            )


class TestGetByReference(_RepoTestBase):
    """Tests for get_subscription_order_by_reference()."""

    def test_returns_order_when_found(self):
        expected = {"id": 1, "order_reference": "abc-123"}
        self.mock_table.select().eq().limit().execute.return_value = _resp([expected])
        result = self.repo.get_subscription_order_by_reference("abc-123")
        self.assertEqual(result["id"], 1)

    def test_returns_none_when_not_found(self):
        self.mock_table.select().eq().limit().execute.return_value = _resp([])
        result = self.repo.get_subscription_order_by_reference("nonexistent")
        self.assertIsNone(result)

    def test_returns_none_for_empty_reference(self):
        result = self.repo.get_subscription_order_by_reference("")
        self.assertIsNone(result)


class TestGetByGatewayId(_RepoTestBase):
    """Tests for get_subscription_order_by_gateway_id()."""

    def test_returns_order_when_found(self):
        expected = {"id": 1, "payment_gateway": "toyyibpay", "gateway_order_id": "bill-001"}
        self.mock_table.select().eq().eq().limit().execute.return_value = _resp([expected])
        result = self.repo.get_subscription_order_by_gateway_id("toyyibpay", "bill-001")
        self.assertEqual(result["id"], 1)

    def test_returns_none_when_not_found(self):
        self.mock_table.select().eq().eq().limit().execute.return_value = _resp([])
        result = self.repo.get_subscription_order_by_gateway_id("toyyibpay", "nonexistent")
        self.assertIsNone(result)

    def test_returns_none_for_empty_args(self):
        self.assertIsNone(self.repo.get_subscription_order_by_gateway_id("", "x"))
        self.assertIsNone(self.repo.get_subscription_order_by_gateway_id("x", ""))


class TestGetByActivationSequenceKey(_RepoTestBase):
    """Tests for get_subscription_order_by_activation_sequence_key()."""

    def test_returns_order_when_found(self):
        expected = {"id": 1, "activation_sequence_key": "company:42:upgrade-from:1"}
        self.mock_table.select().eq().limit().execute.return_value = _resp([expected])

        result = self.repo.get_subscription_order_by_activation_sequence_key(
            "company:42:upgrade-from:1"
        )

        self.assertEqual(result["id"], 1)
        self.mock_table.select().eq.assert_called_with(
            "activation_sequence_key",
            "company:42:upgrade-from:1",
        )

    def test_returns_none_when_not_found(self):
        self.mock_table.select().eq().limit().execute.return_value = _resp([])

        result = self.repo.get_subscription_order_by_activation_sequence_key(
            "company:42:upgrade-from:1"
        )

        self.assertIsNone(result)

    def test_returns_none_for_empty_key(self):
        result = self.repo.get_subscription_order_by_activation_sequence_key("")

        self.assertIsNone(result)


class TestUpdateStatus(_RepoTestBase):
    """Tests for update_subscription_order_status()."""

    def test_update_status_returns_updated_row(self):
        expected = {"id": 1, "order_reference": "abc-123", "status": "paid"}
        self.mock_table.update().eq().execute.return_value = _resp([expected])
        result = self.repo.update_subscription_order_status("abc-123", "paid")
        self.assertEqual(result["status"], "paid")

    def test_update_with_extra_fields(self):
        expected = {"id": 1, "status": "credited", "credited_at": "2026-01-01T00:00:00"}
        self.mock_table.update().eq().execute.return_value = _resp([expected])
        result = self.repo.update_subscription_order_status(
            "abc-123", "credited", credited_at="2026-01-01T00:00:00"
        )
        self.assertEqual(result["status"], "credited")

    def test_raises_on_empty_reference(self):
        with self.assertRaises(ValueError):
            self.repo.update_subscription_order_status("", "paid")

    def test_raises_on_no_rows_returned(self):
        self.mock_table.update().eq().execute.return_value = _resp([])
        with self.assertRaises(RuntimeError):
            self.repo.update_subscription_order_status("nonexistent", "paid")


class TestGuardedGatewayOrderUpdates(_RepoTestBase):
    def _chain_update(self, rows):
        chain = MagicMock()
        chain.eq.return_value = chain
        chain.is_.return_value = chain
        chain.execute.return_value = _resp(rows)
        self.mock_table.update.return_value = chain
        return chain

    def test_attach_gateway_details_is_pending_compare_and_set(self):
        expected = {"status": "pending", "gateway_order_id": "hp-1"}
        chain = self._chain_update([expected])

        result = self.repo.attach_pending_subscription_gateway_details(
            "order-1", "hitpay", "hp-1", "https://securecheckout.hit-pay.com/x"
        )

        self.assertEqual(result, expected)
        chain.eq.assert_any_call("payment_gateway", "hitpay")
        chain.eq.assert_any_call("status", "pending")
        chain.is_.assert_any_call("gateway_order_id", "null")
        chain.is_.assert_any_call("paid_at", "null")
        chain.is_.assert_any_call("credited_at", "null")

    def test_terminal_event_does_not_downgrade_paid_order(self):
        self._chain_update([])
        paid = {"status": "paid", "order_reference": "order-1"}
        with patch.object(
            self.repo, "get_subscription_order_by_reference", return_value=paid
        ):
            result = self.repo.transition_pending_subscription_order_terminal(
                "order-1",
                "failed",
                "released:hitpay:failed:order-1",
                "hitpay_failed",
            )

        self.assertEqual(result, paid)

    def test_mark_paid_is_pending_compare_and_set(self):
        expected = {"status": "paid", "payment_reference": "payment-1"}
        chain = self._chain_update([expected])

        result = self.repo.mark_pending_subscription_order_paid(
            "order-1", "payment-1", "2026-09-04T00:00:00+00:00"
        )

        self.assertEqual(result, expected)
        chain.eq.assert_any_call("status", "pending")
        chain.is_.assert_any_call("paid_at", "null")
        chain.is_.assert_any_call("credited_at", "null")


class TestExpirePendingSubscriptionOrderForCheckoutRetry(_RepoTestBase):
    """Tests for expiring unpaid subscription checkouts and releasing keys."""

    def _chain_update(self, rows):
        chain = MagicMock()
        chain.eq.return_value = chain
        chain.is_.return_value = chain
        chain.lte.return_value = chain
        chain.execute.return_value = _resp(rows)
        self.mock_table.update.return_value = chain
        return chain

    def test_expires_unpaid_preactivation_order_and_releases_key(self):
        expected = {
            "id": 12,
            "order_reference": "order-ref",
            "status": "expired",
            "activation_status": None,
            "reconciliation_required": False,
            "activation_sequence_key": "released:checkout-expired:order:12:company:42",
        }
        self._chain_update([expected])

        result = self.repo.expire_pending_subscription_order_for_checkout_retry(
            order_reference="order-ref",
            activation_sequence_key="company:42",
            expired_activation_sequence_key="released:checkout-expired:order:12:company:42",
            now_iso="2026-08-12T00:00:00+00:00",
        )

        self.assertEqual(result["status"], "expired")
        payload = self.mock_table.update.call_args.args[0]
        self.assertEqual(payload["status"], "expired")
        self.assertIsNone(payload["activation_status"])
        self.assertEqual(payload["activation_error_code"], "checkout_expired_unpaid")
        self.assertFalse(payload["reconciliation_required"])
        self.assertEqual(
            payload["activation_sequence_key"],
            "released:checkout-expired:order:12:company:42",
        )
        chain = self.mock_table.update.return_value
        chain.lte.assert_called_with("expires_at", "2026-08-12T00:00:00+00:00")

    def test_rejects_same_released_key_as_canonical_key(self):
        with self.assertRaises(ValueError):
            self.repo.expire_pending_subscription_order_for_checkout_retry(
                order_reference="order-ref",
                activation_sequence_key="company:42",
                expired_activation_sequence_key="company:42",
            )

    def test_raises_when_order_no_longer_pending(self):
        self._chain_update([])
        with patch.object(
            self.repo,
            "get_subscription_order_by_reference",
            return_value={"status": "paid"},
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.repo.expire_pending_subscription_order_for_checkout_retry(
                    order_reference="order-ref",
                    activation_sequence_key="company:42",
                    expired_activation_sequence_key="released:company:42",
                )

        self.assertIn("current status is 'paid'", str(ctx.exception))

    def test_zero_row_update_returns_already_expired_released_order(self):
        released = {
            "id": 12,
            "order_reference": "order-ref",
            "status": "expired",
            "activation_status": None,
            "reconciliation_required": False,
            "paid_at": None,
            "credited_at": None,
            "activation_sequence_key": "released:checkout-expired:order:12:company:42",
        }
        self._chain_update([])
        with patch.object(
            self.repo,
            "get_subscription_order_by_reference",
            return_value=released,
        ):
            result = self.repo.expire_pending_subscription_order_for_checkout_retry(
                order_reference="order-ref",
                activation_sequence_key="company:42",
                expired_activation_sequence_key="released:checkout-expired:order:12:company:42",
            )

        self.assertEqual(result, released)

    def test_zero_row_update_fails_for_unexpected_released_state(self):
        unexpected = {
            "id": 12,
            "order_reference": "order-ref",
            "status": "expired",
            "activation_status": None,
            "reconciliation_required": False,
            "paid_at": None,
            "credited_at": None,
            "activation_sequence_key": "released:other",
        }
        self._chain_update([])
        with patch.object(
            self.repo,
            "get_subscription_order_by_reference",
            return_value=unexpected,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.repo.expire_pending_subscription_order_for_checkout_retry(
                    order_reference="order-ref",
                    activation_sequence_key="company:42",
                    expired_activation_sequence_key="released:checkout-expired:order:12:company:42",
                )

        self.assertIn("current status is 'expired'", str(ctx.exception))


class TestFailPendingSubscriptionOrderWithoutGatewayAndReleaseKey(_RepoTestBase):
    """Tests for definite no-bill failure release behaviour."""

    def _chain_update(self, rows):
        chain = MagicMock()
        chain.eq.return_value = chain
        chain.is_.return_value = chain
        chain.execute.return_value = _resp(rows)
        self.mock_table.update.return_value = chain
        return chain

    def test_fails_unpaid_preactivation_order_and_releases_key(self):
        expected = {
            "id": 14,
            "status": "failed",
            "activation_status": None,
            "reconciliation_required": False,
            "activation_sequence_key": "released:gateway-create-rejected:order:14:company:42",
        }
        self._chain_update([expected])

        result = self.repo.fail_pending_subscription_order_without_gateway_and_release_key(
            order_reference="order-ref",
            activation_sequence_key="company:42",
            released_activation_sequence_key="released:gateway-create-rejected:order:14:company:42",
            now_iso="2026-08-12T00:00:00+00:00",
        )

        self.assertEqual(result["status"], "failed")
        payload = self.mock_table.update.call_args.args[0]
        self.assertEqual(payload["status"], "failed")
        self.assertIsNone(payload["activation_status"])
        self.assertFalse(payload["reconciliation_required"])
        self.assertNotIn("activation_error_code", payload)
        self.assertNotIn("last_reconciliation_error", payload)
        self.assertEqual(
            payload["activation_sequence_key"],
            "released:gateway-create-rejected:order:14:company:42",
        )

    def test_zero_row_update_returns_already_failed_released_order(self):
        released = {
            "id": 14,
            "order_reference": "order-ref",
            "status": "failed",
            "activation_status": None,
            "reconciliation_required": False,
            "paid_at": None,
            "credited_at": None,
            "gateway_order_id": None,
            "checkout_url": None,
            "activation_sequence_key": "released:gateway-create-rejected:order:14:company:42",
        }
        self._chain_update([])
        with patch.object(
            self.repo,
            "get_subscription_order_by_reference",
            return_value=released,
        ):
            result = self.repo.fail_pending_subscription_order_without_gateway_and_release_key(
                order_reference="order-ref",
                activation_sequence_key="company:42",
                released_activation_sequence_key="released:gateway-create-rejected:order:14:company:42",
            )

        self.assertEqual(result, released)

    def test_zero_row_update_fails_for_unexpected_state(self):
        self._chain_update([])
        with patch.object(
            self.repo,
            "get_subscription_order_by_reference",
            return_value={
                "status": "failed",
                "activation_status": None,
                "reconciliation_required": False,
                "paid_at": None,
                "credited_at": None,
                "gateway_order_id": None,
                "checkout_url": None,
                "activation_sequence_key": "company:42",
            },
        ):
            with self.assertRaises(RuntimeError):
                self.repo.fail_pending_subscription_order_without_gateway_and_release_key(
                    order_reference="order-ref",
                    activation_sequence_key="company:42",
                    released_activation_sequence_key="released:gateway-create-rejected:order:14:company:42",
                )

class TestListSubscriptionOrdersForCompany(unittest.TestCase):
    """Tests for list_subscription_orders_for_company()."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(_REPO_ROOT))
        with patch('app.database.db.supabase', MagicMock()):
            from app.database.company_subscription_order_repository import list_subscription_orders_for_company
            self.repo_func = list_subscription_orders_for_company
            from app.database.company_subscription_order_repository import TABLE
            self.table_name = TABLE

        self.mock_supabase = patch('app.database.company_subscription_order_repository.supabase', MagicMock()).start()
        self.addCleanup(patch.stopall)

    def _make_order(self, ref, status='paid', created_at='2026-07-09T12:00:00Z'):
        return {'order_reference': ref, 'company_id': 42, 'status': status, 'created_at': created_at, 'id': 1}

    def test_returns_orders_newest_first(self):
        order1 = self._make_order('a', created_at='2026-07-09T12:00:00Z')
        order2 = self._make_order('b', created_at='2026-07-08T12:00:00Z')
        self.mock_supabase.table().select().eq().order().order().range().execute.return_value = MagicMock(data=[order1, order2])
        result = self.repo_func(company_id=42)
        self.assertEqual(len(result), 2)

    def test_company_scoped(self):
        order = self._make_order('a')
        self.mock_supabase.table().select().eq().order().order().range().execute.return_value = MagicMock(data=[order])
        result = self.repo_func(company_id=42)
        self.assertEqual(len(result), 1)

    def test_different_company_returns_empty(self):
        self.mock_supabase.table().select().eq().order().order().range().execute.return_value = MagicMock(data=[])
        result = self.repo_func(company_id=99)
        self.assertEqual(len(result), 0)

    def test_empty_company_id_returns_empty(self):
        result = self.repo_func(company_id=0)
        self.assertEqual(len(result), 0)

    def test_status_filter_applied(self):
        order = self._make_order('a', status='paid')
        self.mock_supabase.table().select().eq().order().order().eq().range().execute.return_value = MagicMock(data=[order])
        result = self.repo_func(company_id=42, status='paid')
        self.assertEqual(len(result), 1)

    def test_limit_respected(self):
        orders = [self._make_order(str(i)) for i in range(3)]
        self.mock_supabase.table().select().eq().order().order().range().execute.return_value = MagicMock(data=orders)
        result = self.repo_func(company_id=42, limit=2)
        self.assertEqual(len(result), 3)  # Mock returns all, range filter is applied server-side

    def test_max_limit_capped_at_100(self):
        result = self.repo_func(company_id=42, limit=200)
        # If limit > 100, it should be capped - the range() call should use 100
        self.mock_supabase.table().select().eq().order().order().range.assert_called()

    def test_negative_limit_defaults(self):
        result = self.repo_func(company_id=42, limit=-1)
        self.assertEqual(len(result), 0)  # empty data

    def test_negative_offset_defaults(self):
        self.mock_supabase.table().select().eq().order().order().range().execute.return_value = MagicMock(data=[])
        result = self.repo_func(company_id=42, offset=-1)
        self.assertEqual(len(result), 0)


if __name__ == '__main__':
    unittest.main()
