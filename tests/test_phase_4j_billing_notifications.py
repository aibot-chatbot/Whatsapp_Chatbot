"""tests/test_phase_4j_billing_notifications.py - Tests for Phase 4J billing notifications.

Tests cover:
  - Notification repository CRUD, deduplication, scoping, pagination.
  - Notification service generation functions.
  - Renewal reminder thresholds.
  - API auth, company isolation, mark-read.
  - Frontend section existence and safe rendering.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import re
import unittest
from unittest.mock import MagicMock, patch, ANY
import pytest


# --- Billing moved out of profile.html (2026-09) -------------------------------
# The billing surface now lives on its own page, split across markup, logic and
# styles. These assertions guard the billing guarantees, so they read all three
# parts of that page as one source rather than a single monolithic file.
def _read_billing_source():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _parts = []
    for _rel in (("billing.html",), ("assets", "js", "billing.js"), ("assets", "css", "billing.css")):
        _path = os.path.join(_root, "frontend", *_rel)
        with open(_path, "r", encoding="utf-8", errors="replace") as _fh:
            _parts.append(_fh.read())
    return chr(10).join(_parts)


def _fn_body(source, name):
    """Return the brace-matched body of a JS function declaration."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", source)
    if not m:
        raise AssertionError("function %s not found in billing source" % name)
    start = source.index("{", m.end() - 1)
    depth = 0
    for j in range(start, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError("unbalanced braces in %s" % name)
# ------------------------------------------------------------------------------


# Patch supabase before any app import
with patch("app.database.db.supabase", MagicMock()):
    from app import create_app

PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "profile.html",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase():
    """Mock the repository-level supabase reference."""
    with patch("app.database.billing_notification_repository.supabase") as mock:
        yield mock


@pytest.fixture
def sample_notification():
    return {
        "id": 1,
        "company_id": 42,
        "notification_type": "subscription_expiry_reminder",
        "severity": "warning",
        "title": "Subscription expires in 3 days",
        "message": "Your subscription period ends in 3 days. Renew now.",
        "event_key": "subscription:1:renewal_reminder:3d:2026-07-15",
        "reference_type": "subscription_id",
        "reference_value": "1",
        "is_read": False,
        "read_at": None,
        "created_at": "2026-07-11T12:00:00Z",
        "expires_at": None,
        "metadata": {},
    }


@pytest.fixture
def client():
    """Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Repository Tests
# ---------------------------------------------------------------------------

class TestCreateBillingNotification:
    def test_creates_notification(self, mock_supabase, sample_notification):
        from app.database.billing_notification_repository import create_billing_notification

        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        mock_insert = MagicMock()
        mock_supabase.table.return_value.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock(data=[sample_notification])

        result = create_billing_notification(
            company_id=42, notification_type="test", severity="info",
            title="Test", message="Test", event_key="test-key",
        )
        assert result is not None
        assert result["id"] == 1

    def test_duplicate_event_key_returns_none(self, mock_supabase, sample_notification):
        from app.database.billing_notification_repository import create_billing_notification

        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[sample_notification])

        result = create_billing_notification(
            company_id=42, notification_type="test", severity="info",
            title="Test", message="Test", event_key="test-key",
        )
        assert result is None

    def test_invalid_company_id_raises(self, mock_supabase):
        from app.database.billing_notification_repository import create_billing_notification
        with pytest.raises(ValueError, match="Invalid company_id"):
            create_billing_notification(
                company_id=0, notification_type="test", severity="info",
                title="Test", message="Test", event_key="test",
            )

    def test_invalid_severity_raises(self, mock_supabase):
        from app.database.billing_notification_repository import create_billing_notification
        with pytest.raises(ValueError, match="Invalid severity"):
            create_billing_notification(
                company_id=1, notification_type="test", severity="invalid",
                title="Test", message="Test", event_key="test",
            )


class TestListBillingNotifications:
    def test_lists_company_notifications(self, mock_supabase, sample_notification):
        from app.database.billing_notification_repository import list_billing_notifications

        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[sample_notification])

        results = list_billing_notifications(company_id=42)
        assert len(results) == 1
        assert results[0]["id"] == 1

    def test_company_isolation(self, mock_supabase):
        from app.database.billing_notification_repository import list_billing_notifications

        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        results = list_billing_notifications(company_id=99)
        assert len(results) == 0

    def test_pagination(self, mock_supabase):
        from app.database.billing_notification_repository import list_billing_notifications

        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        list_billing_notifications(company_id=42, limit=5, offset=10)
        mock_query.limit.assert_called_with(5)
        mock_query.offset.assert_called_with(10)

    def test_unread_filter(self, mock_supabase):
        from app.database.billing_notification_repository import list_billing_notifications

        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=[])

        list_billing_notifications(company_id=42, unread_only=True)
        mock_query.eq.assert_any_call("is_read", False)


class TestCountUnread:
    def test_counts_unread(self, mock_supabase):
        from app.database.billing_notification_repository import count_unread_billing_notifications

        mock_result = MagicMock()
        mock_result.count = 3
        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        count = count_unread_billing_notifications(company_id=42)
        assert count == 3

    def test_no_unread_returns_zero(self, mock_supabase):
        from app.database.billing_notification_repository import count_unread_billing_notifications

        mock_result = MagicMock()
        mock_result.count = 0
        mock_query = MagicMock()
        mock_supabase.table.return_value.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = mock_result

        count = count_unread_billing_notifications(company_id=42)
        assert count == 0


class TestMarkRead:
    def test_mark_single_read(self, mock_supabase):
        from app.database.billing_notification_repository import mark_billing_notification_read

        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": 1}])

        result = mark_billing_notification_read(company_id=42, notification_id=1)
        assert result is True

    def test_mark_nonexistent_returns_false(self, mock_supabase):
        from app.database.billing_notification_repository import mark_billing_notification_read

        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[])

        result = mark_billing_notification_read(company_id=42, notification_id=999)
        assert result is False

    def test_mark_all_read(self, mock_supabase):
        from app.database.billing_notification_repository import mark_all_billing_notifications_read

        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": 1}, {"id": 2}])

        count = mark_all_billing_notifications_read(company_id=42)
        assert count == 2

    def test_mark_single_read_includes_company_id_filter(self, mock_supabase):
        """mark_billing_notification_read must filter by company_id to prevent cross-company access."""
        from app.database.billing_notification_repository import mark_billing_notification_read

        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": 1}])

        mark_billing_notification_read(company_id=42, notification_id=7)

        # Verify both id and company_id are used in the WHERE clause
        mock_update.eq.assert_any_call("id", 7)
        mock_update.eq.assert_any_call("company_id", 42)
        mock_update.eq.assert_any_call("is_read", False)

    def test_mark_all_read_includes_company_id_filter(self, mock_supabase):
        """mark_all_billing_notifications_read must filter by company_id."""
        from app.database.billing_notification_repository import mark_all_billing_notifications_read

        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock(data=[{"id": 1}])

        mark_all_billing_notifications_read(company_id=99)

        mock_update.eq.assert_any_call("company_id", 99)
        mock_update.eq.assert_any_call("is_read", False)


# ---------------------------------------------------------------------------
# Service Tests
# ---------------------------------------------------------------------------

class TestBillingNotificationService:

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_renewal_reminder(self, mock_create):
        from app.services.billing_notification_service import notify_subscription_expiry_reminder

        mock_create.return_value = {"id": 1}

        notify_subscription_expiry_reminder(
            company_id=42, subscription_id=1,
            period_end="2026-07-15T00:00:00Z", days_remaining=3,
        )

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "subscription_expiry_reminder"
        assert kwargs["severity"] == "warning"
        assert "3 days" in kwargs["title"]
        assert kwargs["company_id"] == 42

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_expiry_today(self, mock_create):
        from app.services.billing_notification_service import notify_subscription_expiry_reminder

        mock_create.return_value = {"id": 1}

        notify_subscription_expiry_reminder(
            company_id=42, subscription_id=1,
            period_end="2026-07-11T00:00:00Z", days_remaining=0,
        )

        _, kwargs = mock_create.call_args
        assert "today" in kwargs["title"].lower()

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_grace_period_started(self, mock_create):
        from app.services.billing_notification_service import notify_grace_period_started

        mock_create.return_value = {"id": 1}

        notify_grace_period_started(
            company_id=42, subscription_id=1,
            period_end="2026-07-11T00:00:00Z",
            grace_period_end="2026-07-14T00:00:00Z",
        )

        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "grace_period"
        assert "grace" in kwargs["title"].lower()

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_subscription_expired(self, mock_create):
        from app.services.billing_notification_service import notify_subscription_expired

        mock_create.return_value = {"id": 1}

        notify_subscription_expired(
            company_id=42, subscription_id=1,
            period_end="2026-07-11T00:00:00Z",
        )

        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "subscription_expired"
        assert kwargs["severity"] == "critical"

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_payment_confirmed(self, mock_create):
        from app.services.billing_notification_service import notify_payment_confirmed

        mock_create.return_value = {"id": 1}

        notify_payment_confirmed(company_id=42, order_reference="ORD-123")
        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "payment_confirmed"

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_activation_completed(self, mock_create):
        from app.services.billing_notification_service import notify_activation_completed

        mock_create.return_value = {"id": 1}

        notify_activation_completed(company_id=42, order_reference="ORD-123")
        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "activation_completed"

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_activation_failed(self, mock_create):
        from app.services.billing_notification_service import notify_activation_failed

        mock_create.return_value = {"id": 1}

        notify_activation_failed(company_id=42, order_reference="ORD-123")
        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "activation_failed"

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_ai_credit_low(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_low

        mock_create.return_value = {"id": 1}

        notify_ai_credit_low(
            company_id=42, total_balance_micro_myr=300_000_000,
            threshold_micro_myr=500_000_000, period_key="2026-07",
        )
        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "ai_credit_low"

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_ai_credit_depleted(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_depleted

        mock_create.return_value = {"id": 1}

        notify_ai_credit_depleted(company_id=42, period_key="2026-07")
        _, kwargs = mock_create.call_args
        assert kwargs["notification_type"] == "ai_credit_depleted"
        assert kwargs["severity"] == "critical"

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_notification_failure_isolated(self, mock_create):
        from app.services.billing_notification_service import notify_payment_confirmed

        mock_create.side_effect = Exception("DB error")
        notify_payment_confirmed(company_id=42, order_reference="ORD-123")


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

class TestBillingNotificationsAPI:

    def test_list_notifications_unauthenticated(self, client):
        response = client.get("/api/billing/notifications")
        assert response.status_code in (401, 302)

    def test_unread_count_unauthenticated(self, client):
        response = client.get("/api/billing/notifications/unread-count")
        assert response.status_code in (401, 302)

    def test_mark_read_unauthenticated(self, client):
        response = client.post("/api/billing/notifications/1/read")
        assert response.status_code in (401, 302)

    def test_mark_all_unauthenticated(self, client):
        response = client.post("/api/billing/notifications/read-all")
        assert response.status_code in (401, 302)



# ---------------------------------------------------------------------------
# Phase 4A: Trial-aware AI-credit notification message tests
# ---------------------------------------------------------------------------

class TestAiCreditTrialMessages:

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_low_paid_message_contains_top_up(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_low

        mock_create.return_value = {"id": 1}

        notify_ai_credit_low(
            company_id=42, total_balance_micro_myr=300_000_000,
            threshold_micro_myr=500_000_000, period_key="2026-07",
            is_trial=False,
        )
        _, kwargs = mock_create.call_args
        assert "top up" in kwargs["message"].lower()
        assert "upgrade" not in kwargs["message"].lower()

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_low_trial_message_contains_upgrade_not_top_up(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_low

        mock_create.return_value = {"id": 1}

        notify_ai_credit_low(
            company_id=42, total_balance_micro_myr=300_000_000,
            threshold_micro_myr=500_000_000, period_key="2026-07",
            is_trial=True,
        )
        _, kwargs = mock_create.call_args
        assert "upgrade" in kwargs["message"].lower()
        assert "top up" not in kwargs["message"].lower()

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_critical_trial_message_contains_upgrade(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_critical

        mock_create.return_value = {"id": 1}

        notify_ai_credit_critical(
            company_id=42, total_balance_micro_myr=50_000_000,
            threshold_micro_myr=100_000_000, period_key="2026-07",
            is_trial=True,
        )
        _, kwargs = mock_create.call_args
        assert "upgrade" in kwargs["message"].lower()
        assert "top up" not in kwargs["message"].lower()

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_depleted_trial_message_contains_upgrade(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_depleted

        mock_create.return_value = {"id": 1}

        notify_ai_credit_depleted(
            company_id=42, period_key="2026-07",
            is_trial=True,
        )
        _, kwargs = mock_create.call_args
        assert "upgrade" in kwargs["message"].lower()
        assert "top up" not in kwargs["message"].lower()

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_depleted_paid_message_contains_top_up(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_depleted

        mock_create.return_value = {"id": 1}

        notify_ai_credit_depleted(
            company_id=42, period_key="2026-07",
            is_trial=False,
        )
        _, kwargs = mock_create.call_args
        assert "top up" in kwargs["message"].lower()
        assert "upgrade" not in kwargs["message"].lower()


# ---------------------------------------------------------------------------
# Phase 4A: Post-charge notification hook tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 4A follow-up: MYR conversion unit tests
# ---------------------------------------------------------------------------

class TestAiCreditMyrConversion:

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_one_myr_displays_as_rm_one(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_low

        mock_create.return_value = {"id": 1}

        # 1,000,000 micro-MYR = RM1.00
        notify_ai_credit_low(
            company_id=42, total_balance_micro_myr=1_000_000,
            threshold_micro_myr=5_000_000, period_key="2026-07",
            is_trial=False,
        )
        _, kwargs = mock_create.call_args
        assert "RM1.00" in kwargs["message"]

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_half_myr_displays_as_50_cents(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_low

        mock_create.return_value = {"id": 1}

        # 500,000 micro-MYR = RM0.50
        notify_ai_credit_low(
            company_id=42, total_balance_micro_myr=500_000,
            threshold_micro_myr=5_000_000, period_key="2026-07",
            is_trial=False,
        )
        _, kwargs = mock_create.call_args
        assert "RM0.50" in kwargs["message"]

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_not_off_by_hundred(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_low

        mock_create.return_value = {"id": 1}

        # 997,828 micro-MYR should display as ~RM1.00, NOT RM0.01
        notify_ai_credit_low(
            company_id=42, total_balance_micro_myr=997_828,
            threshold_micro_myr=5_000_000, period_key="2026-07",
            is_trial=False,
        )
        _, kwargs = mock_create.call_args
        assert "RM1.00" in kwargs["message"]
        assert "RM0.01" not in kwargs["message"]

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_trial_message_uses_correct_conversion(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_low

        mock_create.return_value = {"id": 1}

        notify_ai_credit_low(
            company_id=42, total_balance_micro_myr=750_000,
            threshold_micro_myr=1_000_000, period_key="2026-07",
            is_trial=True,
        )
        _, kwargs = mock_create.call_args
        assert "RM0.75" in kwargs["message"]
        assert "upgrade" in kwargs["message"].lower()

    @patch("app.services.billing_notification_service.create_billing_notification")
    def test_critical_message_uses_correct_conversion(self, mock_create):
        from app.services.billing_notification_service import notify_ai_credit_critical

        mock_create.return_value = {"id": 1}

        notify_ai_credit_critical(
            company_id=42, total_balance_micro_myr=50_000,
            threshold_micro_myr=100_000, period_key="2026-07",
            is_trial=False,
        )
        _, kwargs = mock_create.call_args
        assert "RM0.05" in kwargs["message"]

class TestPostChargeAiCreditNotifications:

    @patch("app.services.ai_router.notify_ai_credit_depleted")
    @patch("app.services.ai_router.get_company_subscription")
    def test_depleted_fires_when_balance_zero(
        self, mock_get_sub, mock_depleted,
    ):
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_depleted.assert_called_once()

    @patch("app.services.ai_router.notify_ai_credit_critical")
    @patch("app.services.ai_router.get_company_subscription")
    def test_critical_fires_when_balance_below_critical(
        self, mock_get_sub, mock_critical,
    ):
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 500_000,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_critical.assert_called_once()

    @patch("app.services.ai_router.notify_ai_credit_low")
    @patch("app.services.ai_router.get_company_subscription")
    def test_low_fires_when_balance_below_low_threshold(
        self, mock_get_sub, mock_low,
    ):
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 3_000_000,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_low.assert_called_once()

    @patch("app.services.ai_router.notify_ai_credit_low")
    @patch("app.services.ai_router.notify_ai_credit_critical")
    @patch("app.services.ai_router.notify_ai_credit_depleted")
    @patch("app.services.ai_router.get_company_subscription")
    def test_no_notification_when_balance_above_low_threshold(
        self, mock_get_sub, mock_depleted, mock_critical, mock_low,
    ):
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 6_000_000,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_depleted.assert_not_called()
        mock_critical.assert_not_called()
        mock_low.assert_not_called()

    @patch("app.services.ai_router.notify_ai_credit_depleted")
    @patch("app.services.ai_router.get_company_subscription")
    def test_trial_passes_is_trial_true(
        self, mock_get_sub, mock_depleted,
    ):
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "free"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        call_kwargs = mock_depleted.call_args[1]
        assert call_kwargs["is_trial"] is True

    @patch("app.services.ai_router.notify_ai_credit_depleted")
    @patch("app.services.ai_router.get_company_subscription")
    def test_paid_passes_is_trial_false(
        self, mock_get_sub, mock_depleted,
    ):
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        call_kwargs = mock_depleted.call_args[1]
        assert call_kwargs["is_trial"] is False

    @patch("app.services.ai_router.notify_ai_credit_depleted")
    @patch("app.services.ai_router.notify_ai_credit_critical")
    @patch("app.services.ai_router.notify_ai_credit_low")
    @patch("app.services.ai_router.get_company_subscription")
    def test_exception_in_notification_does_not_raise(
        self, mock_get_sub, mock_low, mock_critical, mock_depleted,
    ):
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        mock_depleted.side_effect = RuntimeError("notification db error")

        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        # Should not raise
        _maybe_notify_ai_credit_threshold(charge_result, 42)

# ---------------------------------------------------------------------------
# Frontend Tests
# ---------------------------------------------------------------------------

class TestProfileBillingNotificationsFrontend(unittest.TestCase):
    """Static tests for billing notifications HTML/JS in profile.html."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

    def test_notification_section_exists(self):
        self.assertIn('bl-notif-section', self.html)

    def test_loading_state_exists(self):
        self.assertIn('bl-notif-loading', self.html)

    def test_empty_state_exists(self):
        self.assertIn('bl-notif-empty', self.html)

    def test_error_state_exists(self):
        self.assertIn('bl-notif-error', self.html)

    def test_content_container_exists(self):
        self.assertIn('bl-notif-list', self.html)

    def test_notification_list_exists(self):
        self.assertIn('bl-notif-list', self.html)

    def test_mark_all_read_button_exists(self):
        self.assertIn('bl-notif-readall', self.html)

    def test_unread_count_badge(self):
        self.assertIn("loadUnreadCount", self.html)

    def test_company_wide_wording(self):
        self.assertIn("shared by all chatbots", self.html.lower())

    def test_js_functions_exist(self):
        self.assertIn("function loadNotifications", self.html)
        self.assertIn("function markNotificationRead", self.html)
        self.assertIn("function markAllNotificationsRead", self.html)
        self.assertIn("function loadUnreadCount", self.html)

    def test_init_calls_exist(self):
        self.assertIn("loadNotifications()", self.html)
        self.assertIn("loadUnreadCount()", self.html)

    def test_retry_button_exists(self):
        self.assertIn('bl-notif-retry', self.html)

    def test_notification_section_labels(self):
        self.assertIn("Billing Notifications", self.html)

    def test_backend_text_is_never_written_as_markup(self):
        """Stronger than escaping: the page never assigns innerHTML at all.

        The old page escaped values before concatenating them into an innerHTML
        string, so it needed an escapeHtml() helper. The rewritten billing page
        builds DOM nodes and assigns textContent, so there is no escaping
        function to test - and no injection sink to escape for.
        """
        self.assertNotRegex(self.html, re.compile(r"\.innerHTML\s*="))
        self.assertIn("node.textContent = text;", self.html)

    def test_safe_rendering_of_notification_title(self):
        body = _fn_body(self.html, "notificationItem")
        self.assertIn("notification.title", body)
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("escapeHtml", self.html)


# ---------------------------------------------------------------------------
# Phase 4B: Threshold default value tests
# ---------------------------------------------------------------------------

class TestThresholdDefaults:

    def test_default_low_threshold_is_5_myr(self):
        """Default low threshold should be 5,000,000 micro-MYR = RM5.00."""
        import os
        old_low = os.environ.pop("AI_CREDIT_LOW_THRESHOLD_MICRO_MYR", None)
        try:
            from app.services.ai_router import _load_notification_thresholds
            low, _ = _load_notification_thresholds()
            assert low == 5_000_000, f"Expected 5_000_000, got {low}"
        finally:
            if old_low is not None:
                os.environ["AI_CREDIT_LOW_THRESHOLD_MICRO_MYR"] = old_low

    def test_default_critical_threshold_is_1_myr(self):
        """Default critical threshold should be 1,000,000 micro-MYR = RM1.00."""
        import os
        old_crit = os.environ.pop("AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR", None)
        try:
            from app.services.ai_router import _load_notification_thresholds
            _, critical = _load_notification_thresholds()
            assert critical == 1_000_000, f"Expected 1_000_000, got {critical}"
        finally:
            if old_crit is not None:
                os.environ["AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR"] = old_crit

    def test_env_override_low_threshold(self):
        """Environment variable should override the low default."""
        import os
        os.environ["AI_CREDIT_LOW_THRESHOLD_MICRO_MYR"] = "7500000"
        try:
            from app.services.ai_router import _load_notification_thresholds
            low, _ = _load_notification_thresholds()
            assert low == 7_500_000
        finally:
            os.environ.pop("AI_CREDIT_LOW_THRESHOLD_MICRO_MYR", None)

    def test_env_override_critical_threshold(self):
        """Environment variable should override the critical default."""
        import os
        os.environ["AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR"] = "2000000"
        try:
            from app.services.ai_router import _load_notification_thresholds
            _, critical = _load_notification_thresholds()
            assert critical == 2_000_000
        finally:
            os.environ.pop("AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR", None)


class TestPostChargeThresholdBoundaries:

    @patch("app.services.ai_router.notify_ai_credit_low")
    @patch("app.services.ai_router.get_company_subscription")
    def test_balance_5_500_000_not_low(self, mock_get_sub, mock_low):
        """Balance above 5M default should NOT trigger low notification."""
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 5_500_000,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_low.assert_not_called()

    @patch("app.services.ai_router.notify_ai_credit_low")
    @patch("app.services.ai_router.get_company_subscription")
    def test_balance_4_999_999_triggers_low(self, mock_get_sub, mock_low):
        """Balance just below 5M default should trigger low notification."""
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 4_999_999,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_low.assert_called_once()

    @patch("app.services.ai_router.notify_ai_credit_critical")
    @patch("app.services.ai_router.get_company_subscription")
    def test_balance_997_828_is_critical_not_depleted(self, mock_get_sub, mock_critical):
        """RM 0.998 should trigger critical, not depleted."""
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 997_828,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_critical.assert_called_once()

    @patch("app.services.ai_router.notify_ai_credit_critical")
    @patch("app.services.ai_router.get_company_subscription")
    def test_balance_999_999_triggers_critical(self, mock_get_sub, mock_critical):
        """Balance just below 1M should trigger critical notification."""
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 999_999,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_critical.assert_called_once()

    @patch("app.services.ai_router.notify_ai_credit_depleted")
    @patch("app.services.ai_router.get_company_subscription")
    def test_balance_zero_triggers_depleted(self, mock_get_sub, mock_depleted):
        """Balance of exactly 0 should trigger depleted notification."""
        from app.services.ai_router import _maybe_notify_ai_credit_threshold

        mock_get_sub.return_value = {"plan_code": "essential"}
        charge_result = {
            "status": "charged",
            "included_balance_micro_myr": 0,
            "topup_balance_micro_myr": 0,
            "company_id": 42,
            "subscription_id": 1,
        }
        _maybe_notify_ai_credit_threshold(charge_result, 42)
        mock_depleted.assert_called_once()
