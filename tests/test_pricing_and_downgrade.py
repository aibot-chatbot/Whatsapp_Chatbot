"""test_pricing_and_downgrade.py

Unit tests for subscription pricing card actions, downgrade-check API,
and plan change/expiry policies.
All repository and service calls are mocked; no Supabase, payment gateway,
or network access.

Uses the same authentication-patch pattern as test_billing_routes.py.
Patches are applied where the production code LOOKS UP each dependency.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLASK_DEBUG", "1")

import sys
sys.path.insert(0, r"C:\Users\User\PycharmProjects\python-whatsapp-bot-main")

import json
import unittest
import types
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, PropertyMock

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

_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])

with patch("app.database.db.supabase", _sb):
    from app.routes.billing_routes import billing_bp
    from flask import Flask

MOCK_USER = {"id": 100, "company_id": 42, "full_name": "Test User", "email": "test@example.com", "phone": None, "role": "admin", "status": "active"}


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    app.register_blueprint(billing_bp)
    return app


# --- Shared plans data ---
ESSENTIAL_PLAN = {
    "id": 1, "code": "essential", "name": "Essential",
    "is_active": True, "chatbot_limit": 1, "team_member_limit": 1,
    "knowledge_file_limit": 5, "knowledge_storage_limit_bytes": 50000000,
    "channel_limit": 2,
}

ADVANCED_PLAN = {
    "id": 2, "code": "advanced", "name": "Advanced",
    "is_active": True, "chatbot_limit": 3, "team_member_limit": 3,
    "knowledge_file_limit": 25, "knowledge_storage_limit_bytes": 250000000,
    "channel_limit": 5,
}

PRO_PLAN = {
    "id": 3, "code": "pro", "name": "Pro",
    "is_active": True, "chatbot_limit": 10, "team_member_limit": 5,
    "knowledge_file_limit": 75, "knowledge_storage_limit_bytes": 1000000000,
    "channel_limit": 10,
}

SUB_ACTIVE_PRO = {
    "id": 10, "company_id": 42, "plan_id": 3, "status": "active",
    "plan": {"code": "pro", "name": "Pro"},
    "current_period_end": "2026-08-09T00:00:00Z",
}

_SENTINEL = object()


USAGE_WITHIN_LIMITS = {
    "period": {"start": "2026-07-01", "end": "2026-08-01"},
    "plan": {"code": "pro"},
    "usage": {
        "chatbots": {"used": 1, "limit": 10},
        "team_members": {"used": 1, "limit": 5, "pending_invitations": 0},
        "knowledge_files": {"used": 1, "limit": 75},
        "knowledge_storage_bytes": {"used": 1000, "limit": 1000000000},
        "channels": {"used": 1, "limit": 10},
    },
}


class TestDowngradeCheckAPI(unittest.TestCase):
    """Tests for GET /api/billing/subscription/downgrade-check/<code>."""

    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    # --- Authentication patches ---

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 100, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    # --- Service-level patches for the downgrade endpoint ---

    def _patch_get_subscription(self, return_value=_SENTINEL):
        if return_value is _SENTINEL:
            return_value = SUB_ACTIVE_PRO
        return patch(
            "app.routes.billing_routes.get_current_subscription",
            return_value=return_value,
        )

    def _patch_get_usage(self, return_value=_SENTINEL):
        if return_value is _SENTINEL:
            return_value = USAGE_WITHIN_LIMITS
        return patch(
            "app.routes.billing_routes.get_company_usage",
            return_value=return_value,
        )

    def _patch_get_plan_by_code(self, return_value=None):
        return patch(
            "app.routes.billing_routes._get_plan_by_code",
            return_value=return_value,
        )

    # --- Positive cases ---

    def test_pro_to_advanced_eligible(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_subscription(), self._patch_get_usage(), \
             self._patch_get_plan_by_code(return_value=ADVANCED_PLAN):
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/advanced",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.data)
            self.assertEqual(body["status"], "success")
            self.assertTrue(body["data"]["eligible"])
            self.assertEqual(body["data"]["target_plan"], "advanced")

    def test_pro_to_essential_blocked_by_chatbots(self):
        usage = dict(USAGE_WITHIN_LIMITS)
        usage["usage"] = dict(usage["usage"])
        usage["usage"]["chatbots"] = {"used": 3, "limit": 10}
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_subscription(), self._patch_get_usage(return_value=usage), \
             self._patch_get_plan_by_code(return_value=ESSENTIAL_PLAN):
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/essential",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.data)
            self.assertFalse(body["data"]["eligible"])
            blockers = body["data"]["blocking_items"]
            chatbot_blocker = [b for b in blockers if b["resource"] == "chatbots"]
            self.assertTrue(len(chatbot_blocker) > 0)
            self.assertEqual(chatbot_blocker[0]["excess"], 2)

    def test_pending_invitations_counted(self):
        usage = dict(USAGE_WITHIN_LIMITS)
        usage["usage"] = dict(usage["usage"])
        usage["usage"]["team_members"] = {"used": 1, "limit": 5, "pending_invitations": 2}
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_subscription(), self._patch_get_usage(return_value=usage), \
             self._patch_get_plan_by_code(return_value=ESSENTIAL_PLAN):
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/essential",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.data)
            self.assertFalse(body["data"]["eligible"])
            pending_blocker = [b for b in body["data"]["blocking_items"] if b["resource"] == "team_members_including_pending"]
            self.assertTrue(len(pending_blocker) > 0)

    def test_knowledge_storage_excess(self):
        usage = dict(USAGE_WITHIN_LIMITS)
        usage["usage"] = dict(usage["usage"])
        usage["usage"]["knowledge_storage_bytes"] = {"used": 100000000, "limit": 1000000000}
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_subscription(), self._patch_get_usage(return_value=usage), \
             self._patch_get_plan_by_code(return_value=ESSENTIAL_PLAN):
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/essential",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
            body = json.loads(resp.data)
            self.assertFalse(body["data"]["eligible"])
            kb_blocker = [b for b in body["data"]["blocking_items"] if b["resource"] == "knowledge_storage_bytes"]
            self.assertTrue(len(kb_blocker) > 0)

    # --- Negative cases ---

    def test_free_target_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/free",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 400)

    def test_same_plan_rejected(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_plan_by_code(return_value=ESSENTIAL_PLAN), \
             self._patch_get_subscription():
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/pro",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 400)

    def test_higher_plan_rejected(self):
        sub_essential = {
            "id": 10, "company_id": 42, "plan_id": 1, "status": "active",
            "plan": {"code": "essential", "name": "Essential"},
        }
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_plan_by_code(return_value=ESSENTIAL_PLAN), \
             self._patch_get_subscription(return_value=sub_essential):
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/advanced",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 400)

    def test_invalid_plan_code(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/invalid-plan",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 400)

    def test_missing_subscription(self):
        with self._patch_jwt_decode(), self._patch_user_repo(), \
             self._patch_get_plan_by_code(return_value=ESSENTIAL_PLAN), \
             self._patch_get_subscription(return_value=None):
            resp = self.client.get(
                "/api/billing/subscription/downgrade-check/essential",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 404)

    def test_no_auth(self):
        resp = self.client.get("/api/billing/subscription/downgrade-check/essential")
        self.assertEqual(resp.status_code, 401)


class TestPlanChangePricing(unittest.TestCase):
    """Tests for plan-change behaviour and access policy via service functions."""

    def test_trial_sees_current_trial_on_free(self):
        """Active Free trial has access_state=active_trial."""
        from app.services.ai_access_policy import resolve_ai_access
        trial_sub = {
            "plan_id": 0, "status": "trialing",
            "trial_ends_at": "2026-07-15T00:00:00Z",
        }
        with patch(
            "app.services.ai_access_policy._get_company_subscription",
            return_value=trial_sub,
        ), patch(
            "app.services.ai_access_policy.get_plan_by_id",
            return_value={"code": "free", "name": "Free"},
        ):
            policy = resolve_ai_access(
                42, now=datetime(2026, 7, 10, tzinfo=timezone.utc)
            )
            self.assertEqual(policy.access_state, "active_trial")
            self.assertTrue(policy.allowed)

    def test_expired_paid_not_converted_to_free(self):
        """Expired paid plan stays on paid plan code."""
        from app.services.billing_service import get_current_subscription
        expired_sub = {
            "id": 10, "company_id": 42, "plan_id": 3, "status": "expired",
            "trial_ends_at": None,
        }
        with patch(
            "app.services.billing_service._get_company_subscription",
            return_value=expired_sub,
        ), patch(
            "app.services.billing_service.get_plan_by_id",
            return_value={
                "id": 3, "code": "pro", "name": "Pro", "price": "169",
                "currency": "MYR", "billing_interval": "month",
                "chatbot_limit": 10, "team_member_limit": 5,
                "knowledge_file_limit": 75, "knowledge_storage_limit_bytes": 1000000000,
                "channel_limit": 10, "feature_flags": {},
                "included_ai_credit_micro_myr": 60000000, "model_access_tier": "premium",
            },
        ):
            sub = get_current_subscription(42)
            self.assertIsNotNone(sub)
            self.assertEqual(sub["plan"]["code"], "pro")
            self.assertEqual(sub["status"], "expired")

    def test_past_due_denies_ai(self):
        """Past due status blocks AI access."""
        from app.services.ai_access_policy import resolve_ai_access
        past_due_sub = {
            "plan_id": 3, "status": "past_due",
        }
        with patch(
            "app.services.ai_access_policy._get_company_subscription",
            return_value=past_due_sub,
        ), patch(
            "app.services.ai_access_policy.get_plan_by_id",
            return_value={"code": "pro", "name": "Pro"},
        ):
            policy = resolve_ai_access(42)
            self.assertFalse(policy.allowed)
            self.assertEqual(policy.access_state, "past_due")

    def test_expired_denies_ai(self):
        """Expired status blocks AI access."""
        from app.services.ai_access_policy import resolve_ai_access
        expired_sub = {
            "plan_id": 3, "status": "expired",
        }
        with patch(
            "app.services.ai_access_policy._get_company_subscription",
            return_value=expired_sub,
        ), patch(
            "app.services.ai_access_policy.get_plan_by_id",
            return_value={"code": "pro", "name": "Pro"},
        ):
            policy = resolve_ai_access(42)
            self.assertFalse(policy.allowed)
            self.assertEqual(policy.access_state, "unknown")

    def test_ensure_default_keeps_existing(self):
        """ensure_default_company_subscription does not overwrite existing paid subscription."""
        from app.services.billing_service import ensure_default_company_subscription
        existing_sub = {
            "id": 10, "company_id": 42, "plan_id": 3, "status": "active",
        }
        with patch(
            "app.services.billing_service._get_latest_company_subscription",
            return_value=existing_sub,
        ), patch(
            "app.services.billing_service._get_company_subscription",
            return_value=existing_sub,
        ), patch(
            "app.services.billing_service.get_plan_by_id",
            return_value={
                "id": 3, "code": "pro", "name": "Pro", "price": "169",
                "currency": "MYR", "billing_interval": "month",
                "chatbot_limit": 10, "team_member_limit": 5,
                "knowledge_file_limit": 75, "knowledge_storage_limit_bytes": 1000000000,
                "channel_limit": 10, "feature_flags": {},
                "included_ai_credit_micro_myr": 60000000, "model_access_tier": "premium",
            },
        ):
            sub = ensure_default_company_subscription(42)
            self.assertEqual(sub["plan"]["code"], "pro")
            self.assertEqual(sub["status"], "active")


if __name__ == "__main__":
    unittest.main()
