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
import unittest
from unittest.mock import MagicMock, patch, ANY
import pytest

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
# Frontend Tests
# ---------------------------------------------------------------------------

class TestProfileBillingNotificationsFrontend(unittest.TestCase):
    """Static tests for billing notifications HTML/JS in profile.html."""

    @classmethod
    def setUpClass(cls):
        with open(PROFILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            cls.html = f.read()

    def test_notification_section_exists(self):
        self.assertIn('billing-notifications-section', self.html)

    def test_loading_state_exists(self):
        self.assertIn('billing-notifications-loading', self.html)

    def test_empty_state_exists(self):
        self.assertIn('billing-notifications-empty', self.html)

    def test_error_state_exists(self):
        self.assertIn('billing-notifications-error', self.html)

    def test_content_container_exists(self):
        self.assertIn('billing-notifications-content', self.html)

    def test_notification_list_exists(self):
        self.assertIn('billing-notifications-list', self.html)

    def test_mark_all_read_button_exists(self):
        self.assertIn('btn-mark-all-read', self.html)

    def test_unread_count_badge(self):
        self.assertIn("loadBillingNotificationsUnreadCount", self.html)

    def test_company_wide_wording(self):
        self.assertIn("shared by all chatbots", self.html.lower())

    def test_js_functions_exist(self):
        self.assertIn("function loadBillingNotifications", self.html)
        self.assertIn("function markSingleNotificationRead", self.html)
        self.assertIn("function markAllNotificationsRead", self.html)
        self.assertIn("function loadBillingNotificationsUnreadCount", self.html)

    def test_init_calls_exist(self):
        self.assertIn("loadBillingNotifications()", self.html)
        self.assertIn("loadBillingNotificationsUnreadCount()", self.html)

    def test_retry_button_exists(self):
        self.assertIn('btn-notifications-retry', self.html)

    def test_notification_section_labels(self):
        self.assertIn("Billing Notifications", self.html)

    def test_escape_html_function_exists(self):
        self.assertIn("function escapeHtml", self.html)

    def test_safe_rendering_with_escape_html(self):
        self.assertIn("escapeHtml(n.title", self.html)
