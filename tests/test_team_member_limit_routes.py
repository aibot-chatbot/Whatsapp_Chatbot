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

    def test_post_users_returns_410_and_requires_email_invitations(self):
        with self._patch_auth(), self._patch_current_user():
            response = self.client.post(
                "/api/users",
                json=VALID_MEMBER_PAYLOAD,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 410)
        body = response.get_json()
        self.assertEqual(body["status"], "error")
        self.assertIn("email invitations", body["message"].lower())

    def test_post_users_does_not_invoke_direct_creation_dependencies(self):
        with self._patch_auth(), self._patch_current_user(), \
             patch("app.routes.user_routes.get_user_by_email", create=True) as lookup_user, \
             patch("app.routes.user_routes.generate_password_hash") as hash_password, \
             patch("app.routes.user_routes.create_user", create=True) as create_user, \
             patch("app.routes.user_routes.can_add_team_member") as capacity_guard:
            response = self.client.post(
                "/api/users",
                json=VALID_MEMBER_PAYLOAD,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 410)
        body = response.get_json()
        self.assertEqual(body["status"], "error")
        self.assertIn("email invitations", body["message"].lower())
        lookup_user.assert_not_called()
        hash_password.assert_not_called()
        create_user.assert_not_called()
        capacity_guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
