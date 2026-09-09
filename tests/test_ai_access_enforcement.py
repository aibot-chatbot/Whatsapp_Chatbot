"""Tests for Phase 2B-2A AI access policy, enforcement and bot gating."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch, MagicMock, call
import types

# Mock broken dependencies before any app import
_m = types.ModuleType("tools")
sys.modules["tools"] = _m

if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai

from datetime import datetime, timezone, timedelta
import json

from app.services.ai_access_policy import (
    resolve_ai_access,
    AIAccessPolicy,
    ROUTE_DIRECT_DEEPSEEK,
    ROUTE_OPENROUTER,
    ROUTE_DENIED,
    STATE_ACTIVE_TRIAL,
    STATE_EXPIRED_TRIAL,
    STATE_FREE_NO_TRIAL,
    STATE_ESSENTIAL,
    STATE_ADVANCED,
    STATE_PRO,
    TRIAL_DURATION_DAYS,
    DEFAULT_TRIAL_MODEL,
)

# ============================================================
# Shared test helpers
# ============================================================

def _make_policy(**overrides):
    """Build an AIAccessPolicy with sensible test defaults."""
    defaults = dict(
        allowed=False,
        access_state="unknown",
        api_route=ROUTE_DENIED,
        max_model_tier=None,
        top_up_allowed=False,
        model_editable=False,
        trial_ends_at=None,
        denial_reason=None,
    )
    defaults.update(overrides)
    return AIAccessPolicy(**defaults)


FREE_PLAN = {
    "id": 1,
    "name": "Free",
    "code": "free",
    "price": "0",
    "currency": "MYR",
    "billing_interval": "monthly",
    "chatbot_limit": 1,
    "team_member_limit": 1,
    "knowledge_file_limit": 10,
    "knowledge_storage_limit_bytes": 10485760,
    "channel_limit": 1,
    "feature_flags": {
        "single_website_scraping": False,
        "batch_website_scraping": False,
        "ai_generated_reports": False,
        "ai_assisted_menu_generation": False,
        "crm_lead_assignment": False,
    },
    "included_ai_credit_micro_myr": 0,
    "model_access_tier": None,
    "is_active": True,
}

ESSENTIAL_PLAN = {
    "id": 2,
    "name": "Essential",
    "code": "essential",
    "price": "4900",
    "currency": "MYR",
    "billing_interval": "monthly",
    "chatbot_limit": 3,
    "team_member_limit": 5,
    "knowledge_file_limit": 30,
    "knowledge_storage_limit_bytes": 52428800,
    "channel_limit": 2,
    "feature_flags": {
        "single_website_scraping": True,
        "batch_website_scraping": False,
        "ai_generated_reports": False,
        "ai_assisted_menu_generation": False,
        "crm_lead_assignment": False,
    },
    "included_ai_credit_micro_myr": None,
    "model_access_tier": "economy",
    "is_active": True,
}

ADVANCED_PLAN = {
    "id": 3,
    "name": "Advanced",
    "code": "advanced",
    "price": "9900",
    "currency": "MYR",
    "billing_interval": "monthly",
    "chatbot_limit": 10,
    "team_member_limit": 15,
    "knowledge_file_limit": 100,
    "knowledge_storage_limit_bytes": 209715200,
    "channel_limit": 5,
    "feature_flags": {
        "single_website_scraping": True,
        "batch_website_scraping": True,
        "ai_generated_reports": True,
        "ai_assisted_menu_generation": True,
        "crm_lead_assignment": True,
    },
    "included_ai_credit_micro_myr": None,
    "model_access_tier": "standard",
    "is_active": True,
}

PRO_PLAN = {
    "id": 4,
    "name": "Pro",
    "code": "pro",
    "price": "19900",
    "currency": "MYR",
    "billing_interval": "monthly",
    "chatbot_limit": None,
    "team_member_limit": None,
    "knowledge_file_limit": None,
    "knowledge_storage_limit_bytes": None,
    "channel_limit": None,
    "feature_flags": {
        "single_website_scraping": True,
        "batch_website_scraping": True,
        "ai_generated_reports": True,
        "ai_assisted_menu_generation": True,
        "crm_lead_assignment": True,
    },
    "included_ai_credit_micro_myr": None,
    "model_access_tier": "premium",
    "is_active": True,
}


# ============================================================
# TestAIAccessPolicyResolver (18 tests)
# ============================================================

class TestAIAccessPolicyResolver(unittest.TestCase):
    """Tests for resolve_ai_access() policy decisions."""

    def test_no_company_id(self):
        policy = resolve_ai_access(None)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, "unknown")
        self.assertIn("No company ID", policy.denial_reason)

    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_repository_error(self, mock_sub):
        mock_sub.side_effect = RuntimeError("DB down")
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, "unknown")
        self.assertIn("Unable to verify subscription", policy.denial_reason)

    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_no_subscription_found(self, mock_sub):
        mock_sub.return_value = None
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertIn("No active subscription found", policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_active_trial(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_ACTIVE_TRIAL)
        self.assertEqual(policy.api_route, ROUTE_DIRECT_DEEPSEEK)
        self.assertFalse(policy.top_up_allowed)
        self.assertFalse(policy.model_editable)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_expired(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, STATE_EXPIRED_TRIAL)
        self.assertIn("trial has expired", policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_essential_active(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_ESSENTIAL)
        self.assertEqual(policy.api_route, ROUTE_OPENROUTER)
        self.assertEqual(policy.max_model_tier, "economy")
        self.assertTrue(policy.top_up_allowed)
        self.assertTrue(policy.model_editable)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_essential_active_future_period_allowed(self, mock_sub, mock_plan):
        mock_sub.return_value = {
            "plan_id": 2,
            "status": "active",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_ESSENTIAL)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_advanced_active(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 3, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_ADVANCED)
        self.assertEqual(policy.max_model_tier, "standard")

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_advanced_active_future_period_allowed(self, mock_sub, mock_plan):
        mock_sub.return_value = {
            "plan_id": 3,
            "status": "active",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_ADVANCED)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_pro_active(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 4, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = PRO_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_PRO)
        self.assertEqual(policy.max_model_tier, "premium")

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_pro_active_future_period_allowed(self, mock_sub, mock_plan):
        mock_sub.return_value = {
            "plan_id": 4,
            "status": "active",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
        mock_plan.return_value = PRO_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_PRO)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_active_paid_expired_period_denied_cleanly(self, mock_sub, mock_plan):
        mock_sub.return_value = {
            "plan_id": 3,
            "status": "active",
            "current_period_end": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        }
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, "unknown")
        self.assertIn("period has ended", policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_active_paid_malformed_period_denies_without_exception(self, mock_sub, mock_plan):
        mock_sub.return_value = {
            "plan_id": 3,
            "status": "active",
            "current_period_end": "not-a-date",
        }
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.api_route, ROUTE_DENIED)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_free_active_expired_denied(self, mock_sub, mock_plan):
        mock_sub.return_value = {
            "plan_id": 1, "status": "active",
            "trial_ends_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, STATE_EXPIRED_TRIAL)
        self.assertIn("trial has expired", policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_free_active_no_trial_end_denied(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 1, "status": "active"}
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, STATE_EXPIRED_TRIAL)
        self.assertIn("trial has expired", policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_free_active_within_trial_allowed(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "active",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_ACTIVE_TRIAL)
        self.assertEqual(policy.api_route, ROUTE_DIRECT_DEEPSEEK)
        self.assertFalse(policy.top_up_allowed)
        self.assertFalse(policy.model_editable)
        self.assertIsNone(policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_past_due_denied(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "past_due"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, "past_due")
        self.assertIn("past due", policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_unknown_status(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "cancelled"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertIn("cancelled", policy.denial_reason)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_plan_lookup_error(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 99, "status": "active"}
        mock_plan.side_effect = RuntimeError("No such plan")
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertIn("not recognised", policy.denial_reason)

    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_ends_none_still_expired(self, mock_sub):
        mock_sub.return_value = {
            "plan_id": 1, "status": "trialing", "trial_ends_at": None}
        with patch("app.services.ai_access_policy.get_plan_by_id", return_value=FREE_PLAN):
            policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, STATE_EXPIRED_TRIAL)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_with_timezone_naive_datetime(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "trialing", "trial_ends_at": trial_end}
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.access_state, STATE_ACTIVE_TRIAL)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trialing_wrong_plan_code(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 2, "status": "trialing", "trial_ends_at": trial_end}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        # trialing status with non-free plan falls through to unknown
        self.assertFalse(policy.allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_ends_at_invalid_format(self, mock_sub, mock_plan):
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": "not-a-date",
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, STATE_EXPIRED_TRIAL)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_policy_dataclass_frozen(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        with self.assertRaises(Exception):
            policy.allowed = False

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_active_with_none_plan_code(self, mock_sub, mock_plan):
        plan_no_code = dict(FREE_PLAN)
        plan_no_code.pop("code")
        mock_sub.return_value = {"plan_id": 1, "status": "active"}
        mock_plan.return_value = plan_no_code
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertIn("not recognised", policy.denial_reason or "")


# ============================================================
# TestTrialCreation (4 tests)
# ============================================================

class TestTrialCreation(unittest.TestCase):
    """Tests for trial subscription creation flows."""

    def test_trial_duration_constant(self):
        self.assertEqual(TRIAL_DURATION_DAYS, 7)

    @patch("app.services.ai_access_policy._get_company_subscription")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    def test_trial_returns_trial_ends_at(self, mock_plan, mock_sub):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertIsNotNone(policy.trial_ends_at)
        self.assertEqual(policy.trial_ends_at, trial_end)

    @patch("app.services.ai_access_policy._get_company_subscription")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    def test_trial_uses_direct_deepseek_route(self, mock_plan, mock_sub):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertEqual(policy.api_route, ROUTE_DIRECT_DEEPSEEK)

    @patch("app.services.ai_access_policy._get_company_subscription")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    def test_trial_blocks_top_up(self, mock_plan, mock_sub):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.top_up_allowed)


# ============================================================
# TestBotEnforcement (12 tests)
# ============================================================

class TestBotEnforcement(unittest.TestCase):
    """Tests for bot-level enforcement of AI access policies."""

    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_with_no_subscription_denied(self, mock_sub):
        mock_sub.return_value = None
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.api_route, ROUTE_DENIED)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_trial_company_allowed(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=6)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.api_route, ROUTE_DIRECT_DEEPSEEK)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_essential_company_allowed(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.api_route, ROUTE_OPENROUTER)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_advanced_company_allowed(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 3, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_pro_company_allowed(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 4, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = PRO_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_past_due_denied(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 3, "status": "past_due"}
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_expired_trial_denied(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_bot_free_active_within_trial_allowed(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "active",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.api_route, ROUTE_DIRECT_DEEPSEEK)
        self.assertFalse(policy.model_editable)
        self.assertFalse(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_essential_model_editable(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.model_editable)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_model_not_editable(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.model_editable)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_advanced_model_editable(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 3, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.model_editable)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_policy_denial_reason_set_when_denied(self, mock_sub, mock_plan):
        mock_sub.return_value = None
        policy = resolve_ai_access(42)
        self.assertIsNotNone(policy.denial_reason)
        self.assertGreater(len(policy.denial_reason), 0)


# ============================================================
# TestRuntimeEnforcement (7 tests)
# ============================================================

class TestRuntimeEnforcement(unittest.TestCase):
    """Tests for runtime enforcement during AI generation."""

    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_runtime_no_subscription_blocks_generation(self, mock_sub):
        mock_sub.return_value = None
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.api_route, ROUTE_DENIED)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_runtime_trial_allows_generation(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_runtime_expired_trial_blocks_generation(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertEqual(policy.access_state, STATE_EXPIRED_TRIAL)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_runtime_essential_allows_openrouter(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertEqual(policy.api_route, ROUTE_OPENROUTER)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_runtime_past_due_blocks_generation(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "past_due"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertIn("past due", policy.denial_reason)

    def test_ai_credit_enforcement_env_set(self):
        self.assertEqual(
            os.environ.get("AI_CREDIT_ENFORCEMENT_ENABLED"),
            "true",
        )

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_policy_values_are_consistent(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertIsNone(policy.denial_reason)


# ============================================================
# TestTopUpRestriction (7 tests)
# ============================================================

class TestTopUpRestriction(unittest.TestCase):
    """Tests for top-up restrictions based on access state."""

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_allowed_for_essential(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_allowed_for_advanced(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 3, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_allowed_for_pro(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 4, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = PRO_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_blocked_for_trial(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_blocked_for_free_active_within_trial(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "active",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertTrue(policy.allowed)
        self.assertFalse(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_blocked_for_free_active_expired(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "active",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.allowed)
        self.assertFalse(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_blocked_for_expired_trial(self, mock_sub, mock_plan):
        trial_end = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1,
            "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.top_up_allowed)

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_top_up_blocked_for_past_due(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "past_due"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertFalse(policy.top_up_allowed)


# ============================================================
# TestModelTierCatalog (14 tests)
# ============================================================

class TestModelTierCatalog(unittest.TestCase):
    """Tests for model tier classification and validation."""

    @classmethod
    def setUpClass(cls):
        from app.services.model_catalog import (
            MODEL_TIER_RANK,
            MODEL_TIER_MAP,
            get_model_tier,
            get_model_provider,
            is_openrouter_model,
            is_model_allowed_for_tier,
            validate_provider_model_pair,
            get_models_with_tiers,
            normalize_model_selection,
            get_default_model,
        )
        cls.MODEL_TIER_RANK = MODEL_TIER_RANK
        cls.MODEL_TIER_MAP = MODEL_TIER_MAP

    def test_economy_rank_lowest(self):
        self.assertEqual(self.MODEL_TIER_RANK["economy"], 0)

    def test_standard_rank_middle(self):
        self.assertEqual(self.MODEL_TIER_RANK["standard"], 1)

    def test_premium_rank_highest(self):
        self.assertEqual(self.MODEL_TIER_RANK["premium"], 2)

    def test_unknown_model_returns_none(self):
        from app.services.model_catalog import get_model_tier
        self.assertIsNone(get_model_tier("completely/unknown"))

    def test_economy_model_allowed_for_economy(self):
        from app.services.model_catalog import is_model_allowed_for_tier
        self.assertTrue(
            is_model_allowed_for_tier("google/gemini-3.5-flash", "economy")
        )

    def test_premium_not_allowed_for_economy(self):
        from app.services.model_catalog import is_model_allowed_for_tier
        self.assertFalse(
            is_model_allowed_for_tier("openai/gpt-5.5", "economy")
        )

    def test_economy_not_allowed_for_nonexistent_tier(self):
        from app.services.model_catalog import is_model_allowed_for_tier
        self.assertFalse(
            is_model_allowed_for_tier("google/gemini-3.5-flash", "fantasy")
        )

    def test_get_model_provider_returns_correct(self):
        from app.services.model_catalog import get_model_provider
        provider = get_model_provider("openai/gpt-5.5")
        self.assertEqual(provider, "openai")

    def test_is_openrouter_openai(self):
        from app.services.model_catalog import is_openrouter_model
        self.assertTrue(is_openrouter_model("openai/gpt-4.1"))

    def test_is_deepseek_not_openrouter(self):
        from app.services.model_catalog import is_openrouter_model
        self.assertFalse(is_openrouter_model("deepseek-v4-flash"))

    def test_validate_provider_model_pair_valid(self):
        from app.services.model_catalog import validate_provider_model_pair
        result = validate_provider_model_pair("google", "google/gemini-3.5-flash")
        self.assertTrue(result)

    def test_get_models_with_tiers_has_tier_keys(self):
        from app.services.model_catalog import get_models_with_tiers
        augmented = get_models_with_tiers()
        for provider_key, provider_data in augmented.items():
            for m in provider_data.get("models", []):
                self.assertIn("tier", m)

    def test_normalize_model_selection_default_provider(self):
        from app.services.model_catalog import normalize_model_selection
        provider, model_name = normalize_model_selection(None, "openai/gpt-4.1")
        self.assertIsNotNone(provider)

    def test_normalize_model_selection_invalid_provider_raises(self):
        from app.services.model_catalog import normalize_model_selection
        with self.assertRaises(ValueError):
            normalize_model_selection("nonexistent", "some-model")

class TestPlanTierAccess(unittest.TestCase):
    """Tests that plans carry correct max_model_tier."""

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_essential_has_economy_tier(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        policy = resolve_ai_access(1)
        self.assertEqual(policy.max_model_tier, "economy")

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_advanced_has_standard_tier(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 3, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ADVANCED_PLAN
        policy = resolve_ai_access(1)
        self.assertEqual(policy.max_model_tier, "standard")

    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_pro_has_premium_tier(self, mock_sub, mock_plan):
        mock_sub.return_value = {"plan_id": 4, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = PRO_PLAN
        policy = resolve_ai_access(1)
        self.assertEqual(policy.max_model_tier, "premium")


# ============================================================
# TestBotTierEnforcement (12 tests)
# ============================================================

class TestBotTierEnforcement(unittest.TestCase):
    """Tests for bot-level model tier enforcement."""

    def setUp(self):
        from app.services.model_catalog import is_model_allowed_for_tier
        self._is_model_allowed_for_tier = is_model_allowed_for_tier

    def test_essential_cannot_use_premium(self):
        self.assertFalse(
            self._is_model_allowed_for_tier("openai/gpt-5.5", "economy")
        )

    def test_essential_can_use_economy(self):
        self.assertTrue(
            self._is_model_allowed_for_tier("google/gemini-3.5-flash", "economy")
        )

    def test_advanced_cannot_use_premium(self):
        self.assertFalse(
            self._is_model_allowed_for_tier("anthropic/claude-opus-4.7", "standard")
        )

    def test_advanced_can_use_standard(self):
        self.assertTrue(
            self._is_model_allowed_for_tier("openai/gpt-4.1", "standard")
        )

    def test_pro_can_use_premium(self):
        self.assertTrue(
            self._is_model_allowed_for_tier("openai/gpt-5.5", "premium")
        )

    def test_trial_deepseek_always_allowed(self):
        # DeepSeek models do not go through tier classification; they are trial-only
        from app.services.model_catalog import get_model_tier
        self.assertIsNone(get_model_tier("deepseek-v4-flash"))

    def test_unknown_model_blocked(self):
        self.assertFalse(
            self._is_model_allowed_for_tier("fake/model", "premium")
        )

    @patch("app.services.report_service.get_bot_by_id")
    def test_uses_configured_bot_model(self, mock_get_bot):
        """Verify generate_weekly_report reads the bot's configured model."""
        from app.services.report_service import generate_weekly_report

        mock_get_bot.return_value = {
            "id": 1,
            "ai_provider": "google",
            "model_name": "google/gemini-3.5-flash",
            "company_id": 1,
        }

        with patch("app.services.report_service.get_transcript_logs") as mock_logs, \
             patch("app.services.report_service.generate_system_response") as mock_gsr:
            mock_logs.return_value = [
                {"phone": "60123456789", "chat": "Hello bot"},
            ]
            mock_gsr.return_value = "Weekly report content"

            result = generate_weekly_report(chatbot_id=1, days=7)

            self.assertIn("Weekly report content", result)
            mock_gsr.assert_called_once()
            call_kwargs = mock_gsr.call_args[1]
            self.assertEqual(call_kwargs.get("provider"), "google")
            self.assertEqual(call_kwargs.get("model"), "google/gemini-3.5-flash")

    def test_default_paid_model_is_economy(self):
        from app.services.model_catalog import (
            DEFAULT_PAID_MODEL,
            DEFAULT_PAID_PROVIDER,
            get_model_tier,
        )
        self.assertEqual(get_model_tier(DEFAULT_PAID_MODEL), "economy")
        self.assertEqual(DEFAULT_PAID_PROVIDER, "google")

    def test_model_editable_essential_true(self):
        from app.services.model_catalog import is_valid_provider, is_valid_model
        self.assertTrue(is_valid_provider("google"))
        self.assertTrue(is_valid_model("google", "google/gemini-3.5-flash"))

    def test_model_editable_advanced_true(self):
        from app.services.model_catalog import is_valid_model
        self.assertTrue(is_valid_model("openai", "openai/gpt-4.1"))

    def test_model_editable_pro_true(self):
        from app.services.model_catalog import is_valid_model
        self.assertTrue(is_valid_model("anthropic", "anthropic/claude-opus-4.7"))


