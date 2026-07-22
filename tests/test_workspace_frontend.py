import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8000")
os.environ.setdefault("FLASK_DEBUG", "1")
os.environ.setdefault("RATELIMIT_ENABLED", "false")

from app import create_app


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = (ROOT / "frontend" / "profile.html").read_text(encoding="utf-8", errors="replace")
        cls.team = (ROOT / "frontend" / "team.html").read_text(encoding="utf-8", errors="replace")
        cls.accept = (ROOT / "frontend" / "accept-invite.html").read_text(encoding="utf-8", errors="replace")

    def test_profile_has_two_compact_workspace_cards_and_no_placeholders(self):
        self.assertIn("Company Information", self.profile)
        self.assertIn("Team Summary", self.profile)
        self.assertIn('authenticatedFetch("/api/workspace")', self.profile)
        self.assertNotIn("AI Chatbot Team", self.profile)
        self.assertNotIn("your-app.com/invite/ABC123", self.profile)
        self.assertNotIn("member-avatar-mini", self.profile)

    def test_profile_renders_role_counts_and_singular_plural(self):
        self.assertIn("data.current_user_role", self.profile)
        self.assertIn("data.active_member_count", self.profile)
        self.assertIn("data.pending_invitation_count", self.profile)
        self.assertIn('active === 1 ? "" : "s"', self.profile)

    def test_profile_company_save_has_loading_and_permission_states(self):
        self.assertIn("saveCompanyInformation", self.profile)
        self.assertIn("data.can_edit_company", self.profile)
        self.assertIn("Saving...", self.profile)

    def test_team_uses_same_workspace_summary_and_allows_read_only_members(self):
        self.assertIn('authenticatedFetch("/api/workspace")', self.team)
        self.assertNotIn("requireAdminOrOwner();", self.team)
        self.assertIn('currentUserRole !== "admin" && currentUserRole !== "owner"', self.team)

    def test_google_invitation_passes_invite_token(self):
        self.assertIn("invite_token: getTokenFromUrl()", self.accept)
        self.assertIn("onGoogleInviteCredential", self.accept)

    def test_google_invitation_uses_runtime_configuration_without_hardcoded_client_id(self):
        self.assertNotIn(".apps.googleusercontent.com", self.accept)
        self.assertNotIn("g_id_onload", self.accept)
        self.assertNotIn("data-client_id", self.accept)
        self.assertIn("fetch('/api/auth/google-config')", self.accept)
        self.assertIn("google.accounts.id.initialize({", self.accept)
        self.assertIn("client_id: googleClientId", self.accept)
        self.assertIn("google.accounts.id.renderButton(", self.accept)

    def test_google_unavailable_does_not_disable_password_acceptance(self):
        config_function = re.search(
            r"async function loadGoogleConfiguration\(\) \{.*?\n        \}",
            self.accept,
            flags=re.S,
        ).group(0)
        self.assertIn("hideGoogleInviteOption();", config_function)
        self.assertNotIn("showInvalid(", config_function)
        self.assertNotIn("submitBtn", config_function)
        self.assertIn('id="acceptForm" onsubmit="return handleSubmit(event)"', self.accept)
        self.assertIn("fetch('/api/invites/accept'", self.accept)
        self.assertIn("You can continue with your name and password.", self.accept)


class GoogleConfigRouteTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_google_config_returns_only_trimmed_public_client_id(self):
        with patch.dict(os.environ, {
            "GOOGLE_CLIENT_ID": "  configured-client-id  ",
            "GOOGLE_CLIENT_SECRET": "must-not-be-exposed",
            "SUPABASE_SERVICE_ROLE_KEY": "also-must-not-be-exposed",
        }):
            response = self.client.get("/api/auth/google-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "status": "success",
            "data": {"client_id": "configured-client-id"},
        })
        body = response.get_data(as_text=True)
        self.assertNotIn("must-not-be-exposed", body)
        self.assertNotIn("also-must-not-be-exposed", body)
        self.assertNotIn("secret", body.lower())

    def test_google_config_missing_client_id_is_sanitized_and_unavailable(self):
        with patch.dict(os.environ, {
            "GOOGLE_CLIENT_ID": "   ",
            "GOOGLE_CLIENT_SECRET": "private-google-secret",
        }):
            response = self.client.get("/api/auth/google-config")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {
            "status": "error",
            "message": "Google sign-in is currently unavailable.",
        })
        body = response.get_data(as_text=True)
        self.assertNotIn("private-google-secret", body)
        self.assertNotIn("GOOGLE_CLIENT_ID", body)


if __name__ == "__main__":
    unittest.main()
