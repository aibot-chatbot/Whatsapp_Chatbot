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
sys.path.insert(0, r"C:\\Users\\User\\PycharmProjects\\python-whatsapp-bot-main")

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