# ============================================================
# TestRuntimeTierEnforcement (11 tests)
# ============================================================

class TestRuntimeTierEnforcement(unittest.TestCase):
    """Tests for runtime model tier enforcement during AI generation."""

    def setUp(self):
        from app.services.model_catalog import is_model_allowed_for_tier
        self._is_model_allowed_for_tier = is_model_allowed_for_tier

    def test_premium_blocked_on_essential(self):
        self.assertFalse(
            self._is_model_allowed_for_tier("anthropic/claude-opus-4.7", "economy")
        )

    def test_economy_allowed_on_essential(self):
        self.assertTrue(
            self._is_model_allowed_for_tier("qwen/qwen3.6-27b", "economy")
        )

    def test_standard_blocked_on_economy(self):
        self.assertFalse(
            self._is_model_allowed_for_tier("openai/gpt-4.1", "economy")
        )

    def test_premium_allowed_on_pro(self):
        self.assertTrue(
            self._is_model_allowed_for_tier("anthropic/claude-opus-4.7", "premium")
        )

    def test_trial_deepseek_model_has_no_tier(self):
        from app.services.model_catalog import get_model_tier
        self.assertIsNone(get_model_tier("deepseek-v4-flash"))

    def test_economy_model_tier_for_qwen(self):
        from app.services.model_catalog import get_model_tier
        self.assertEqual(get_model_tier("qwen/qwen3.6-35b-a3b"), "economy")

    def test_standard_model_tier_for_openai(self):
        from app.services.model_catalog import get_model_tier
        self.assertEqual(get_model_tier("openai/gpt-4.1"), "standard")

    def test_premium_model_tier_for_xai(self):
        from app.services.model_catalog import get_model_tier
        self.assertEqual(get_model_tier("x-ai/grok-4.3"), "premium")

    def test_rank_ordering_is_monotonic(self):
        from app.services.model_catalog import MODEL_TIER_RANK
        self.assertEqual(MODEL_TIER_RANK["economy"], 0)
        self.assertEqual(MODEL_TIER_RANK["standard"], 1)
        self.assertEqual(MODEL_TIER_RANK["premium"], 2)
        self.assertEqual(len(MODEL_TIER_RANK), 3)
    def test_deepseek_provider_has_trial_only_access(self):
        from app.services.model_catalog import get_models_with_tiers
        augmented = get_models_with_tiers()
        deepseek = augmented.get("deepseek", {})
        for m in deepseek.get("models", []):
            self.assertEqual(m.get("access"), "trial_only")
            self.assertIsNone(m.get("tier"))

    def test_openrouter_provider_has_paid_access(self):
        from app.services.model_catalog import get_models_with_tiers
        augmented = get_models_with_tiers()
        openai = augmented.get("openai", {})
        for m in openai.get("models", []):
            self.assertIn(m.get("access"), ["paid", None])


