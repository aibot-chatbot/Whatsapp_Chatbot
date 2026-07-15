"""Tests for is_password_valid() — plaintext fallback removal (Security Phase 1)."""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

import sys
sys.path.insert(0, "C:\\Users\\User\\PycharmProjects\\python-whatsapp-bot-main")

import unittest
from werkzeug.security import generate_password_hash


# Import the function directly at module level to avoid method-binding issues
from app.routes.auth_routes import is_password_valid


class TestIsPasswordValid(unittest.TestCase):
    """Verify is_password_valid uses only hash verification, no plaintext fallback."""

    def test_valid_hashed_password_authenticates(self):
        """Correct password against a properly hashed value returns True."""
        pw = "StrongP@ss1"
        hashed = generate_password_hash(pw)
        self.assertTrue(is_password_valid(hashed, pw))

    def test_invalid_password_fails(self):
        """Wrong password against a properly hashed value returns False."""
        pw = "StrongP@ss1"
        hashed = generate_password_hash(pw)
        self.assertFalse(is_password_valid(hashed, "WrongPassword1!"))

    def test_plaintext_equal_to_input_does_not_authenticate(self):
        """Stored value that equals user input must NOT authenticate (no plaintext fallback)."""
        pw = "MyPlaintextPassword"
        self.assertFalse(is_password_valid(pw, pw))

    def test_empty_stored_password_fails(self):
        """Empty or None stored_password always returns False."""
        self.assertFalse(is_password_valid("", "anything"))
        self.assertFalse(is_password_valid(None, "anything"))

    def test_empty_input_password_fails(self):
        """Empty or None input_password always returns False."""
        hashed = generate_password_hash("StrongP@ss1")
        self.assertFalse(is_password_valid(hashed, ""))
        self.assertFalse(is_password_valid(hashed, None))

    def test_malformed_stored_hash_fails_safely(self):
        """A stored value that is not a valid Werkzeug hash returns False, not an exception."""
        self.assertFalse(is_password_valid("not-a-valid-hash-format", "anything"))

    def test_both_empty_fails(self):
        """Both values empty returns False."""
        self.assertFalse(is_password_valid("", ""))
        self.assertFalse(is_password_valid(None, None))


class TestPasswordResetErrorExposure(unittest.TestCase):
    """Verify password reset 500 responses do not expose internal details."""

    @classmethod
    def setUpClass(cls):
        import types
        from unittest.mock import patch, MagicMock

        # Mock broken deps
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
            cls.app = create_app()
            cls.app.config["TESTING"] = True
            cls.client = cls.app.test_client()

    def test_reset_password_500_does_not_expose_internal_error(self):
        """When password reset fails internally, the response must not leak exception details."""
        from unittest.mock import patch
        from werkzeug.security import generate_password_hash

        with patch("app.routes.auth_routes.get_password_reset_otp") as mock_otp:
            mock_otp.return_value = {
                "otp_code": "123456",
                "verified": True,
                "otp_expiry": "2099-01-01T00:00:00+00:00",
            }
            with patch("app.database.db.supabase") as mock_db:
                # Simulate a DB failure during password update
                mock_chain = mock_db.table.return_value.update.return_value.eq.return_value
                mock_chain.execute.side_effect = RuntimeError("connection refused: table 'users' not found")

                resp = self.client.post(
                    "/api/auth/reset-password",
                    json={
                        "email": "test@example.com",
                        "otp": "123456",
                        "password": "NewStrongP@ss1",
                        "confirm_password": "NewStrongP@ss1",
                    },
                )

                self.assertEqual(resp.status_code, 500)
                data = resp.get_json()
                self.assertEqual(data["status"], "error")
                self.assertIn("Unable to reset password", data["message"])
                # Must NOT leak internal details
                self.assertNotIn("connection refused", data["message"])
                self.assertNotIn("RuntimeError", data["message"])
                self.assertNotIn("table", data["message"])
                self.assertNotIn("not found", data["message"])


if __name__ == "__main__":
    unittest.main()
