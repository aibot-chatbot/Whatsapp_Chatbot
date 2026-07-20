import unittest
from unittest.mock import call, patch

from flask import Flask, g, jsonify

from app.decorators.platform_admin_decorator import platform_admin_required


class PlatformAdminAuthorizationTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.get("/protected")
        @platform_admin_required
        def protected():
            return jsonify({"actor": g.platform_admin_user["id"]})

        self.app = app
        self.protected = protected
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}
        self.jwt = patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"user_id": 7, "company_id": 99, "role": "member", "platform_admin": True},
        )
        self.secret = patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret")
        self.jwt_decode = self.jwt.start()
        self.secret.start()
        self.addCleanup(self.jwt.stop)
        self.addCleanup(self.secret.stop)

    def _request(self, user=None, mapping=None, user_error=None, mapping_error=None):
        user = user if user is not None else {"id": 7, "status": "active", "role": "member"}
        user_patch = patch("app.database.user_repository.get_user_by_id")
        mapping_patch = patch(
            "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id"
        )
        with user_patch as get_user, mapping_patch as get_mapping:
            get_user.side_effect = user_error
            get_user.return_value = user
            get_mapping.side_effect = mapping_error
            get_mapping.return_value = mapping
            response = self.client.get("/protected", headers=self.headers)
            return response, get_mapping

    def test_tenant_admin_and_owner_without_mapping_are_denied(self):
        for role in ("admin", "owner"):
            response, _ = self._request(user={"id": 7, "status": "active", "role": role})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json["code"], "platform_admin_access_denied")

    def test_active_mapped_member_allowed(self):
        response, mapping = self._request(mapping={"id": 12, "user_id": 7, "is_active": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["actor"], 12)
        mapping.assert_called_once_with(7)

    def test_forged_platform_jwt_claim_has_no_effect(self):
        self.jwt_decode.return_value = {
            "user_id": 7, "company_id": 99, "role": "member",
            "platform_admin": True, "is_platform_admin": True,
        }
        denied, denied_lookup = self._request(mapping=None)
        self.assertEqual(denied.status_code, 403)
        denied_lookup.assert_called_once_with(7)

        self.jwt_decode.return_value = {
            "user_id": 7, "company_id": 99, "role": "member",
            "platform_admin": False, "is_platform_admin": False,
        }
        allowed, allowed_lookup = self._request(
            mapping={"id": 12, "user_id": 7, "is_active": True}
        )
        self.assertEqual(allowed.status_code, 200)
        allowed_lookup.assert_called_once_with(7)

    def test_missing_and_inactive_mapping_have_same_denial(self):
        for mapping in (None, {"id": 12, "user_id": 7, "is_active": False}):
            response, _ = self._request(mapping=mapping)
            self.assertEqual((response.status_code, response.json["code"]), (403, "platform_admin_access_denied"))

    def test_inactive_application_user_denied_before_mapping_lookup(self):
        response, mapping = self._request(user={"id": 7, "status": "inactive"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json["code"], "account_inactive")
        mapping.assert_not_called()

    def test_user_repository_failure_is_sanitized(self):
        response, mapping = self._request(user_error=RuntimeError("supabase secret detail"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "authentication_backend_unavailable")
        self.assertNotIn("supabase", response.get_data(as_text=True).lower())
        mapping.assert_not_called()

    def test_mapping_repository_failure_is_sanitized(self):
        response, _ = self._request(mapping_error=RuntimeError("database secret detail"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_authorization_unavailable")
        self.assertNotIn("database", response.get_data(as_text=True).lower())

    def test_role_changes_do_not_affect_access(self):
        for role in ("owner", "admin", "member"):
            response, _ = self._request(
                user={"id": 7, "status": "active", "role": role},
                mapping={"id": 12, "user_id": 7, "is_active": True},
            )
            self.assertEqual(response.status_code, 200)

    def test_mapping_is_refreshed_and_revocation_applies_next_request(self):
        with patch("app.database.user_repository.get_user_by_id", return_value={"id": 7, "status": "active"}), patch(
            "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
            side_effect=[{"id": 12, "is_active": True}, None],
        ) as lookup:
            self.assertEqual(self.client.get("/protected", headers=self.headers).status_code, 200)
            self.assertEqual(self.client.get("/protected", headers=self.headers).status_code, 403)
            self.assertEqual(lookup.call_count, 2)
            self.assertEqual(lookup.call_args_list, [call(7), call(7)])

    def test_missing_authenticated_user_context_fails_closed(self):
        with self.app.test_request_context("/protected"):
            response, status_code = self.protected.__wrapped__()
        self.assertEqual(status_code, 500)
        self.assertEqual(response.get_json()["code"], "platform_admin_guard_misconfigured")

    def test_malformed_authenticated_user_ids_fail_before_mapping_lookup(self):
        for malformed_id in (True, 0, -1, "7", None):
            with self.subTest(user_id=malformed_id):
                response, mapping = self._request(
                    user={"id": malformed_id, "status": "active", "role": "member"},
                    mapping={"id": 12, "is_active": True},
                )
                self.assertEqual(response.status_code, 500)
                self.assertEqual(
                    response.json["code"], "platform_admin_guard_misconfigured"
                )
                mapping.assert_not_called()


if __name__ == "__main__":
    unittest.main()