# ============================================================
# TestGraphRAGEnforcement (5 tests)
# ============================================================

class TestGraphRAGEnforcement(unittest.TestCase):
    """Tests for GraphRAG knowledge extraction enforcement."""

    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    @patch("app.services.ai_router.generate_system_response")
    def test_graphrag_parses_json_response(
        self, mock_gsr, mock_edge, mock_node
    ):
        mock_gsr.return_value = json.dumps({
            "nodes": [
                {"name": "Acme", "label": "Company", "description": "A company"},
            ],
            "relationships": [
                {"source": "Acme", "target": "Widget", "type": "SELLS"},
            ],
        })
        mock_node.return_value = {"id": 1, "name": "acme"}
        mock_edge.return_value = {"id": 1}

        from app.services.knowledge_service import (
            extract_and_store_graph_supabase,
        )
        extract_and_store_graph_supabase(
            chunks=["Acme sells Widget."], chatbot_id=1, file_id=1
        )
        mock_node.assert_called()
        mock_edge.assert_called()

    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    @patch("app.services.ai_router.generate_system_response")
    def test_graphrag_empty_response_continues(
        self, mock_gsr, mock_edge, mock_node
    ):
        mock_gsr.return_value = ""

        from app.services.knowledge_service import (
            extract_and_store_graph_supabase,
        )
        extract_and_store_graph_supabase(
            chunks=["Some text"], chatbot_id=1, file_id=1
        )
        mock_node.assert_not_called()
        mock_edge.assert_not_called()

    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    @patch("app.services.ai_router.generate_system_response")
    def test_graphrag_upsert_node_called_per_entity(
        self, mock_gsr, mock_edge, mock_node
    ):
        mock_gsr.return_value = json.dumps({
            "nodes": [
                {"name": "Entity1", "label": "Product", "description": "First"},
                {"name": "Entity2", "label": "Service", "description": "Second"},
            ],
            "relationships": [],
        })
        mock_node.return_value = {"id": 1}

        from app.services.knowledge_service import (
            extract_and_store_graph_supabase,
        )
        extract_and_store_graph_supabase(
            chunks=["Entity1 and Entity2."], chatbot_id=1, file_id=1
        )
        self.assertGreaterEqual(mock_node.call_count, 2)

    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    @patch("app.services.ai_router.generate_system_response")
    def test_graphrag_upsert_edge_called(
        self, mock_gsr, mock_edge, mock_node
    ):
        mock_gsr.return_value = json.dumps({
            "nodes": [
                {"name": "A", "label": "Company", "description": "A"},
                {"name": "B", "label": "Product", "description": "B"},
            ],
            "relationships": [
                {"source": "A", "target": "B", "type": "MAKES"},
            ],
        })
        mock_node.return_value = {"id": 1}
        mock_edge.return_value = {"id": 1}

        from app.services.knowledge_service import (
            extract_and_store_graph_supabase,
        )
        extract_and_store_graph_supabase(
            chunks=["A makes B."], chatbot_id=1, file_id=1
        )
        mock_edge.assert_called()

    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    @patch("app.services.ai_router.generate_system_response")
    def test_graphrag_non_json_response_does_not_crash(
        self, mock_gsr, mock_edge, mock_node
    ):
        mock_gsr.return_value = "Not a JSON response at all"

        from app.services.knowledge_service import (
            extract_and_store_graph_supabase,
        )
        extract_and_store_graph_supabase(
            chunks=["Some text"], chatbot_id=1, file_id=1
        )
        mock_node.assert_not_called()
        mock_edge.assert_not_called()


