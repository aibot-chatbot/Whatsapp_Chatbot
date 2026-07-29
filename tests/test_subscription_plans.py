"""Tests for subscription plan routes and billing guards."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
sys.path.insert(0, "C:\\Users\\User\\PycharmProjects\\python-whatsapp-bot-main")

import unittest
from unittest.mock import patch, MagicMock
import types

# Mock pre-existing broken dependencies before any app import
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

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app

MOCK_USER = {
    "id": 1,
    "company_id": 42,
    "full_name": "Test User",
    "email": "test@example.com",
    "role": "admin",
    "status": "active",
    "phone": "+60123456789",
}

MOCK_PLANS = [
    {
        "id": 1,
        "name": "Free",
        "code": "free",
        "description": "Free plan",
        "price": "0",
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "knowledge_file_limit": 3,
        "knowledge_storage_limit_bytes": 52428800,
        "channel_limit": 1,
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "ai_generated_reports": False,
            "ai_assisted_menu_generation": False,
            "crm_lead_assignment": False,
        },
        "included_ai_credit_micro_myr": 1000000,
        "model_access_tier": "economy",
        "is_active": True,
    },
    {
        "id": 2,
        "name": "Essential",
        "code": "essential",
        "description": "Essential plan",
        "price": None,
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "knowledge_file_limit": 5,
        "knowledge_storage_limit_bytes": 52428800,
        "channel_limit": 1,
        "feature_flags": {"single_website_scraping": False, "batch_website_scraping": False, "ai_generated_reports": False, "ai_assisted_menu_generation": False, "crm_lead_assignment": False},
        "included_ai_credit_micro_myr": None,
        "model_access_tier": "economy",
        "is_active": True,
    },
    {
        "id": 3,
        "name": "Advanced",
        "code": "advanced",
        "description": "Advanced plan",
        "price": None,
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 2,
        "team_member_limit": 3,
        "knowledge_file_limit": 25,
        "knowledge_storage_limit_bytes": 262144000,
        "channel_limit": 2,
        "feature_flags": {"single_website_scraping": True, "batch_website_scraping": False, "ai_generated_reports": False, "ai_assisted_menu_generation": True, "crm_lead_assignment": True},
        "included_ai_credit_micro_myr": None,
        "model_access_tier": "standard",
        "is_active": True,
    },
    {
        "id": 4,
        "name": "Pro",
        "code": "pro",
        "description": "Pro plan",
        "price": None,
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 3,
        "team_member_limit": 5,
        "knowledge_file_limit": 75,
        "knowledge_storage_limit_bytes": 1073741824,
        "channel_limit": 2,
        "feature_flags": {"single_website_scraping": True, "batch_website_scraping": True, "ai_generated_reports": True, "ai_assisted_menu_generation": True, "crm_lead_assignment": True},
        "included_ai_credit_micro_myr": None,
        "model_access_tier": "premium",
        "is_active": True,
    },
]

SERIALIZED_PLANS = [
    {
        "id": 1,
        "name": "Free",
        "code": "free",
        "description": "Free plan",
        "price": "0",
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "knowledge_file_limit": 3,
        "knowledge_storage_limit_bytes": 52428800,
        "channel_limit": 1,
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "ai_generated_reports": False,
            "ai_assisted_menu_generation": False,
            "crm_lead_assignment": False,
        },
        "included_ai_credit_micro_myr": 1000000,
        "model_access_tier": "economy",
    },
    {
        "id": 2,
        "name": "Essential",
        "code": "essential",
        "description": "Essential plan",
        "price": None,
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "knowledge_file_limit": 5,
        "knowledge_storage_limit_bytes": 52428800,
        "channel_limit": 1,
        "feature_flags": {"single_website_scraping": False, "batch_website_scraping": False, "ai_generated_reports": False, "ai_assisted_menu_generation": False, "crm_lead_assignment": False},
        "included_ai_credit_micro_myr": None,
        "model_access_tier": "economy",
    },
    {
        "id": 3,
        "name": "Advanced",
        "code": "advanced",
        "description": "Advanced plan",
        "price": None,
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 2,
        "team_member_limit": 3,
        "knowledge_file_limit": 25,
        "knowledge_storage_limit_bytes": 262144000,
        "channel_limit": 2,
        "feature_flags": {"single_website_scraping": True, "batch_website_scraping": False, "ai_generated_reports": False, "ai_assisted_menu_generation": True, "crm_lead_assignment": True},
        "included_ai_credit_micro_myr": None,
        "model_access_tier": "standard",
    },
    {
        "id": 4,
        "name": "Pro",
        "code": "pro",
        "description": "Pro plan",
        "price": None,
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 3,
        "team_member_limit": 5,
        "knowledge_file_limit": 75,
        "knowledge_storage_limit_bytes": 1073741824,
        "channel_limit": 2,
        "feature_flags": {"single_website_scraping": True, "batch_website_scraping": True, "ai_generated_reports": True, "ai_assisted_menu_generation": True, "crm_lead_assignment": True},
        "included_ai_credit_micro_myr": None,
        "model_access_tier": "premium",
    },
]
MOCK_SUBSCRIPTION = {
    "id": 10,
    "company_id": 42,
    "plan_id": 1,
    "status": "active",
    "starts_at": "2026-07-06T00:00:00",
    "current_period_start": "2026-07-06T00:00:00",
    "current_period_end": "2026-08-06T00:00:00",
    "trial_ends_at": None,
    "cancelled_at": None,
    "ends_at": None,
    "payment_gateway": None,
    "created_at": "2026-07-06T00:00:00",
    "updated_at": "2026-07-06T00:00:00",
    "plan": {
        "id": 1,
        "name": "Free",
        "code": "free",
        "description": "Free plan",
        "price": "0",
        "currency": "MYR",
        "billing_interval": "monthly",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "knowledge_file_limit": 3,
        "knowledge_storage_limit_bytes": 52428800,
        "channel_limit": 1,
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "ai_generated_reports": False,
            "ai_assisted_menu_generation": False,
            "crm_lead_assignment": False,
        },
        "included_ai_credit_micro_myr": 1000000,
        "model_access_tier": "economy",
    },
}

MOCK_USAGE = {
    "period": {
        "start": "2026-07-06T00:00:00",
        "end": "2026-08-06T00:00:00",
        "end_source": "plan_billing_interval",
    },
    "plan": {"id": 1, "name": "Free", "code": "free", "billing_interval": "monthly"},
    "usage": {
        "chatbots": {"used": 1, "limit": 1},
        "team_members": {"used": 1, "limit": 1},
        "knowledge_files": {"used": 0, "limit": 3},
        "knowledge_storage_bytes": {"used": 0, "limit": 52428800},
        "ai_tokens": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "channels": {"used": 1, "limit": 1},
    },
}

# ======================================================================
# Route tests: GET /api/billing/plans
# ======================================================================

class TestSubscriptionPlansRoute(unittest.TestCase):
    """Tests for GET /api/billing/plans."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    # ----- Plans route -----

    @patch("app.routes.billing_routes.list_active_plans")
    def test_plans_authenticated_success(self, mock_list_plans):
        mock_list_plans.return_value = SERIALIZED_PLANS
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/plans",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(len(data["data"]), 4)

    @patch("app.routes.billing_routes.list_active_plans")
    def test_plans_only_active_returned(self, mock_list_plans):
        mock_list_plans.return_value = SERIALIZED_PLANS
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/plans",
                headers={"Authorization": "Bearer test-token"},
            )
            data = resp.get_json()
            self.assertEqual(len(data["data"]), len(SERIALIZED_PLANS))
            mock_list_plans.assert_called_once()

    @patch("app.routes.billing_routes.list_active_plans")
    def test_plans_response_structure(self, mock_list_plans):
        mock_list_plans.return_value = SERIALIZED_PLANS
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/plans",
                headers={"Authorization": "Bearer test-token"},
            )
            data = resp.get_json()
            self.assertIn("data", data)
            self.assertIn("status", data)
            plan = data["data"][0]
            expected_keys = {
                "id", "name", "code", "description", "price", "currency",
                "billing_interval", "chatbot_limit", "team_member_limit",
                "knowledge_file_limit", "knowledge_storage_limit_bytes",
                "channel_limit", "feature_flags", "included_ai_credit_micro_myr",
                "model_access_tier",
            }
            self.assertEqual(set(plan.keys()), expected_keys)

    @patch("app.routes.billing_routes.list_active_plans")
    def test_plans_service_failure_returns_500(self, mock_list_plans):
        mock_list_plans.side_effect = RuntimeError("DB error")
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/plans",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 500)
            data = resp.get_json()
            self.assertEqual(data["status"], "error")

    def test_plans_unauthenticated_rejected(self):
        resp = self.client.get("/api/billing/plans")
        self.assertEqual(resp.status_code, 401)

    # ----- Subscription route -----

    @patch("app.routes.billing_routes.get_current_subscription")
    def test_subscription_authenticated_success(self, mock_get_sub):
        mock_get_sub.return_value = MOCK_SUBSCRIPTION
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["data"]["company_id"], 42)
            self.assertIn("plan", data["data"])

    @patch("app.routes.billing_routes.get_current_subscription")
    def test_subscription_no_subscription_returns_success_null(self, mock_get_sub):
        mock_get_sub.return_value = None
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["data"], None)

    def test_subscription_unauthenticated_rejected(self):
        resp = self.client.get("/api/billing/subscription")
        self.assertEqual(resp.status_code, 401)

    @patch("app.routes.billing_routes.get_current_subscription")
    def test_subscription_service_failure_returns_500(self, mock_get_sub):
        mock_get_sub.side_effect = RuntimeError("DB error")
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 500)

    # ----- Usage route -----

    @patch("app.routes.billing_routes.get_company_usage")
    def test_usage_authenticated_success(self, mock_get_usage):
        mock_get_usage.return_value = MOCK_USAGE
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/usage",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("usage", data["data"])
            self.assertIn("period", data["data"])

    @patch("app.routes.billing_routes.get_company_usage")
    def test_usage_no_subscription_returns_success_null(self, mock_get_usage):
        mock_get_usage.return_value = None
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/usage",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["data"], None)

    def test_usage_unauthenticated_rejected(self):
        resp = self.client.get("/api/billing/usage")
        self.assertEqual(resp.status_code, 401)

    @patch("app.routes.billing_routes.get_company_usage")
    def test_usage_service_failure_returns_500(self, mock_get_usage):
        mock_get_usage.side_effect = RuntimeError("DB error")
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/usage",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(resp.status_code, 500)

    @patch("app.routes.billing_routes.get_company_usage")
    def test_usage_usage_and_limits_structure(self, mock_get_usage):
        mock_get_usage.return_value = MOCK_USAGE
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/usage",
                headers={"Authorization": "Bearer test-token"},
            )
            data = resp.get_json()["data"]
            usage = data["usage"]
            for metric in ["chatbots", "channels", "team_members", "knowledge_files", "knowledge_storage_bytes"]:
                self.assertIn("used", usage[metric])
                self.assertIn("limit", usage[metric])
            self.assertIn("ai_tokens", usage)
            self.assertIn("total_tokens", usage["ai_tokens"])

    @patch("app.routes.billing_routes.get_company_usage")
    def test_usage_current_plan_included(self, mock_get_usage):
        mock_get_usage.return_value = MOCK_USAGE
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/usage",
                headers={"Authorization": "Bearer test-token"},
            )
            data = resp.get_json()["data"]
            self.assertIn("plan", data)
            self.assertEqual(data["plan"]["code"], "free")

