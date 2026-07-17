"""Route tests for team-member subscription enforcement."""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

sys.path.insert(0, "C:\\Users\\User\\PycharmProjects\\python-whatsapp-bot-main")

if "google" not in sys.modules:
    google_module = types.ModuleType("google")
    google_module.genai = types.ModuleType("google.genai")
    google_module.genai.Client = MagicMock()
    sys.modules["google"] = google_module
    sys.modules["google.genai"] = google_module.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "_tools" not in sys.modules:
    sys.modules["_tools"] = types.ModuleType("_tools")

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app
    from app.services.billing_guard import BillingLimitError


CURRENT_USER = {
    "id": 1,
    "company_id": 42,
    "email": "admin@example.com",
    "role": "admin",
    "status": "active",
}

VALID_MEMBER_PAYLOAD = {
    "full_name": "New Member",
    "email": "new.member@example.com",
    "role": "member",
    "password": "StrongPass1!",
    "confirm_password": "StrongPass1!",
}


class TestDirectTeamMemberCreationLimit(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def _patch_auth(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_current_user(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=CURRENT_USER,
        )

    def test_post_users_succeeds_below_team_member_limit(self):
        created_user = {
            "id": 99,
            "company_id": 42,
            "phone": None,
            "full_name": "New Member",
            "email": "new.member@example.com",
            "role": "member",
            "status": "active",
            "is_verified": True,
        }

        with self._patch_auth(), self._patch_current_user(), \
             patch("app.routes.user_routes.get_user_by_email", return_value=None), \
             patch("app.routes.user_routes.can_add_team_member", return_value=True) as mock_guard, \
             patch("app.routes.user_routes.create_user", return_value=created_user) as mock_create:
            response = self.client.post(
                "/api/users",
                json=VALID_MEMBER_PAYLOAD,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["email"], "new.member@example.com")
        mock_guard.assert_called_once_with(42)
        mock_create.assert_called_once()

    def test_post_users_returns_403_at_team_member_limit(self):
        error = BillingLimitError(
            "Team member limit reached for the current subscription plan.",
            code="team_member_limit",
            details={"used": 5, "limit": 5},
        )

        with self._patch_auth(), self._patch_current_user(), \
             patch("app.routes.user_routes.get_user_by_email", return_value=None), \
             patch("app.routes.user_routes.can_add_team_member", side_effect=error), \
             patch("app.routes.user_routes.create_user") as mock_create:
            response = self.client.post(
                "/api/users",
                json=VALID_MEMBER_PAYLOAD,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["code"], "team_member_limit")
        self.assertEqual(
            body["message"],
            "Team member limit reached for the current subscription plan.",
        )
        self.assertEqual(body["details"], {"used": 5, "limit": 5})
        mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