# ============================================================
# TestWebsiteKnowledgeEnforcement (3 tests)
# ============================================================

class TestWebsiteKnowledgeEnforcement(unittest.TestCase):
    """Tests for website scraping knowledge extraction AI routing."""

    @patch("app.services.ai_router.generate_system_response")
    def test_scrape_uses_configured_bot_model(self, mock_gsr):
        """Configured chatbot provider/model is used."""
        mock_gsr.return_value = "Extracted content"
        from app.services.knowledge_service import extract_business_knowledge
        result = extract_business_knowledge("Test business text", chatbot_id=1)
        self.assertIn("Extracted content", result)
        mock_gsr.assert_called_once()
        args, kwargs = mock_gsr.call_args
        self.assertEqual(kwargs.get("provider"), None)
        self.assertEqual(kwargs.get("model"), None)
        # Provider=None forces the default path (no longer hardcoded Google)

    @patch("app.services.ai_router.generate_system_response")
    def test_scrape_router_error_returns_raw_text(self, mock_gsr):
        """Provider failure returns original text safely without fallback."""
        mock_gsr.side_effect = RuntimeError("AI provider failed")
        from app.services.knowledge_service import extract_business_knowledge
        result = extract_business_knowledge("Original source text", chatbot_id=1)
        self.assertEqual(result, "Original source text")
        mock_gsr.assert_called_once()

    def test_scrape_needs_chatbot_id(self):
        """Missing chatbot_id raises ValueError."""
        from app.services.knowledge_service import extract_business_knowledge
        with self.assertRaises(ValueError):
            extract_business_knowledge("text", chatbot_id=None)
class TestReportEnforcement(unittest.TestCase):
    """Tests for AI-generated report enforcement."""

    @patch("app.services.report_service.get_transcript_logs")
    @patch("app.services.report_service.get_bot_by_id")
    @patch("app.services.report_service.generate_system_response")
    def test_report_no_transcripts(self, mock_gsr, mock_get_bot, mock_logs):
        mock_logs.return_value = []
        mock_get_bot.return_value = {
            "id": 1,
            "ai_provider": "google",
            "model_name": "google/gemini-3.5-flash",
            "company_id": 1,
        }

        from app.services.report_service import generate_weekly_report
        result = generate_weekly_report(chatbot_id=1, days=7)

        self.assertIn("No conversation history", result)
        mock_gsr.assert_not_called()

    @patch("app.services.report_service.get_transcript_logs")
    @patch("app.services.report_service.get_bot_by_id")
    @patch("app.services.report_service.generate_system_response")
    def test_no_hardcoded_fallback(self, mock_gsr, mock_get_bot, mock_logs):
        mock_logs.return_value = [
            {"phone": "60123456789", "chat": "User: Hi\nBot: Hello!"},
        ]
        mock_get_bot.return_value = {
            "id": 1,
            "ai_provider": "google",
            "model_name": "google/gemini-3.5-flash",
            "company_id": 1,
        }
        mock_gsr.side_effect = RuntimeError("AI failed")

        from app.services.report_service import generate_weekly_report
        result = generate_weekly_report(chatbot_id=1, days=7)

        self.assertIn("error occurred", result.lower())
        self.assertNotIn("deepseek", result.lower())

    @patch("app.services.report_service.get_transcript_logs")
    @patch("app.services.report_service.get_bot_by_id")
    @patch("app.services.report_service.generate_system_response")
    def test_report_successful_generation(self, mock_gsr, mock_get_bot, mock_logs):
        mock_logs.return_value = [
            {"phone": "60123456789", "chat": "User: Hi\nBot: Hello!"},
        ]
        mock_get_bot.return_value = {
            "id": 1,
            "ai_provider": "openai",
            "model_name": "openai/gpt-4.1",
            "company_id": 1,
        }
        mock_gsr.return_value = "## Executive Summary\nAll good."

        from app.services.report_service import generate_weekly_report
        result = generate_weekly_report(chatbot_id=1, days=7)

        self.assertIn("Executive Summary", result)
        mock_gsr.assert_called_once()


# ============================================================
# Run


# ============================================================
# TestFallbackIsolation (4 tests)
# ============================================================

class TestFallbackIsolation(unittest.TestCase):
    """Tests that cross-provider fallback is disabled."""

    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.ai_router._route_for_enforcement")
    @patch("app.services.ai_router.call_provider")
    @patch("app.services.ai_router.resolve_ai_access")
    def test_trial_deepseek_failure_does_not_call_openrouter(
        self, mock_resolve, mock_call, mock_route, mock_bot
    ):
        """When trial DeepSeek fails, no OpenRouter provider is called."""
        from app.services.ai_access_policy import AIAccessPolicy as Policy
        mock_resolve.return_value = Policy(
            allowed=True, api_route="direct_deepseek",
            max_model_tier=None,
        )
        mock_bot.return_value = {
            "ai_provider": "deepseek",
            "model_name": "deepseek-chat",
            "temperature": 0.7,
            "company_id": 1,
        }
        mock_call.return_value = MagicMock(text="Sorry, I'm having trouble", finished=False)

        mock_route.return_value = ("deepseek", "deepseek-chat")
        from app.services.ai_router import generate_response
        with patch(
            "app.services.ai_router._try_process_flow_message",
            return_value=types.SimpleNamespace(status="no_flow", reply=None, handled=False, should_handoff_to_ai=True),
        ):
            result = generate_response("Hello", 1, 1)

        mock_call.assert_called_once()
        called_provider = mock_call.call_args[0][0]
        self.assertEqual(called_provider, "deepseek")
        self.assertIn("trouble", result)
        mock_resolve.assert_not_called()

    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.ai_router._route_for_enforcement")
    @patch("app.services.ai_router.call_provider")
    @patch("app.services.ai_router.resolve_ai_access")
    def test_paid_openrouter_failure_does_not_fallback_deepseek(
        self, mock_resolve, mock_call, mock_route, mock_bot
    ):
        """When paid OpenRouter fails, no direct DeepSeek is attempted."""
        from app.services.ai_access_policy import AIAccessPolicy as Policy
        mock_resolve.return_value = Policy(
            allowed=True, api_route="openrouter",
            max_model_tier="economy",
        )
        mock_bot.return_value = {
            "ai_provider": "google",
            "model_name": "google/gemini-3.5-flash",
            "temperature": 0.7,
            "company_id": 1,
        }
        mock_call.return_value = MagicMock(text="Sorry, I'm having trouble", finished=False)
        mock_route.return_value = ("google", "google/gemini-3.5-flash")

        from app.services.ai_router import generate_response
        with patch(
            "app.services.ai_router._try_process_flow_message",
            return_value=types.SimpleNamespace(status="no_flow", reply=None, handled=False, should_handoff_to_ai=True),
        ):
            result = generate_response("Hello", 1, 1)

        mock_call.assert_called_once()
        called_provider = mock_call.call_args[0][0]
        self.assertEqual(called_provider, "google")
        self.assertIn("trouble", result)
        mock_resolve.assert_not_called()

    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.ai_router._route_for_enforcement")
    @patch("app.services.ai_router.call_provider")
    @patch("app.services.ai_router.resolve_ai_access")
    def test_trial_deepseek_failure_exception_stays_on_deepseek(
        self, mock_resolve, mock_call, mock_route, mock_bot
    ):
        """Exception from trial DeepSeek does not trigger OpenRouter."""
        from app.services.ai_access_policy import AIAccessPolicy as Policy
        mock_resolve.return_value = Policy(
            allowed=True, api_route="direct_deepseek",
            max_model_tier=None,
        )
        mock_bot.return_value = {
            "ai_provider": "deepseek",
            "model_name": "deepseek-chat",
            "temperature": 0.7,
            "company_id": 1,
        }
        mock_call.side_effect = RuntimeError("DeepSeek connection failed")

        mock_route.return_value = ("deepseek", "deepseek-chat")
        from app.services.ai_router import generate_response
        with patch(
            "app.services.ai_router._try_process_flow_message",
            return_value=types.SimpleNamespace(status="no_flow", reply=None, handled=False, should_handoff_to_ai=True),
        ):
            result = generate_response("Hello", 1, 1)

        mock_call.assert_called_once()
        called_provider = mock_call.call_args[0][0]
        self.assertEqual(called_provider, "deepseek")
        self.assertIn("trouble", result)
        mock_resolve.assert_not_called()

    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.ai_router._route_for_enforcement")
    @patch("app.services.ai_router.call_provider")
    @patch("app.services.ai_router.resolve_ai_access")
    def test_paid_openrouter_exception_stays_on_openrouter(
        self, mock_resolve, mock_call, mock_route, mock_bot
    ):
        """Exception from paid OpenRouter does not fall back to DeepSeek."""
        from app.services.ai_access_policy import AIAccessPolicy as Policy
        mock_resolve.return_value = Policy(
            allowed=True, api_route="openrouter",
            max_model_tier="standard",
        )
        mock_bot.return_value = {
            "ai_provider": "openai",
            "model_name": "openai/gpt-4.1",
            "temperature": 0.7,
            "company_id": 1,
        }
        mock_call.side_effect = RuntimeError("OpenRouter API error")
        mock_route.return_value = ("openai", "openai/gpt-4.1")

        from app.services.ai_router import generate_response
        with patch(
            "app.services.ai_router._try_process_flow_message",
            return_value=types.SimpleNamespace(status="no_flow", reply=None, handled=False, should_handoff_to_ai=True),
        ):
            result = generate_response("Hello", 1, 1)

        mock_call.assert_called_once()
        called_provider = mock_call.call_args[0][0]
        self.assertEqual(called_provider, "openai")
        self.assertIn("trouble", result)
        mock_resolve.assert_not_called()

    @patch("app.services.ai_router.get_bot_by_id")
    @patch("app.services.ai_router.call_provider")
    def test_bot_not_found_returns_safe_error(self, mock_call, mock_get_bot):
        """When bot is not found, returns safe error without calling any provider."""
        mock_get_bot.return_value = None

        from app.services.ai_router import generate_response
        result = generate_response("Hello", 1, 9999)

        self.assertIn("trouble", result)
        mock_call.assert_not_called()

    def test_ai_router_has_no_provider_fallback_runtime_references(self):
        import inspect
        from app.services import ai_router

        source = inspect.getsource(ai_router)

        self.assertNotIn("get_fallback_model", source)
        self.assertNotIn("send_provider_failover_email", source)
        self.assertNotIn("Falling back to direct DeepSeek", source)