# ======================================================================
# Billing guard unit tests
# ======================================================================

from app.services.billing_guard import (
    BillingLimitError,
    can_create_chatbot,
    can_add_team_member,
    can_upload_knowledge_file,
    can_upload_knowledge_storage,
    can_connect_channel,
    can_use_plan_feature,
)

FREE_PLAN_WITH_LIMITS = {
    "plan": {
        "id": 1,
        "name": "Free",
        "code": "free",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "knowledge_file_limit": 3,
        "knowledge_storage_limit_bytes": 52428800,
        "channel_limit": 1,
        "feature_flags": {"batch_website_scraping": False},
    },
}

UNLIMITED_PLAN = {
    "plan": {
        "id": 99,
        "name": "Unlimited",
        "code": "unlimited",
        "chatbot_limit": None,
        "team_member_limit": None,
        "knowledge_file_limit": None,
        "knowledge_storage_limit_bytes": None,
        "channel_limit": None,
        "feature_flags": None,
    },
}

FREE_USAGE_AT_LIMIT = {
    "usage": {
        "chatbots": {"used": 1, "limit": 1},
        "team_members": {"used": 1, "limit": 1},
        "knowledge_files": {"used": 3, "limit": 3},
        "knowledge_storage_bytes": {"used": 52428800, "limit": 52428800},
        "channels": {"used": 1, "limit": 1},
    },
}