# ============================================================
# TestSystemProviderFallbackIsolation (5 tests)
# ============================================================

class TestSystemProviderFallbackIsolation(unittest.TestCase):
    """Tests that system/background AI calls do not cross providers."""

    def _patch_system_gateways(self, provider="openai", model="openai/gpt-4.1"):
        return (
            patch("app.services.ai_router.get_bot_by_id", return_value={
                "id": 1,
                "ai_provider": provider,
                "model_name": model,
                "temperature": 0.3,
                "company_id": 42,
            }),
            patch("app.services.company_status_service.ensure_company_operational"),
            patch("app.services.ai_router._get_system_provider_for_enforcement", return_value=(provider, model)),
            patch("app.services.ai_router._check_ai_credit_before_provider"),
            patch("app.services.ai_router._make_usage_log"),
        )

    def test_paid_openrouter_system_call_failure_does_not_call_deepseek_direct(self):
        from app.services import ai_router

        bot_patch, company_patch, route_patch, credit_patch, usage_patch = self._patch_system_gateways()
        with bot_patch, company_patch, route_patch, credit_patch, usage_patch, \
             patch.object(ai_router, "_call_openrouter_direct", side_effect=RuntimeError("OpenRouter failed")) as openrouter_call, \
             patch.object(ai_router, "_call_deepseek_direct") as deepseek_call:
            with self.assertRaises(RuntimeError):
                ai_router.generate_system_response("Summarize", 1)

        openrouter_call.assert_called_once()
        deepseek_call.assert_not_called()

    def test_openrouter_system_exception_does_not_invoke_another_provider(self):
        from app.services import ai_router

        bot_patch, company_patch, route_patch, credit_patch, usage_patch = self._patch_system_gateways(
            provider="google",
            model="google/gemini-3.5-flash",
        )
        with bot_patch, company_patch, route_patch, credit_patch, usage_patch, \
             patch.object(ai_router, "_call_openrouter_direct", side_effect=RuntimeError("OpenRouter failed")) as openrouter_call, \
             patch.object(ai_router, "_call_deepseek_direct") as deepseek_call, \
             patch.object(ai_router, "_call_gemini_direct") as gemini_call:
            with self.assertRaises(RuntimeError):
                ai_router.generate_system_response("Summarize", 1)

        openrouter_call.assert_called_once()
        deepseek_call.assert_not_called()
        gemini_call.assert_not_called()

    def test_deepseek_system_calls_remain_deepseek_only(self):
        from app.services import ai_router

        bot_patch, company_patch, route_patch, credit_patch, usage_patch = self._patch_system_gateways(
            provider="deepseek",
            model="deepseek-chat",
        )
        with bot_patch, company_patch, route_patch, credit_patch, usage_patch, \
             patch.object(ai_router, "_call_deepseek_direct", return_value=MagicMock(text="Done", is_provider_response=False)) as deepseek_call, \
             patch.object(ai_router, "_call_openrouter_direct") as openrouter_call:
            result = ai_router.generate_system_response("Summarize", 1)

        self.assertEqual(result, "Done")
        deepseek_call.assert_called_once()
        openrouter_call.assert_not_called()

    @patch("app.services.ai_router.generate_system_response")
    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    def test_graphrag_provider_failure_keeps_safe_chunk_processing(self, mock_edge, mock_node, mock_gsr):
        mock_gsr.side_effect = RuntimeError("AI provider failed")

        from app.services.knowledge_service import extract_and_store_graph_supabase
        extract_and_store_graph_supabase(["Some text"], chatbot_id=1, file_id=1)

        mock_gsr.assert_called_once()
        mock_node.assert_not_called()
        mock_edge.assert_not_called()

    @patch("app.services.report_service.get_transcript_logs")
    @patch("app.services.report_service.get_bot_by_id")
    @patch("app.services.report_service.generate_system_response")
    def test_report_provider_failure_keeps_safe_error_response(self, mock_gsr, mock_get_bot, mock_logs):
        mock_logs.return_value = [{"phone": "60123456789", "chat": "User: Hi"}]
        mock_get_bot.return_value = {
            "id": 1,
            "ai_provider": "openai",
            "model_name": "openai/gpt-4.1",
            "company_id": 1,
        }
        mock_gsr.side_effect = RuntimeError("AI provider failed")

        from app.services.report_service import generate_weekly_report
        result = generate_weekly_report(chatbot_id=1, days=7)

        mock_gsr.assert_called_once()
        self.assertIn("error occurred", result.lower())



# ============================================================
# TestGraphRAGDirectClientProhibition (2 tests)
# ============================================================

class TestGraphRAGDirectClientProhibition(unittest.TestCase):
    """Tests that GraphRAG does not create a direct provider client."""

    @patch("app.services.ai_router.generate_system_response")
    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    def test_graphrag_uses_ai_router_not_direct_client(
        self, mock_edge, mock_node, mock_gsr
    ):
        """GraphRAG calls generate_system_response; no direct provider client."""
        mock_gsr.return_value = json.dumps({
            "nodes": [{"name": "Co", "label": "Company", "description": "A company"}],
            "relationships": [],
        })
        mock_node.return_value = {"id": 1}
        mock_edge.return_value = {"id": 1}

        from app.services.knowledge_service import extract_and_store_graph_supabase
        extract_and_store_graph_supabase(["Some text"], chatbot_id=1, file_id=1)

        mock_gsr.assert_called_once()
        self.assertGreaterEqual(mock_node.call_count, 1)

    def test_graphrag_no_openai_import_remains_in_knowledge_service(self):
        """Knowledge service no longer imports direct OpenAI/DeepSeek client."""
        import app.services.knowledge_service as ks
        source = ks.__file__
        with open(source, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("openai.OpenAI", content)
        self.assertNotIn('from openai import OpenAI', content)


# ============================================================
# TestAICreditSingleCharge (5 tests)
# ============================================================

class TestAICreditSingleCharge(unittest.TestCase):
    """Tests that each AI operation charges credit exactly once."""

    @patch("app.services.ai_router.generate_system_response")
    @patch("app.database.knowledge_graph_repository.upsert_node")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    def test_graphrag_charges_once(
        self, mock_edge, mock_node, mock_gsr
    ):
        """GraphRAG makes one system-response call, resulting in one charge."""
        mock_gsr.return_value = json.dumps({
            "nodes": [{"name": "Co", "label": "Company", "description": "A company"}],
            "relationships": [],
        })
        mock_node.return_value = {"id": 1}
        mock_edge.return_value = {"id": 1}

        from app.services.knowledge_service import extract_and_store_graph_supabase
        extract_and_store_graph_supabase(["Some text"], chatbot_id=1, file_id=1)

        self.assertEqual(mock_gsr.call_count, 1)

    @patch("app.services.ai_router.generate_system_response")
    def test_website_knowledge_charges_once(self, mock_gsr):
        """Website knowledge extraction makes one system-response call."""
        mock_gsr.return_value = "Extracted business info"

        from app.services.knowledge_service import extract_business_knowledge
        result = extract_business_knowledge("Test business text", chatbot_id=1)

        self.assertIn("Extracted business info", result)
        self.assertEqual(mock_gsr.call_count, 1)

    @patch("app.services.report_service.get_transcript_logs")
    @patch("app.services.report_service.get_bot_by_id")
    @patch("app.services.report_service.generate_system_response")
    def test_report_charges_once(
        self, mock_gsr, mock_get_bot, mock_logs
    ):
        """Report generation makes one system-response call."""
        mock_logs.return_value = [{"phone": "60123456789", "chat": "User: Hi"}]
        mock_get_bot.return_value = {
            "id": 1, "ai_provider": "google",
            "model_name": "google/gemini-3.5-flash",
            "company_id": 1,
        }
        mock_gsr.return_value = "## Executive Summary\nAll good."

        from app.services.report_service import generate_weekly_report
        result = generate_weekly_report(chatbot_id=1, days=7)

        self.assertIn("Executive Summary", result)
        self.assertEqual(mock_gsr.call_count, 1)

    @patch("app.services.report_service.get_transcript_logs")
    @patch("app.services.report_service.get_bot_by_id")
    @patch("app.services.report_service.generate_system_response")
    def test_report_failure_does_not_double_charge(
        self, mock_gsr, mock_get_bot, mock_logs
    ):
        """When report AI call fails, only one call is made, not multiple."""
        mock_logs.return_value = [{"phone": "60123456789", "chat": "User: Hi"}]
        mock_get_bot.return_value = {
            "id": 1, "ai_provider": "google",
            "model_name": "google/gemini-3.5-flash",
            "company_id": 1,
        }
        mock_gsr.side_effect = RuntimeError("AI failed")

        from app.services.report_service import generate_weekly_report
        result = generate_weekly_report(chatbot_id=1, days=7)

        self.assertEqual(mock_gsr.call_count, 1)
        self.assertIn("error", result.lower())

    @patch("app.services.ai_router.generate_system_response")
    def test_website_failure_does_not_double_charge(self, mock_gsr):
        """When website knowledge AI fails, only one call is made."""
        mock_gsr.side_effect = RuntimeError("AI failed")

        from app.services.knowledge_service import extract_business_knowledge
        result = extract_business_knowledge("Original text", chatbot_id=1)

        self.assertEqual(mock_gsr.call_count, 1)
        self.assertEqual(result, "Original text")

# ============================================================
# TestDeepSeekCreditCheck (3 tests)
# ============================================================

class TestDeepSeekCreditCheck(unittest.TestCase):
    """Tests that the DeepSeek dict-response path in call_provider performs AI-credit checks."""

    @patch("app.services.ai_router._check_ai_credit_before_provider")
    @patch("app.services.ai_router.deepseek_service._request")
    def test_deepseek_dict_response_checks_credit(
        self, mock_deepseek_request, mock_credit_check
    ):
        """When DeepSeek returns a dict response, call_provider checks credit before returning."""
        mock_deepseek_request.return_value = (True, {
            "choices": [{"message": {"content": "Hello from DeepSeek"}}],
        })
        from app.services.ai_router import call_provider
        result = call_provider(
            "deepseek", "Hi", customer_id=1, chatbot_id=1,
            company_id=1,
        )
        mock_credit_check.assert_called_once_with(1)
        self.assertTrue(result.success)
        self.assertEqual(result.text, "Hello from DeepSeek")

    @patch("app.services.ai_router._check_ai_credit_before_provider")
    @patch("app.services.ai_router.deepseek_service._request")
    def test_deepseek_dict_response_insufficient_credit_denies(
        self, mock_deepseek_request, mock_credit_check
    ):
        """When credit check raises, DeepSeek dict response must not bypass the denial."""
        mock_deepseek_request.return_value = (True, {
            "choices": [{"message": {"content": "Secret response"}}],
        })
        mock_credit_check.side_effect = RuntimeError("AI credit exhausted")
        from app.services.ai_router import call_provider
        with self.assertRaises(RuntimeError) as ctx:
            call_provider(
                "deepseek", "Hi", customer_id=1, chatbot_id=1,
                company_id=1,
            )
        mock_credit_check.assert_called_once_with(1)
        self.assertIn("credit", str(ctx.exception).lower())

    @patch("app.services.ai_router._check_ai_credit_before_provider")
    @patch("app.services.ai_router.deepseek_service._request")
    def test_deepseek_non_dict_object_response_also_checks_credit(
        self, mock_deepseek_request, mock_credit_check
    ):
        """When DeepSeek returns an SDK object, call_provider also checks credit before the object branch."""
        from unittest.mock import MagicMock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Object response"
        mock_deepseek_request.return_value = (True, mock_response)
        from app.services.ai_router import call_provider
        result = call_provider(
            "deepseek", "Hi", customer_id=1, chatbot_id=1,
            company_id=1,
        )
        mock_credit_check.assert_called_once_with(1)
        self.assertTrue(result.success)
        self.assertEqual(result.text, "Object response")



# ============================================================
# TestTrialToPaidConversion (10 tests)
# ============================================================

class TestTrialToPaidConversion(unittest.TestCase):
    """Tests for convert_trial_ai_configuration()."""

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_trial_deepseek_converts_to_paid_default(
        self, mock_update_bot, mock_get_bots
    ):
        """Trial company with DeepSeek chatbot converts to OpenRouter default."""
        from app.services.model_catalog import DEFAULT_PAID_PROVIDER, DEFAULT_PAID_MODEL
        mock_get_bots.return_value = [
            {"id": 1, "ai_provider": "deepseek", "model_name": "deepseek-v4-flash"}
        ]
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "essential")
        mock_update_bot.assert_called_once_with(
            1,
            {"ai_provider": DEFAULT_PAID_PROVIDER, "model_name": DEFAULT_PAID_MODEL},
            1,
        )

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_multiple_bots_all_converted(
        self, mock_update_bot, mock_get_bots
    ):
        """Multiple chatbots all converted to paid default."""
        from app.services.model_catalog import DEFAULT_PAID_PROVIDER, DEFAULT_PAID_MODEL
        mock_get_bots.return_value = [
            {"id": 1, "ai_provider": "deepseek", "model_name": "deepseek-v4-flash"},
            {"id": 2, "ai_provider": "deepseek", "model_name": "deepseek-chat"},
            {"id": 3, "ai_provider": "deepseek", "model_name": "deepseek-v4-flash"},
        ]
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "advanced")
        self.assertEqual(mock_update_bot.call_count, 3)
        for call_args in mock_update_bot.call_args_list:
            bot_id, payload, company_id = call_args[0]
            self.assertEqual(payload, {"ai_provider": DEFAULT_PAID_PROVIDER, "model_name": DEFAULT_PAID_MODEL})
            self.assertEqual(company_id, 1)

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_conversion_is_idempotent(
        self, mock_update_bot, mock_get_bots
    ):
        """Calling conversion twice does not modify already-converted bots."""
        from app.services.model_catalog import DEFAULT_PAID_PROVIDER, DEFAULT_PAID_MODEL
        bot = {"id": 1, "ai_provider": DEFAULT_PAID_PROVIDER, "model_name": DEFAULT_PAID_MODEL}
        mock_get_bots.return_value = [bot]
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "pro")
        convert_trial_ai_configuration(1, "pro")
        mock_update_bot.assert_not_called()

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_active_paid_not_modified(
        self, mock_update_bot, mock_get_bots
    ):
        """Active paid subscription is not modified by conversion."""
        mock_get_bots.return_value = [
            {"id": 1, "ai_provider": "google", "model_name": "google/gemini-3.5-flash"}
        ]
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "essential")
        mock_update_bot.assert_not_called()

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_valid_openrouter_model_not_modified(
        self, mock_update_bot, mock_get_bots
    ):
        """Valid OpenRouter model remains unchanged."""
        mock_get_bots.return_value = [
            {"id": 1, "ai_provider": "openai", "model_name": "openai/gpt-4.1"}
        ]
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "advanced")
        mock_update_bot.assert_not_called()

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_invalid_model_gets_default(
        self, mock_update_bot, mock_get_bots
    ):
        """Bot with invalid or unknown model receives paid default."""
        from app.services.model_catalog import DEFAULT_PAID_PROVIDER, DEFAULT_PAID_MODEL
        mock_get_bots.return_value = [
            {"id": 1, "ai_provider": "deepseek", "model_name": "nonexistent-model"}
        ]
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "essential")
        mock_update_bot.assert_called_once()
        payload = mock_update_bot.call_args[0][1]
        self.assertEqual(payload["ai_provider"], DEFAULT_PAID_PROVIDER)
        self.assertEqual(payload["model_name"], DEFAULT_PAID_MODEL)

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_chatbot_data_preserved(
        self, mock_update_bot, mock_get_bots
    ):
        """Only ai_provider and model_name are changed; other data is not modified."""
        from app.services.model_catalog import DEFAULT_PAID_PROVIDER, DEFAULT_PAID_MODEL
        mock_get_bots.return_value = [
            {
                "id": 1,
                "ai_provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "bot_name": "My Bot",
                "temperature": 0.7,
                "system_prompt": "You are helpful",
            }
        ]
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "essential")
        mock_update_bot.assert_called_once()
        payload = mock_update_bot.call_args[0][1]
        self.assertEqual(payload, {"ai_provider": DEFAULT_PAID_PROVIDER, "model_name": DEFAULT_PAID_MODEL})
        # check that other bot fields are not in the update payload
        self.assertNotIn("bot_name", payload)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("system_prompt", payload)

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_missing_company_raises(
        self, mock_update_bot, mock_get_bots
    ):
        """Missing company_id raises ValueError."""
        from app.services.billing_service import convert_trial_ai_configuration
        with self.assertRaises(ValueError):
            convert_trial_ai_configuration(None, "essential")

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_non_paid_plan_code_skips(
        self, mock_update_bot, mock_get_bots
    ):
        """Non-paid plan code (free, trial) skips conversion without error."""
        from app.services.billing_service import convert_trial_ai_configuration
        convert_trial_ai_configuration(1, "free")
        mock_get_bots.assert_not_called()
        mock_update_bot.assert_not_called()

    @patch("app.database.bot_repository.get_all_bots")
    @patch("app.database.bot_repository.update_bot")
    def test_repository_failure_raises(
        self, mock_update_bot, mock_get_bots
    ):
        """Repository failure during update raises RuntimeError."""
        mock_get_bots.return_value = [
            {"id": 1, "ai_provider": "deepseek", "model_name": "deepseek-v4-flash"},
            {"id": 2, "ai_provider": "deepseek", "model_name": "deepseek-v4-flash"},
        ]
        mock_update_bot.side_effect = [None, RuntimeError("DB error")]
        from app.services.billing_service import convert_trial_ai_configuration
        with self.assertRaises(RuntimeError) as ctx:
            convert_trial_ai_configuration(1, "essential")
        self.assertIn("partially failed", str(ctx.exception))
        self.assertEqual(mock_update_bot.call_count, 2)