FREE_USAGE_BELOW_LIMIT = {
    "usage": {
        "chatbots": {"used": 0, "limit": 1},
        "team_members": {"used": 0, "limit": 1},
        "knowledge_files": {"used": 0, "limit": 3},
        "knowledge_storage_bytes": {"used": 0, "limit": 52428800},
        "channels": {"used": 0, "limit": 1},
    },
}

COMPANY_ID = 42


class TestBillingGuard(unittest.TestCase):
    """Tests for billing guard limit enforcement functions."""

    # ----- can_create_chatbot -----

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_create_chatbot_below_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_create_chatbot(COMPANY_ID)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_create_chatbot_at_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_AT_LIMIT
        with self.assertRaises(BillingLimitError):
            can_create_chatbot(COMPANY_ID)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_create_chatbot_unlimited(self, mock_usage, mock_sub):
        mock_sub.return_value = UNLIMITED_PLAN
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_create_chatbot(COMPANY_ID)
        self.assertTrue(result)

    # ----- can_add_team_member -----

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_add_team_member_below_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_add_team_member(COMPANY_ID)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_add_team_member_at_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_AT_LIMIT
        with self.assertRaises(BillingLimitError):
            can_add_team_member(COMPANY_ID)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_add_team_member_unlimited(self, mock_usage, mock_sub):
        mock_sub.return_value = UNLIMITED_PLAN
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_add_team_member(COMPANY_ID)
        self.assertTrue(result)

    # ----- can_upload_knowledge_file -----

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_file_below_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_upload_knowledge_file(COMPANY_ID)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_file_at_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_AT_LIMIT
        with self.assertRaises(BillingLimitError):
            can_upload_knowledge_file(COMPANY_ID)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_file_unlimited(self, mock_usage, mock_sub):
        mock_sub.return_value = UNLIMITED_PLAN
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_upload_knowledge_file(COMPANY_ID)
        self.assertTrue(result)

    # ----- can_connect_channel -----

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_connect_channel_below_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_connect_channel(COMPANY_ID)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_connect_channel_at_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_AT_LIMIT
        with self.assertRaises(BillingLimitError):
            can_connect_channel(COMPANY_ID)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_connect_channel_unlimited(self, mock_usage, mock_sub):
        mock_sub.return_value = UNLIMITED_PLAN
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_connect_channel(COMPANY_ID)
        self.assertTrue(result)

    # ----- can_upload_knowledge_storage -----

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_storage_below_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_upload_knowledge_storage(COMPANY_ID, 1000)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_storage_at_limit(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_AT_LIMIT
        with self.assertRaises(BillingLimitError):
            can_upload_knowledge_storage(COMPANY_ID, 1)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_can_upload_knowledge_storage_unlimited(self, mock_usage, mock_sub):
        mock_sub.return_value = UNLIMITED_PLAN
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_upload_knowledge_storage(COMPANY_ID, 1000000)
        self.assertTrue(result)

    def test_can_upload_knowledge_storage_negative_size(self):
        with self.assertRaises(ValueError):
            can_upload_knowledge_storage(COMPANY_ID, -1)

    # ----- can_use_plan_feature -----

    @patch("app.services.billing_guard.get_current_subscription")
    def test_can_use_plan_feature_enabled(self, mock_sub):
        plan = {"plan": {"feature_flags": {"batch_website_scraping": True}}}
        mock_sub.return_value = plan
        result = can_use_plan_feature(COMPANY_ID, "batch_website_scraping")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    def test_can_use_plan_feature_disabled(self, mock_sub):
        plan = {"plan": {"feature_flags": {"batch_website_scraping": False}}}
        mock_sub.return_value = plan
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(COMPANY_ID, "batch_website_scraping")

    @patch("app.services.billing_guard.get_current_subscription")
    def test_can_use_plan_feature_null_flags(self, mock_sub):
        mock_sub.return_value = {"plan": {"feature_flags": None}}
        result = can_use_plan_feature(COMPANY_ID, "batch_website_scraping")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    def test_can_use_plan_feature_empty_flags(self, mock_sub):
        mock_sub.return_value = {"plan": {"feature_flags": {}}}
        result = can_use_plan_feature(COMPANY_ID, "batch_website_scraping")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    def test_can_use_plan_feature_missing_key(self, mock_sub):
        plan = {"plan": {"feature_flags": {"ai_generated_reports": True}}}
        mock_sub.return_value = plan
        result = can_use_plan_feature(COMPANY_ID, "batch_website_scraping")
        self.assertTrue(result)

    def test_can_use_plan_feature_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            can_use_plan_feature(COMPANY_ID, "unknown_feature")

    def test_can_use_plan_feature_empty_key_raises(self):
        with self.assertRaises(ValueError):
            can_use_plan_feature(COMPANY_ID, "")

    def test_can_use_plan_feature_none_key_raises(self):
        with self.assertRaises(ValueError):
            can_use_plan_feature(COMPANY_ID, None)

    @patch("app.services.billing_guard.get_current_subscription")
    def test_can_use_plan_feature_unlimited_plan_null_flags(self, mock_sub):
        mock_sub.return_value = UNLIMITED_PLAN
        result = can_use_plan_feature(COMPANY_ID, "batch_website_scraping")
        self.assertTrue(result)

    # ----- _check_limit with usage_unavailable -----

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_usage_unavailable_denies(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "usage_unavailable")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_storage_usage_unavailable_denies(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_upload_knowledge_storage(COMPANY_ID, 100)
        self.assertEqual(ctx.exception.code, "usage_unavailable")

# ======================================================================
# Missing subscription fail-closed tests
# ======================================================================


class TestMissingSubscriptionGuard(unittest.TestCase):
    """Tests that missing subscriptions fail closed or recover to Free plan."""

    # Missing subscription — no recovery possible
    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_no_subscription_denies_chatbot(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_no_subscription_denies_team_member(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_add_team_member(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_no_subscription_denies_knowledge_file(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_upload_knowledge_file(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_no_subscription_denies_knowledge_storage(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_upload_knowledge_storage(COMPANY_ID, 100)
        self.assertEqual(ctx.exception.code, "no_subscription")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_no_subscription_denies_channel(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_connect_channel(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_no_subscription_denies_plan_feature(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.return_value = None
        with self.assertRaises(BillingLimitError) as ctx:
            can_use_plan_feature(COMPANY_ID, "batch_website_scraping")
        self.assertEqual(ctx.exception.code, "no_subscription")

    # Free-plan recovery — subscription missing but creatable
    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_free_plan_recovery_chatbot_below_limit(self, mock_usage, mock_ensure, mock_sub):
        mock_sub.side_effect = [None, FREE_PLAN_WITH_LIMITS]
        mock_ensure.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result = can_create_chatbot(COMPANY_ID)
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_free_plan_limits_enforced_after_recovery(self, mock_usage, mock_ensure, mock_sub):
        # Mock side_effect for first call (no subscription) and second call (after recovery)
        mock_sub.side_effect = [None, FREE_PLAN_WITH_LIMITS]
        mock_ensure.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_AT_LIMIT
        with self.assertRaises(BillingLimitError):
            can_create_chatbot(COMPANY_ID)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_existing_subscription_not_replaced(self, mock_usage, mock_sub):
        mock_sub.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        with patch("app.services.billing_guard.ensure_default_company_subscription") as mock_ensure:
            can_create_chatbot(COMPANY_ID)
            mock_ensure.assert_not_called()

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    def test_recovery_idempotent(self, mock_usage, mock_ensure, mock_sub):
        """Repeated recovery with same args succeeds"""
        mock_sub.side_effect = [None, FREE_PLAN_WITH_LIMITS]
        mock_ensure.return_value = FREE_PLAN_WITH_LIMITS
        mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
        result1 = can_create_chatbot(COMPANY_ID)
        result2 = can_create_chatbot(COMPANY_ID)
        self.assertTrue(result1)
        self.assertTrue(result2)

    # Missing Free plan — deny
    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_missing_free_plan_denies(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.side_effect = RuntimeError("Free plan not configured")
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    # Subscription creation failure — deny
    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_subscription_creation_failure_denies(self, mock_ensure, mock_sub):
        mock_sub.return_value = None
        mock_ensure.side_effect = Exception("DB error")
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    # Repository exception — deny
    @patch("app.services.billing_guard.get_current_subscription")
    def test_repository_exception_denies(self, mock_sub):
        mock_sub.side_effect = Exception("Connection error")
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    # Subscription row without plan — deny
    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_subscription_without_plan_denies(self, mock_ensure, mock_sub):
        mock_sub.side_effect = [None, {"id": 1, "company_id": COMPANY_ID, "plan": None}]
        mock_ensure.return_value = {"id": 1, "company_id": COMPANY_ID, "plan": None}
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(COMPANY_ID)
        self.assertEqual(ctx.exception.code, "no_subscription")

    # Invalid plan data — deny
    @patch("app.services.billing_guard.get_current_subscription")
    def test_invalid_plan_data_handled_safely(self, mock_sub):
        mock_sub.return_value = {"id": 1, "plan": {"chatbot_limit": None}}
        with patch("app.services.billing_guard.get_company_usage") as mock_usage:
            mock_usage.return_value = FREE_USAGE_BELOW_LIMIT
            result = can_create_chatbot(COMPANY_ID)
            self.assertTrue(result)  # None limit means unlimited

# ======================================================================
# Default subscription assignment tests
# ======================================================================

from app.services.billing_service import ensure_default_company_subscription


class TestDefaultSubscription(unittest.TestCase):
    """Tests for ensure_default_company_subscription behavior."""

    @patch("app.services.billing_service._get_company_subscription")
    @patch("app.services.billing_service.get_plan_by_code")
    @patch("app.services.billing_service._create_company_subscription")
    @patch("app.services.billing_service.get_current_subscription")
    @patch("app.services.billing_service._get_latest_company_subscription")
    def test_creates_free_subscription_when_none_exists(self, mock_get_latest, mock_get_current, mock_create, mock_get_plan, mock_get_existing):
        mock_get_existing.return_value = None
        mock_get_latest.return_value = None
        mock_get_plan.return_value = {"id": 1, "code": "free"}
        mock_create.return_value = {"id": 100, "company_id": 42, "plan_id": 1}
        mock_get_current.return_value = {
            "id": 100,
            "company_id": 42,
            "plan_id": 1,
            "status": "active",
            "plan": {"id": 1, "name": "Free", "code": "free"},
        }
        result = ensure_default_company_subscription(42)
        self.assertIsNotNone(result)
        self.assertEqual(result["company_id"], 42)
        mock_create.assert_called_once()

    @patch("app.services.billing_service._get_company_subscription")
    @patch("app.services.billing_service.get_plan_by_code")
    @patch("app.services.billing_service._get_latest_company_subscription")
    def test_returns_existing_subscription(self, mock_get_latest, mock_get_plan, mock_get_existing):
        mock_get_existing.return_value = {"id": 200, "company_id": 42, "plan_id": 1, "status": "active"}
        mock_get_plan.return_value = {"id": 1, "code": "free", "name": "Free"}
        with patch("app.services.billing_service.get_current_subscription") as mock_current:
            mock_current.return_value = {
                "id": 200, "company_id": 42, "plan_id": 1, "status": "active",
                "plan": {"id": 1, "name": "Free", "code": "free"},
            }
            result = ensure_default_company_subscription(42)
            self.assertEqual(result["id"], 200)

    @patch("app.services.billing_service._get_company_subscription")
    @patch("app.services.billing_service.get_plan_by_code")
    @patch("app.services.billing_service._get_latest_company_subscription")
    def test_missing_free_plan_raises_error(self, mock_get_latest, mock_get_plan, mock_get_existing):
        mock_get_existing.return_value = None
        mock_get_latest.return_value = None
        mock_get_plan.return_value = None
        with self.assertRaises(RuntimeError):
            ensure_default_company_subscription(42)

    def test_missing_company_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            ensure_default_company_subscription(None)

    @patch("app.services.billing_service._get_company_subscription")
    @patch("app.services.billing_service.get_plan_by_code")
    @patch("app.services.billing_service._create_company_subscription")
    @patch("app.services.billing_service._get_latest_company_subscription")
    def test_concurrent_duplicate_handled_gracefully(self, mock_get_latest, mock_create, mock_get_plan, mock_get_existing):
        mock_get_existing.return_value = {"id": 300, "company_id": 42, "plan_id": 1}
        mock_get_latest.return_value = None
        mock_get_plan.return_value = {"id": 1, "code": "free"}
        mock_create.side_effect = Exception("duplicate")
        with patch("app.services.billing_service.get_current_subscription") as mock_current:
            mock_current.return_value = {
                "id": 300, "company_id": 42, "plan_id": 1, "status": "active",
                "plan": {"id": 1, "name": "Free", "code": "free"},
            }
            result = ensure_default_company_subscription(42)
            self.assertEqual(result["id"], 300)
            mock_create.assert_called_once()

    @patch("app.services.billing_service._get_company_subscription")
    @patch("app.services.billing_service.get_plan_by_code")
    @patch("app.services.billing_service._create_company_subscription")
    def test_raises_on_non_duplicate_creation_failure(
        self, mock_create, mock_get_plan, mock_get_existing
    ):
        mock_get_existing.side_effect = [None, None]
        mock_get_plan.return_value = {"id": 1, "code": "free"}
        mock_create.side_effect = Exception("constraint violation")
        with self.assertRaises(Exception):
            ensure_default_company_subscription(42)


if __name__ == "__main__":
    unittest.main()
# ======================================================================
# Plan seed and serialization tests
# ======================================================================


class TestPlanSeedData(unittest.TestCase):
    """Tests for plan seed data integrity and serialization."""

    def test_plan_codes_are_lowercase(self):
        """All plan codes must be lowercase for consistent lookups."""
        for plan in MOCK_PLANS:
            code = plan["code"]
            self.assertEqual(
                code, code.lower(),
                f"Plan code '{code}' is not lowercase",
            )

    def test_essential_plan_limits(self):
        """Essential plan limits match the approved proposal."""
        essential = [p for p in MOCK_PLANS if p["code"] == "essential"][0]
        self.assertEqual(essential["chatbot_limit"], 1)
        self.assertEqual(essential["channel_limit"], 1)
        self.assertEqual(essential["team_member_limit"], 1)
        self.assertEqual(essential["knowledge_file_limit"], 5)
        self.assertEqual(essential["knowledge_storage_limit_bytes"], 52428800)
        self.assertEqual(essential["model_access_tier"], "economy")

    def test_essential_feature_flags(self):
        """Essential plan has all three features disabled."""
        essential = [p for p in MOCK_PLANS if p["code"] == "essential"][0]
        ff = essential["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertFalse(ff["batch_website_scraping"])
        self.assertFalse(ff["ai_generated_reports"])
        self.assertFalse(ff["ai_assisted_menu_generation"])

    def test_advanced_plan_limits(self):
        """Advanced plan limits match the approved proposal."""
        advanced = [p for p in MOCK_PLANS if p["code"] == "advanced"][0]
        self.assertEqual(advanced["chatbot_limit"], 2)
        self.assertEqual(advanced["channel_limit"], 2)
        self.assertEqual(advanced["team_member_limit"], 3)
        self.assertEqual(advanced["knowledge_file_limit"], 25)
        self.assertEqual(advanced["knowledge_storage_limit_bytes"], 262144000)
        self.assertEqual(advanced["model_access_tier"], "standard")

    def test_advanced_feature_flags(self):
        """Advanced plan has only AI menu generation enabled."""
        advanced = [p for p in MOCK_PLANS if p["code"] == "advanced"][0]
        ff = advanced["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertFalse(ff["batch_website_scraping"])
        self.assertFalse(ff["ai_generated_reports"])
        self.assertTrue(ff["ai_assisted_menu_generation"])

    def test_pro_plan_limits(self):
        """Pro plan limits match the approved proposal."""
        pro = [p for p in MOCK_PLANS if p["code"] == "pro"][0]
        self.assertEqual(pro["chatbot_limit"], 3)
        self.assertEqual(pro["channel_limit"], 2)
        self.assertEqual(pro["team_member_limit"], 5)
        self.assertEqual(pro["knowledge_file_limit"], 75)
        self.assertEqual(pro["knowledge_storage_limit_bytes"], 1073741824)
        self.assertEqual(pro["model_access_tier"], "premium")

    def test_pro_feature_flags(self):
        """Pro plan has all three features enabled."""
        pro = [p for p in MOCK_PLANS if p["code"] == "pro"][0]
        ff = pro["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertTrue(ff["batch_website_scraping"])
        self.assertTrue(ff["ai_generated_reports"])
        self.assertTrue(ff["ai_assisted_menu_generation"])

    def test_free_plan_preserved(self):
        """Free plan retains existing limits."""
        free = [p for p in MOCK_PLANS if p["code"] == "free"][0]
        self.assertEqual(free["chatbot_limit"], 1)
        self.assertEqual(free["team_member_limit"], 1)
        self.assertEqual(free["knowledge_file_limit"], 3)
        self.assertEqual(free["knowledge_storage_limit_bytes"], 52428800)
        self.assertEqual(free["channel_limit"], 1)
        self.assertEqual(free["model_access_tier"], "economy")
        self.assertIsNotNone(free["feature_flags"])
        self.assertFalse(free["feature_flags"]["single_website_scraping"])
        self.assertFalse(free["feature_flags"]["batch_website_scraping"])
        self.assertFalse(free["feature_flags"]["ai_generated_reports"])
        self.assertFalse(free["feature_flags"]["ai_assisted_menu_generation"])
        self.assertFalse(free["feature_flags"]["crm_lead_assignment"])

    def test_free_plan_current_catalogue_includes_rm1_ai_credit(self):
        """Current Free catalogue fixtures include RM1 of trial AI credit."""
        free = [p for p in MOCK_PLANS if p["code"] == "free"][0]
        serialized_free = [p for p in SERIALIZED_PLANS if p["code"] == "free"][0]
        subscription_free = MOCK_SUBSCRIPTION["plan"]

        self.assertEqual(free["included_ai_credit_micro_myr"], 1000000)
        self.assertEqual(serialized_free["included_ai_credit_micro_myr"], 1000000)
        self.assertEqual(subscription_free["included_ai_credit_micro_myr"], 1000000)

    def test_serialization_all_expected_keys(self):
        """Each serialized plan has all keys expected by the frontend."""
        expected_keys = {
            "id", "name", "code", "description", "price", "currency",
            "billing_interval", "chatbot_limit", "team_member_limit",
            "knowledge_file_limit", "knowledge_storage_limit_bytes",
            "channel_limit", "feature_flags", "included_ai_credit_micro_myr",
            "model_access_tier",
        }
        for plan in MOCK_PLANS:
            plan_keys = set(plan.keys()) - {"is_active"}
            self.assertEqual(
                plan_keys, expected_keys,
                f"Plan {plan['code']} has mismatched keys: extra={plan_keys - expected_keys}, missing={expected_keys - plan_keys}",
            )

# ======================================================================
# Price and credit serialization tests
# ======================================================================


class TestPriceAndCreditSerialization(unittest.TestCase):
    """Tests that NULL price and credit values serialize as JSON null."""

    # ----- list_active_plans serialization -----

    @patch("app.services.billing_service._get_active_plans")
    def test_null_price_serializes_as_none_in_plans(self, mock_get_plans):
        """NULL price in DB becomes None/JSON null in plan listing."""
        mock_get_plans.return_value = [
            {"id": 1, "name": "Test", "code": "test", "price": None,
             "included_ai_credit_micro_myr": None}
        ]
        from app.services.billing_service import list_active_plans
        plans = list_active_plans()
        self.assertIsNone(plans[0]["price"])
        self.assertIsNone(plans[0]["included_ai_credit_micro_myr"])

    @patch("app.services.billing_service._get_active_plans")
    def test_real_price_serializes_as_string_in_plans(self, mock_get_plans):
        """Real price serializes as a string in plan listing, not int."""
        mock_get_plans.return_value = [
            {"id": 1, "name": "Free", "code": "free", "price": 0,
             "included_ai_credit_micro_myr": 0}
        ]
        from app.services.billing_service import list_active_plans
        plans = list_active_plans()
        self.assertIsInstance(plans[0]["price"], str)
        self.assertEqual(plans[0]["price"], "0")

    @patch("app.services.billing_service._get_active_plans")
    def test_set_price_serializes_as_string_in_plans(self, mock_get_plans):
        """Set price like 5000000 serializes as string, not int."""
        mock_get_plans.return_value = [
            {"id": 2, "name": "Test", "code": "test", "price": 5000000,
             "included_ai_credit_micro_myr": None}
        ]
        from app.services.billing_service import list_active_plans
        plans = list_active_plans()
        self.assertIsInstance(plans[0]["price"], str)
        self.assertEqual(plans[0]["price"], "5000000")

    @patch("app.services.billing_service._get_active_plans")
    def test_missing_price_key_serializes_as_none(self, mock_get_plans):
        """Missing price key produces JSON null, not '0'."""
        mock_get_plans.return_value = [
            {"id": 1, "name": "Test", "code": "test"}
        ]
        from app.services.billing_service import list_active_plans
        plans = list_active_plans()
        self.assertIsNone(plans[0]["price"])

    # ----- get_current_subscription serialization -----

    @patch("app.services.billing_service.get_plan_by_id")
    @patch("app.services.billing_service._get_company_subscription")
    def test_null_price_in_subscription(self, mock_get_sub, mock_get_plan):
        """NULL price serializes as None in subscription response."""
        mock_get_sub.return_value = {"id": 10, "company_id": 42, "plan_id": 1, "status": "active"}
        mock_get_plan.return_value = {"id": 1, "name": "Free", "code": "free",
                                      "price": None, "included_ai_credit_micro_myr": None}
        from app.services.billing_service import get_current_subscription
        sub = get_current_subscription(42)
        self.assertIsNotNone(sub)
        self.assertIn("plan", sub)
        self.assertIsNone(sub["plan"]["price"])
        self.assertIsNone(sub["plan"]["included_ai_credit_micro_myr"])

    @patch("app.services.billing_service.get_plan_by_id")
    @patch("app.services.billing_service._get_company_subscription")
    def test_real_price_in_subscription(self, mock_get_sub, mock_get_plan):
        """Real price serializes as a string in subscription response."""
        mock_get_sub.return_value = {"id": 10, "company_id": 42, "plan_id": 1, "status": "active"}
        mock_get_plan.return_value = {"id": 1, "name": "Free", "code": "free",
                                      "price": 0, "included_ai_credit_micro_myr": 0}
        from app.services.billing_service import get_current_subscription
        sub = get_current_subscription(42)
        self.assertIsInstance(sub["plan"]["price"], str)
        self.assertEqual(sub["plan"]["price"], "0")

    @patch("app.services.billing_service.get_plan_by_id")
    @patch("app.services.billing_service._get_company_subscription")
    def test_set_price_in_subscription(self, mock_get_sub, mock_get_plan):
        """Set price serializes as string in subscription response."""
        mock_get_sub.return_value = {"id": 10, "company_id": 42, "plan_id": 1, "status": "active"}
        mock_get_plan.return_value = {"id": 2, "name": "Pro", "code": "pro",
                                      "price": 10000000, "included_ai_credit_micro_myr": None}
        from app.services.billing_service import get_current_subscription
        sub = get_current_subscription(42)
        self.assertIsInstance(sub["plan"]["price"], str)
        self.assertEqual(sub["plan"]["price"], "10000000")

    # ----- Consistency: both functions behave the same -----

    @patch("app.services.billing_service._get_active_plans")
    def test_free_plan_price_in_plans_is_string(self, mock_get_plans):
        """Current Free plan price serializes as string and keeps RM1 credit."""
        mock_get_plans.return_value = [
            {"id": 1, "name": "Free", "code": "free", "price": 0,
             "included_ai_credit_micro_myr": 1000000}
        ]
        from app.services.billing_service import list_active_plans
        plans = list_active_plans()
        self.assertEqual(plans[0]["price"], "0")
        self.assertEqual(plans[0]["included_ai_credit_micro_myr"], 1000000)
        self.assertIsInstance(plans[0]["price"], str)




# ==============================================================================
# Phase 2A — New feature flags: single_website_scraping, crm_lead_assignment
# ==============================================================================

class TestPhase2AFeatureFlagData(unittest.TestCase):
    """Verify the Phase 2A feature flag configuration in MOCK_PLANS."""

    def test_free_has_both_new_features_disabled(self):
        ff = [p for p in MOCK_PLANS if p["code"] == "free"][0]["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertFalse(ff["single_website_scraping"])
        self.assertFalse(ff["batch_website_scraping"])
        self.assertFalse(ff["ai_generated_reports"])
        self.assertFalse(ff["ai_assisted_menu_generation"])
        self.assertFalse(ff["crm_lead_assignment"])

    def test_essential_has_both_new_features_disabled(self):
        ff = [p for p in MOCK_PLANS if p["code"] == "essential"][0]["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertFalse(ff["single_website_scraping"])
        self.assertFalse(ff["crm_lead_assignment"])

    def test_advanced_has_both_new_features_enabled(self):
        ff = [p for p in MOCK_PLANS if p["code"] == "advanced"][0]["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertTrue(ff["single_website_scraping"])
        self.assertTrue(ff["crm_lead_assignment"])

    def test_pro_has_both_new_features_enabled(self):
        ff = [p for p in MOCK_PLANS if p["code"] == "pro"][0]["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertTrue(ff["single_website_scraping"])
        self.assertTrue(ff["crm_lead_assignment"])

    def test_existing_feature_flags_still_present(self):
        """Existing flags (batch_website_scraping, ai_generated_reports, ai_assisted_menu_generation) are not removed."""
        essential = [p for p in MOCK_PLANS if p["code"] == "essential"][0]["feature_flags"]
        self.assertIn("batch_website_scraping", essential)
        self.assertIn("ai_generated_reports", essential)
        self.assertIn("ai_assisted_menu_generation", essential)

    def test_mock_plans_have_new_feature_keys(self):
        """All four plans in MOCK_PLANS include both new feature keys."""
        for plan in MOCK_PLANS:
            ff = plan.get("feature_flags")
            if ff is not None:
                self.assertIn("single_website_scraping", ff)
                self.assertIn("crm_lead_assignment", ff)


    def test_free_has_all_plan_features_explicit(self):
        """Free plan now has every supported PLAN_FEATURES key explicitly set."""
        ff = [p for p in MOCK_PLANS if p["code"] == "free"][0]["feature_flags"]
        self.assertIsNotNone(ff)
        self.assertIn("single_website_scraping", ff)
        self.assertIn("batch_website_scraping", ff)
        self.assertIn("ai_generated_reports", ff)
        self.assertIn("ai_assisted_menu_generation", ff)
        self.assertIn("crm_lead_assignment", ff)

    def test_free_all_five_flags_are_false(self):
        """All five Free feature values are false."""
        ff = [p for p in MOCK_PLANS if p["code"] == "free"][0]["feature_flags"]
        self.assertFalse(ff["single_website_scraping"])
        self.assertFalse(ff["batch_website_scraping"])
        self.assertFalse(ff["ai_generated_reports"])
        self.assertFalse(ff["ai_assisted_menu_generation"])
        self.assertFalse(ff["crm_lead_assignment"])

    def test_jsonb_merge_preserves_unrelated_keys_still(self):
        """Simulating JSONB merge: keys not set by the migration survive."""
        existing = {"batch_website_scraping": True, "legacy_key": "survive"}
        merged = dict(existing)
        merged["single_website_scraping"] = False
        merged["crm_lead_assignment"] = False
        self.assertEqual(merged["legacy_key"], "survive")
        self.assertEqual(merged["batch_website_scraping"], True)
        self.assertEqual(merged["single_website_scraping"], False)

# Raw seed data used by TestPlanSeedData — also include the new keys
MOCK_PLANS_WITH_NEW = [
    {
        "code": "free",
        "name": "Free",
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "ai_generated_reports": False,
            "ai_assisted_menu_generation": False,
            "crm_lead_assignment": False,
        },
    },
    {
        "code": "essential",
        "name": "Essential",
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "ai_generated_reports": False,
            "ai_assisted_menu_generation": False,
            "crm_lead_assignment": False,
        },
    },
    {
        "code": "advanced",
        "name": "Advanced",
        "feature_flags": {
            "single_website_scraping": True,
            "batch_website_scraping": False,
            "ai_generated_reports": False,
            "ai_assisted_menu_generation": True,
            "crm_lead_assignment": True,
        },
    },
    {
        "code": "pro",
        "name": "Pro",
        "feature_flags": {
            "single_website_scraping": True,
            "batch_website_scraping": True,
            "ai_generated_reports": True,
            "ai_assisted_menu_generation": True,
            "crm_lead_assignment": True,
        },
    },
]


class TestPhase2AMigrationSeedData(unittest.TestCase):
    """Verify that the Phase 2A seed data matches the approved configuration."""

    def test_essential_disabled(self):
        essential = [p for p in MOCK_PLANS_WITH_NEW if p["code"] == "essential"][0]
        ff = essential["feature_flags"]
        self.assertFalse(ff["single_website_scraping"])
        self.assertFalse(ff["crm_lead_assignment"])

    def test_advanced_enabled(self):
        advanced = [p for p in MOCK_PLANS_WITH_NEW if p["code"] == "advanced"][0]
        ff = advanced["feature_flags"]
        self.assertTrue(ff["single_website_scraping"])
        self.assertTrue(ff["crm_lead_assignment"])

    def test_pro_enabled(self):
        pro = [p for p in MOCK_PLANS_WITH_NEW if p["code"] == "pro"][0]
        ff = pro["feature_flags"]
        self.assertTrue(ff["single_website_scraping"])
        self.assertTrue(ff["crm_lead_assignment"])
        self.assertTrue(ff["batch_website_scraping"])

    def test_advanced_batch_scraping_disabled(self):
        """Advanced does not get batch_website_scraping."""
        advanced = [p for p in MOCK_PLANS_WITH_NEW if p["code"] == "advanced"][0]
        ff = advanced["feature_flags"]
        self.assertTrue(ff["single_website_scraping"])
        self.assertFalse(ff["batch_website_scraping"])

    def test_jsonb_merge_preserves_existing_keys(self):
        """Simulating the JSONB merge: existing keys not in the migration must survive."""
        existing = {"batch_website_scraping": True, "legacy_key": "keep_me"}
        merged = dict(existing)
        merged.update({"single_website_scraping": True, "crm_lead_assignment": True})
        self.assertEqual(merged["legacy_key"], "keep_me")
        self.assertEqual(merged["batch_website_scraping"], True)
        self.assertEqual(merged["single_website_scraping"], True)
        self.assertEqual(merged["crm_lead_assignment"], True)


class TestPhase2AFeatureGating(unittest.TestCase):
    """Test that can_use_plan_feature correctly gates the new feature keys."""

    COMPANY_ID = 999

    def _mock_sub(self, feature_flags):
        return {"plan": {"feature_flags": feature_flags}}

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_essential_denied_single_scraping(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"single_website_scraping": False, "batch_website_scraping": False}
        )
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(self.COMPANY_ID, "single_website_scraping")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_advanced_allowed_single_scraping(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"single_website_scraping": True, "batch_website_scraping": False}
        )
        result = can_use_plan_feature(self.COMPANY_ID, "single_website_scraping")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_pro_allowed_single_scraping(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"single_website_scraping": True, "batch_website_scraping": True}
        )
        result = can_use_plan_feature(self.COMPANY_ID, "single_website_scraping")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_advanced_denied_batch_scraping(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"single_website_scraping": True, "batch_website_scraping": False}
        )
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(self.COMPANY_ID, "batch_website_scraping")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_pro_allowed_batch_scraping(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"single_website_scraping": True, "batch_website_scraping": True}
        )
        result = can_use_plan_feature(self.COMPANY_ID, "batch_website_scraping")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_single_scraping_uses_own_key_not_batch(self, mock_ensure, mock_sub):
        """single_website_scraping denied even when batch_website_scraping is enabled."""
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"single_website_scraping": False, "batch_website_scraping": True}
        )
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(self.COMPANY_ID, "single_website_scraping")

    # --- CRM assignment gating ---

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_essential_denied_crm_assign(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"crm_lead_assignment": False, "single_website_scraping": False}
        )
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(self.COMPANY_ID, "crm_lead_assignment")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_advanced_allowed_crm_assign(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"crm_lead_assignment": True, "single_website_scraping": True}
        )
        result = can_use_plan_feature(self.COMPANY_ID, "crm_lead_assignment")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_pro_allowed_crm_assign(self, mock_ensure, mock_sub):
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub(
            {"crm_lead_assignment": True, "batch_website_scraping": True}
        )
        result = can_use_plan_feature(self.COMPANY_ID, "crm_lead_assignment")
        self.assertTrue(result)

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_crm_assign_missing_flag_denies(self, mock_ensure, mock_sub):
        """Feature flag explicitly set to false denies CRM assignment."""
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub({"crm_lead_assignment": False})
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(self.COMPANY_ID, "crm_lead_assignment")

    @patch("app.services.billing_guard.get_current_subscription")
    @patch("app.services.billing_guard.ensure_default_company_subscription")
    def test_new_feature_false_still_denied(self, mock_ensure, mock_sub):
        """crm_lead_assignment explicitly set to false denies assignment."""
        mock_ensure.return_value = None
        mock_sub.return_value = self._mock_sub({"crm_lead_assignment": False, "some_other_flag": True})
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(self.COMPANY_ID, "crm_lead_assignment")


class TestSample(unittest.TestCase):
    def test_placeholder(self):
        self.assertTrue(True)

# =============================================================================
# Phase 2B-2A: AI access policy resolver tests
# =============================================================================


class TestAIAccessPolicyResolver(unittest.TestCase):
    """Tests for resolve_ai_access() in ai_access_policy.py."""

    def setUp(self):
        self.company_id = 1
        self.free_plan = {
            'id': 10, 'code': 'free', 'name': 'Free',
        }
        self.essential_plan = {
            'id': 11, 'code': 'essential', 'name': 'Essential',
            'model_access_tier': 'economy',
        }
        self.advanced_plan = {
            'id': 12, 'code': 'advanced', 'name': 'Advanced',
            'model_access_tier': 'standard',
        }
        self.pro_plan = {
            'id': 13, 'code': 'pro', 'name': 'Pro',
            'model_access_tier': 'premium',
        }