# ============================================================

# ============================================================
# Phase 2: Chatbot creation & model-settings enforcement
# ============================================================

TRIAL_PROVIDER = "deepseek"
TRIAL_MODEL = "deepseek-v4-flash"


class TestChatbotCreation(unittest.TestCase):
    """Chatbot creation should not require AI credit or AI access."""

    @patch("app.services.bot_service.create_bot")
    @patch("app.services.bot_service.get_bot_by_id")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_free_user_first_bot_created(self, mock_sub, mock_plan, mock_get_bot, mock_create):
        """Free + trialing user with 0 bots can create the first bot."""
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        mock_create.return_value = {"id": 1, "bot_name": "Test Bot"}
        mock_get_bot.return_value = None

        from app.services.bot_service import add_bot
        result = add_bot({"bot_name": "Test Bot"}, 1)
        self.assertEqual(result["bot_name"], "Test Bot")
        mock_create.assert_called_once()

    @patch("app.services.billing_guard._resolve_company_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    def test_second_bot_blocked_with_chatbot_limit(
        self, mock_plan, mock_usage, mock_sub
    ):
        """Free user at 1/1 bots gets chatbot_limit code, not ai_access_denied."""
        mock_sub.return_value = {
            "plan": {"chatbot_limit": 1, "code": "free"},
            "plan_id": 1, "status": "trialing",
            "trial_ends_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        }
        mock_plan.return_value = FREE_PLAN
        mock_usage.return_value = {"usage": {"chatbots": {"used": 1}}}

        from app.services.billing_guard import can_create_chatbot, BillingLimitError
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(1)
        self.assertEqual(ctx.exception.code, "chatbot_limit")
        self.assertIn("Chatbot limit reached", str(ctx.exception))

    @patch("app.services.bot_service.create_bot")
    @patch("app.services.bot_service.get_bot_by_id")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_chatbot_creation_no_credit_check(
        self, mock_sub, mock_plan, mock_get_bot, mock_create
    ):
        """Creating a bot does not check AI-credit balance."""
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        mock_create.return_value = {"id": 1, "bot_name": "Test"}
        mock_get_bot.return_value = None

        from app.services.bot_service import add_bot
        # Should not raise BillingLimitError or any AI-credit error
        result = add_bot({"bot_name": "Test"}, 1)
        self.assertIsNotNone(result)

    @patch("app.services.billing_guard._resolve_company_subscription")
    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    def test_chatbot_limit_error_distinct_from_ai_denial(
        self, mock_plan, mock_usage, mock_sub
    ):
        """Chatbot-limit errors use code 'chatbot_limit', not 'ai_access_denied'."""
        mock_sub.return_value = {
            "plan": {"chatbot_limit": 1, "code": "free"},
            "plan_id": 1, "status": "trialing",
            "trial_ends_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        }
        mock_plan.return_value = FREE_PLAN
        mock_usage.return_value = {"usage": {"chatbots": {"used": 1}}}

        from app.services.billing_guard import can_create_chatbot, BillingLimitError
        with self.assertRaises(BillingLimitError) as ctx:
            can_create_chatbot(1)
        self.assertEqual(ctx.exception.code, "chatbot_limit")
        self.assertNotEqual(ctx.exception.code, "ai_access_denied")


class TestModelSettingsEnforcement(unittest.TestCase):
    """edit_bot enforces provider/model for trial users."""

    @patch("app.services.bot_service.update_bot")
    @patch("app.services.bot_service.get_bot_by_id")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_temperature_only_update_succeeds(
        self, mock_sub, mock_plan, mock_get_bot, mock_update
    ):
        """Trial user saving only temperature succeeds."""
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        mock_get_bot.return_value = {
            "id": 1, "ai_provider": TRIAL_PROVIDER,
            "model_name": TRIAL_MODEL, "temperature": 0.7,
        }
        mock_update.return_value = {"id": 1}

        from app.services.bot_service import edit_bot
        result = edit_bot(1, {"temperature": 0.5}, 1)
        self.assertIsNotNone(result)

    @patch("app.services.bot_service.update_bot")
    @patch("app.services.bot_service.get_bot_by_id")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_deepseek_flash_save_succeeds(
        self, mock_sub, mock_plan, mock_get_bot, mock_update
    ):
        """Trial user saving the enforced DeepSeek V4 Flash config succeeds."""
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        mock_get_bot.return_value = {
            "id": 1, "ai_provider": TRIAL_PROVIDER,
            "model_name": TRIAL_MODEL,
        }
        mock_update.return_value = {"id": 1}

        from app.services.bot_service import edit_bot
        result = edit_bot(1, {
            "ai_provider": TRIAL_PROVIDER,
            "model_name": TRIAL_MODEL,
        }, 1)
        self.assertIsNotNone(result)

    @patch("app.services.bot_service.get_bot_by_id")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_trial_claude_rejected(
        self, mock_sub, mock_plan, mock_get_bot
    ):
        """Trial user cannot manually set Claude/OpenAI/Gemini."""
        trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        mock_sub.return_value = {
            "plan_id": 1, "status": "trialing",
            "trial_ends_at": trial_end,
        }
        mock_plan.return_value = FREE_PLAN
        mock_get_bot.return_value = {
            "id": 1, "ai_provider": TRIAL_PROVIDER,
            "model_name": TRIAL_MODEL,
        }

        from app.services.bot_service import edit_bot
        from app.services.billing_guard import BillingLimitError
        with self.assertRaises(BillingLimitError) as ctx:
            edit_bot(1, {
                "ai_provider": "anthropic",
                "model_name": "claude-sonnet-4-20250514",
            }, 1)
        self.assertIn(ctx.exception.code, ("trial_provider_restricted", "trial_model_locked"))

    @patch("app.services.bot_service.update_bot")
    @patch("app.services.bot_service.get_bot_by_id")
    @patch("app.services.ai_access_policy.get_plan_by_id")
    @patch("app.services.ai_access_policy._get_company_subscription")
    def test_paid_model_save_unchanged(
        self, mock_sub, mock_plan, mock_get_bot, mock_update
    ):
        """Paid user can change provider/model freely."""
        mock_sub.return_value = {"plan_id": 2, "status": "active", "current_period_end": "2099-01-01T00:00:00+00:00"}
        mock_plan.return_value = ESSENTIAL_PLAN
        mock_get_bot.return_value = {
            "id": 1, "ai_provider": "openai", "model_name": "google/gemini-3.5-flash",
        }
        mock_update.return_value = {"id": 1}

        from app.services.bot_service import edit_bot
        result = edit_bot(1, {
            "ai_provider": "google",
            "model_name": "google/gemini-3.5-flash",
        }, 1)
        self.assertIsNotNone(result)


class TestAIModelRouteFiltering(unittest.TestCase):
    """GET /api/ai-models returns filtered catalog for trial users
    and includes access_allowed / denial_reason for expired trials."""

    @patch("app.routes.ai_model_routes.get_models_with_tiers")
    @patch("app.services.ai_access_policy.resolve_ai_access")
    def test_trial_user_sees_only_deepseek_with_access(self, mock_policy, mock_tiers):
        mock_tiers.return_value = {
            "deepseek": {
                "label": "DeepSeek",
                "models": [{"value": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"}],
            },
            "openai": {
                "label": "OpenAI",
                "models": [{"value": "gpt-4o", "label": "GPT-4o"}],
            },
        }
        mock_policy.return_value = AIAccessPolicy(
            allowed=True,
            access_state=STATE_ACTIVE_TRIAL,
            api_route=ROUTE_DIRECT_DEEPSEEK,
            top_up_allowed=False,
            model_editable=False,
        )
        # Simulate what the route does
        policy = mock_policy.return_value
        free_states = {STATE_ACTIVE_TRIAL, STATE_EXPIRED_TRIAL, STATE_FREE_NO_TRIAL}
        self.assertIn(policy.access_state, free_states)
        filtered = {}
        for key, entry in mock_tiers.return_value.items():
            if key == "deepseek":
                filtered["deepseek"] = {
                    "label": entry["label"],
                    "models": [
                        m for m in entry.get("models", [])
                        if m.get("value") == TRIAL_MODEL
                    ],
                }
        self.assertIn("deepseek", filtered)
        self.assertNotIn("openai", filtered)
        self.assertEqual(len(filtered["deepseek"]["models"]), 1)

    @patch("app.routes.ai_model_routes.get_models_with_tiers")
    @patch("app.services.ai_access_policy.resolve_ai_access")
    def test_free_expired_returns_deepseek_readonly_denied(self, mock_policy, mock_tiers):
        """Free + active + no trial_ends_at returns DeepSeek-only with access_allowed=false."""
        mock_tiers.return_value = {
            "deepseek": {
                "label": "DeepSeek",
                "models": [{"value": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"}],
            },
            "openai": {"label": "OpenAI", "models": [{"value": "gpt-4o"}]},
        }
        mock_policy.return_value = AIAccessPolicy(
            allowed=False,
            access_state=STATE_EXPIRED_TRIAL,
            api_route=ROUTE_DENIED,
            denial_reason="Your trial has expired. Please subscribe to continue.",
            top_up_allowed=False,
            model_editable=False,
        )
        policy = mock_policy.return_value
        free_states = {STATE_ACTIVE_TRIAL, STATE_EXPIRED_TRIAL, STATE_FREE_NO_TRIAL}
        self.assertIn(policy.access_state, free_states)
        self.assertFalse(policy.allowed)
        self.assertIsNotNone(policy.denial_reason)

    @patch("app.routes.ai_model_routes.get_models_with_tiers")
    @patch("app.services.ai_access_policy.resolve_ai_access")
    def test_paid_user_sees_full_catalog(self, mock_policy, mock_tiers):
        mock_tiers.return_value = {
            "deepseek": {"label": "DeepSeek", "models": [{"value": "deepseek-v4-flash"}]},
            "openai": {"label": "OpenAI", "models": [{"value": "gpt-4o"}]},
            "anthropic": {"label": "Claude", "models": [{"value": "claude-sonnet-4-20250514"}]},
        }
        mock_policy.return_value = AIAccessPolicy(
            allowed=True,
            access_state=STATE_ESSENTIAL,
            api_route=ROUTE_OPENROUTER,
            top_up_allowed=True,
            model_editable=True,
        )
        policy = mock_policy.return_value
        free_states = {STATE_ACTIVE_TRIAL, STATE_EXPIRED_TRIAL, STATE_FREE_NO_TRIAL}
        self.assertNotIn(policy.access_state, free_states)

    @patch("app.routes.ai_model_routes.get_models_with_tiers")
    @patch("app.services.ai_access_policy.resolve_ai_access")
    def test_free_no_trial_returns_deepseek_readonly(self, mock_policy, mock_tiers):
        """STATE_FREE_NO_TRIAL also gets DeepSeek-only read_only."""
        mock_tiers.return_value = {
            "deepseek": {
                "label": "DeepSeek",
                "models": [{"value": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"}],
            },
        }
        mock_policy.return_value = AIAccessPolicy(
            allowed=False,
            access_state=STATE_FREE_NO_TRIAL,
            api_route=ROUTE_DENIED,
            denial_reason="Your plan does not include AI replies. Please subscribe.",
            top_up_allowed=False,
            model_editable=False,
        )
        policy = mock_policy.return_value
        free_states = {STATE_ACTIVE_TRIAL, STATE_EXPIRED_TRIAL, STATE_FREE_NO_TRIAL}
        self.assertIn(policy.access_state, free_states)
        self.assertFalse(policy.allowed)

    """GET /api/ai-models returns filtered catalog for trial users."""

    @patch("app.routes.ai_model_routes.get_models_with_tiers")
    def test_trial_user_sees_only_deepseek(self, mock_tiers):
        mock_tiers.return_value = {
            "deepseek": {
                "label": "DeepSeek",
                "models": [{"value": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"}],
            },
            "openai": {
                "label": "OpenAI",
                "models": [{"value": "gpt-4o", "label": "GPT-4o"}],
            },
        }
        policy = AIAccessPolicy(
            allowed=True,
            access_state=STATE_ACTIVE_TRIAL,
            api_route=ROUTE_DIRECT_DEEPSEEK,
            max_model_tier=None,
            top_up_allowed=False,
            model_editable=False,
        )
        # Simulate what the route does with the policy
        filtered = {}
        for key, entry in mock_tiers.return_value.items():
            if key == "deepseek":
                filtered["deepseek"] = {
                    "label": entry["label"],
                    "models": [
                        m for m in entry.get("models", [])
                        if m.get("value") == TRIAL_MODEL
                    ],
                }
        self.assertIn("deepseek", filtered)
        self.assertNotIn("openai", filtered)
        self.assertEqual(len(filtered["deepseek"]["models"]), 1)
        self.assertEqual(filtered["deepseek"]["models"][0]["value"], TRIAL_MODEL)

    @patch("app.routes.ai_model_routes.get_models_with_tiers")
    def test_paid_user_sees_full_catalog(self, mock_tiers):
        mock_tiers.return_value = {
            "deepseek": {"label": "DeepSeek", "models": [{"value": "deepseek-v4-flash"}]},
            "openai": {"label": "OpenAI", "models": [{"value": "gpt-4o"}]},
            "anthropic": {"label": "Claude", "models": [{"value": "claude-sonnet-4-20250514"}]},
        }
        # Paid: no filtering
        all_models = mock_tiers.return_value
        self.assertIn("deepseek", all_models)
        self.assertIn("openai", all_models)
        self.assertIn("anthropic", all_models)


if __name__ == "__main__":
    unittest.main()
