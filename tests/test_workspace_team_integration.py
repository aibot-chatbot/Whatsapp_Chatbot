import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch
from werkzeug.security import generate_password_hash
from postgrest.exceptions import APIError

from tests.frontend_pages import page_source_path

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8000")
os.environ.setdefault("FLASK_DEBUG", "1")
os.environ.setdefault("RATELIMIT_ENABLED", "false")

from app import create_app
from app.services.invitation_service import (
    InvitationValidationError,
    accept_pending_invitation,
    get_valid_pending_invitation,
)
from app.services.workspace_service import get_workspace_summary, update_workspace_company
from app.services.billing_guard import BillingLimitError, can_accept_team_invitation, can_add_team_member
from app.database.user_repository import count_active_users_by_company, update_user_for_company
from app.database.invite_repository import (
    delete_invite,
    get_invite_by_id,
    get_pending_invite_by_email,
    update_invite_for_company,
)
from app.utils.auth_token import build_password_fingerprint


ADMIN = {"id": 1, "company_id": 42, "email": "admin@example.com", "role": "admin", "status": "active", "password_hash": None}
MEMBER = {"id": 2, "company_id": 42, "email": "member@example.com", "role": "member", "status": "active", "password_hash": None}
WORKSPACE = {
    "company": {"name": "Acme", "contact_email": "contact@acme.test", "contact_phone": ""},
    "current_user_role": "admin",
    "active_member_count": 2,
    "pending_invitation_count": 1,
    "plan_member_limit": 5,
    "remaining_seats": 2,
    "can_edit_company": True,
    "can_manage_team": True,
}


class WorkspaceRouteTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def auth(self, user=ADMIN, jwt_company=999, jwt_role="member"):
        return (
            patch("app.decorators.auth_decorator.jwt.decode", return_value={
                "user_id": user["id"],
                "company_id": jwt_company,
                "role": jwt_role,
                "pwdv": build_password_fingerprint(user),
            }),
            patch("app.database.user_repository.get_user_by_id", return_value=user),
        )

    def test_workspace_uses_database_refreshed_company_and_ignores_browser_context(self):
        auth, user = self.auth()
        with auth, user, patch("app.routes.profile_routes.get_workspace_summary", return_value=WORKSPACE) as summary:
            response = self.client.get("/api/workspace?company_id=99&bot_id=777", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        summary.assert_called_once_with(42, ADMIN)
        self.assertNotIn("company_id", response.get_json()["data"])

    def test_admin_can_update_company_with_authenticated_company(self):
        auth, user = self.auth()
        with auth, user, patch("app.routes.profile_routes.update_workspace_company", return_value=WORKSPACE) as update:
            response = self.client.put("/api/workspace?company_id=99", headers=self.headers, json={"company_name": "Acme", "contact_email": "Contact@Acme.test"})
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with(42, ADMIN, {"company_name": "Acme", "contact_email": "Contact@Acme.test"})

    def test_member_cannot_update_company(self):
        auth, user = self.auth(MEMBER, jwt_role="admin")
        with auth, user, patch("app.routes.profile_routes.update_workspace_company", side_effect=PermissionError("denied")):
            response = self.client.put("/api/workspace", headers=self.headers, json={"company_name": "Nope", "contact_email": "nope@test.test"})
        self.assertEqual(response.status_code, 403)

    def test_team_list_is_scoped_to_refreshed_company_even_with_bot_id(self):
        auth, user = self.auth(MEMBER)
        with auth, user, patch("app.routes.user_routes.get_users_by_company", return_value=[]) as users:
            response = self.client.get("/api/users?company_id=99&bot_id=777", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        users.assert_called_once_with(42)

    def test_cross_company_member_management_is_rejected_by_scoped_lookup(self):
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.user_routes.get_user_by_id_for_company", return_value=None) as target, \
             patch("app.routes.user_routes.update_user_for_company") as update:
            response = self.client.put("/api/users/99/role?bot_id=777", headers=self.headers, json={"role": "member"})
        self.assertEqual(response.status_code, 404)
        target.assert_called_once_with(99, 42)
        update.assert_not_called()

    def test_login_email_cannot_be_changed_through_user_update(self):
        auth, user = self.auth(ADMIN)
        with auth, user, patch("app.routes.user_routes.update_user") as update:
            response = self.client.put(
                "/api/user",
                headers=self.headers,
                json={"email": "replacement@example.test"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be changed", response.get_json()["message"])
        update.assert_not_called()

    def test_direct_team_user_creation_is_unavailable(self):
        auth, user = self.auth(ADMIN)
        with auth, user:
            response = self.client.post(
                "/api/users",
                headers=self.headers,
                json={"email": "new@example.test", "password": "NotUsed123!"},
            )
        self.assertEqual(response.status_code, 410)
        self.assertIn("email invitations", response.get_json()["message"])

    def test_role_change_uses_company_scoped_write(self):
        target_user = {**MEMBER, "id": 7}
        updated_user = {**target_user, "role": "admin"}
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.user_routes.get_user_by_id_for_company", return_value=target_user), \
             patch("app.routes.user_routes.update_user_for_company", return_value=updated_user) as scoped_update, \
             patch("app.routes.user_routes.update_user") as global_update:
            response = self.client.put("/api/users/7/role", headers=self.headers, json={"role": "admin"})
        self.assertEqual(response.status_code, 200)
        scoped_update.assert_called_once_with(7, 42, {"role": "admin"})
        global_update.assert_not_called()

    def test_deactivation_uses_scoped_write_without_limit_check(self):
        target_user = {**MEMBER, "id": 7}
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.user_routes.get_user_by_id_for_company", return_value=target_user), \
             patch("app.routes.user_routes.can_add_team_member") as limit_guard, \
             patch("app.routes.user_routes.update_user_for_company", return_value={**target_user, "status": "inactive"}) as scoped_update, \
             patch("app.routes.user_routes.update_user") as global_update:
            response = self.client.put("/api/users/7/status", headers=self.headers, json={"status": "inactive"})
        self.assertEqual(response.status_code, 200)
        limit_guard.assert_not_called()
        scoped_update.assert_called_once_with(7, 42, {"status": "inactive"})
        global_update.assert_not_called()

    def test_reactivation_checks_limit_then_uses_scoped_write(self):
        target_user = {**MEMBER, "id": 7, "status": "inactive"}
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.user_routes.get_user_by_id_for_company", return_value=target_user), \
             patch("app.routes.user_routes.can_add_team_member", return_value=True) as limit_guard, \
             patch("app.routes.user_routes.update_user_for_company", return_value={**target_user, "status": "active"}) as scoped_update:
            response = self.client.put("/api/users/7/status", headers=self.headers, json={"status": "active"})
        self.assertEqual(response.status_code, 200)
        limit_guard.assert_called_once_with(42)
        scoped_update.assert_called_once_with(7, 42, {"status": "active"})

    def test_platform_staff_deactivation_returns_database_guard_denial(self):
        error = APIError({"code": "42501", "message": "platform_staff_account_protected",
                          "details": "Internal database context", "hint": None})
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.user_routes.get_user_by_id_for_company", return_value={**MEMBER, "id": 7}), \
             patch("app.routes.user_routes.update_user_for_company", side_effect=error) as scoped_update:
            response = self.client.put("/api/users/7/status", headers=self.headers, json={"status": "inactive"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "platform_staff_account_protected")
        self.assertNotIn("Internal database context", response.get_data(as_text=True))
        scoped_update.assert_called_once_with(7, 42, {"status": "inactive"})

    def test_reactivation_rejects_limit_error_before_write(self):
        target_user = {**MEMBER, "id": 7, "status": "inactive"}
        error = BillingLimitError("Upgrade required.", code="team_member_limit", details={"limit": 2})
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.user_routes.get_user_by_id_for_company", return_value=target_user), \
             patch("app.routes.user_routes.can_add_team_member", side_effect=error), \
             patch("app.routes.user_routes.update_user_for_company") as scoped_update:
            response = self.client.put("/api/users/7/status", headers=self.headers, json={"status": "active"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "team_member_limit")
        self.assertEqual(response.get_json()["details"], {"limit": 2})
        scoped_update.assert_not_called()

    def test_owner_accounts_cannot_be_demoted_or_deactivated(self):
        owner = {**ADMIN, "id": 7, "role": "owner"}
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.user_routes.get_user_by_id_for_company", return_value=owner), \
             patch("app.routes.user_routes.update_user_for_company") as scoped_update:
            role_response = self.client.put("/api/users/7/role", headers=self.headers, json={"role": "member"})
            status_response = self.client.put("/api/users/7/status", headers=self.headers, json={"status": "inactive"})
        self.assertEqual(role_response.status_code, 403)
        self.assertEqual(status_response.status_code, 403)
        scoped_update.assert_not_called()

    def test_owner_role_cannot_be_assigned(self):
        auth, user = self.auth(ADMIN)
        with auth, user, patch("app.routes.user_routes.get_user_by_id_for_company") as lookup:
            response = self.client.put("/api/users/7/role", headers=self.headers, json={"role": "owner"})
        self.assertEqual(response.status_code, 400)
        lookup.assert_not_called()

    def test_backend_rejects_invitation_when_plan_limit_is_reached(self):
        auth, user = self.auth(ADMIN, jwt_role="member")
        limit_error = BillingLimitError("Team member limit reached for the current subscription plan.", code="team_member_limit")
        with auth, user, \
             patch("app.routes.invite_routes.get_user_by_email", return_value=None), \
             patch("app.routes.invite_routes.get_pending_invite_by_email", return_value=None), \
             patch("app.routes.invite_routes.can_add_team_member", side_effect=limit_error), \
             patch("app.routes.invite_routes.create_invite") as create_invite:
            response = self.client.post("/api/invites", headers=self.headers, json={"email": "new@example.com", "role": "member"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "team_member_limit")
        create_invite.assert_not_called()


class InvitationRouteTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def auth(self, user=ADMIN, jwt_company=999, jwt_role="member"):
        return (
            patch("app.decorators.auth_decorator.jwt.decode", return_value={
                "user_id": user["id"],
                "company_id": jwt_company,
                "role": jwt_role,
                "pwdv": build_password_fingerprint(user),
            }),
            patch("app.database.user_repository.get_user_by_id", return_value=user),
        )

    def test_generated_invitation_url_uses_html_page(self):
        from app.routes.invite_routes import _build_invite_url

        app = create_app()
        app.config["FRONTEND_URL"] = "https://app.example.test/"
        with app.app_context():
            self.assertEqual(
                _build_invite_url("secure-token"),
                "https://app.example.test/accept-invite.html?token=secure-token",
            )

    def test_existing_registered_user_cannot_be_invited(self):
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.invite_routes.get_user_by_email", return_value={"id": 9}) as lookup, \
             patch("app.routes.invite_routes.get_pending_invite_by_email") as pending_lookup, \
             patch("app.routes.invite_routes.can_add_team_member") as capacity_guard, \
             patch("app.routes.invite_routes.create_invite") as create_invite, \
             patch("app.services.email_service.send_invite_email") as send_email:
            response = self.client.post(
                "/api/invites",
                headers=self.headers,
                json={"email": " Existing@Example.Test ", "role": "member"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("registered user", response.get_json()["message"].lower())
        lookup.assert_called_once_with("existing@example.test")
        pending_lookup.assert_not_called()
        capacity_guard.assert_not_called()
        create_invite.assert_not_called()
        send_email.assert_not_called()

    def test_expired_pending_invitation_is_refreshed_without_duplicate(self):
        auth, user = self.auth(ADMIN)
        stale_invite = {
            "id": 8,
            "company_id": 42,
            "email": "rejoin@example.test",
            "role": "member",
            "status": "pending",
            "token": "expired-token",
            "expires_at": "2020-01-01T00:00:00+00:00",
        }
        refreshed_expiry = "2030-01-01T00:00:00+00:00"
        with auth, user, \
             patch("app.routes.invite_routes.get_user_by_email", return_value=None), \
             patch("app.routes.invite_routes.get_pending_invite_by_email", side_effect=[None, stale_invite]) as pending_lookup, \
             patch("app.routes.invite_routes.can_add_team_member", return_value=True), \
             patch("app.routes.invite_routes.secrets.token_urlsafe", return_value="replacement-token"), \
             patch("app.routes.invite_routes.build_invite_expiry", return_value=refreshed_expiry), \
             patch("app.routes.invite_routes.update_invite_for_company", return_value={**stale_invite, "token": "replacement-token"}) as scoped_update, \
             patch("app.routes.invite_routes.create_invite") as create_invite, \
             patch("app.services.email_service.send_invite_email") as send_email:
            response = self.client.post(
                "/api/invites",
                headers=self.headers,
                json={"email": " Rejoin@Example.Test ", "role": "member"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(pending_lookup.call_args_list, [
            call("rejoin@example.test", 42),
            call("rejoin@example.test", 42, valid_only=False),
        ])
        scoped_update.assert_called_once_with(8, 42, {
            "token": "replacement-token",
            "expires_at": refreshed_expiry,
            "role": "member",
            "status": "pending",
            "created_by": 1,
        })
        create_invite.assert_not_called()
        sent_url = send_email.call_args.args[1]
        self.assertTrue(sent_url.endswith("/accept-invite.html?token=replacement-token"))
        self.assertNotIn("expired-token", sent_url)

    def test_invitation_without_previous_pending_row_is_created(self):
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.invite_routes.get_user_by_email", return_value=None), \
             patch("app.routes.invite_routes.get_pending_invite_by_email", side_effect=[None, None]) as pending_lookup, \
             patch("app.routes.invite_routes.can_add_team_member", return_value=True), \
             patch("app.routes.invite_routes.secrets.token_urlsafe", return_value="new-token"), \
             patch("app.routes.invite_routes.build_invite_expiry", return_value="2030-01-01T00:00:00+00:00"), \
             patch("app.routes.invite_routes.update_invite_for_company") as scoped_update, \
             patch("app.routes.invite_routes.create_invite", return_value={"id": 9}) as create_invite, \
             patch("app.services.email_service.send_invite_email") as send_email:
            response = self.client.post(
                "/api/invites",
                headers=self.headers,
                json={"email": " New@Example.Test ", "role": "admin"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(pending_lookup.call_args_list, [
            call("new@example.test", 42),
            call("new@example.test", 42, valid_only=False),
        ])
        scoped_update.assert_not_called()
        create_invite.assert_called_once_with(
            email="new@example.test",
            company_id=42,
            role="admin",
            token="new-token",
            created_by=1,
        )
        self.assertIn("token=new-token", send_email.call_args.args[1])

    def test_valid_pending_invitation_blocks_duplicate_without_write_or_email(self):
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.invite_routes.get_user_by_email", return_value=None), \
             patch("app.routes.invite_routes.get_pending_invite_by_email", return_value={"id": 7}), \
             patch("app.routes.invite_routes.can_add_team_member") as capacity_guard, \
             patch("app.routes.invite_routes.create_invite") as create_invite, \
             patch("app.services.email_service.send_invite_email") as send_email:
            response = self.client.post(
                "/api/invites",
                headers=self.headers,
                json={"email": "pending@example.test", "role": "member"},
            )

        self.assertEqual(response.status_code, 409)
        capacity_guard.assert_not_called()
        create_invite.assert_not_called()
        send_email.assert_not_called()

    def test_resend_rotates_token_expiry_and_uses_company_scope(self):
        auth, user = self.auth(ADMIN)
        invite = {
            "id": 7,
            "company_id": 42,
            "email": "invitee@example.test",
            "role": "member",
            "status": "pending",
            "token": "old-token",
            "expires_at": "2020-01-01T00:00:00+00:00",
        }
        refreshed_expiry = "2030-01-01T00:00:00+00:00"
        with auth, user, \
             patch("app.routes.invite_routes.get_invite_by_id", return_value=invite) as scoped_get, \
             patch("app.routes.invite_routes.secrets.token_urlsafe", return_value="new-token"), \
             patch("app.routes.invite_routes.build_invite_expiry", return_value=refreshed_expiry), \
             patch("app.routes.invite_routes.update_invite_for_company", return_value={**invite, "token": "new-token"}) as scoped_update, \
             patch("app.services.email_service.send_invite_email") as send_email:
            response = self.client.post(
                "/api/invites/resend",
                headers=self.headers,
                json={"invite_id": 7},
            )

        self.assertEqual(response.status_code, 200)
        scoped_get.assert_called_once_with(7, 42)
        scoped_update.assert_called_once_with(7, 42, {
            "token": "new-token",
            "expires_at": refreshed_expiry,
        })
        sent_url = send_email.call_args.args[1]
        self.assertIn("token=new-token", sent_url)
        self.assertNotIn("old-token", sent_url)

    def test_resend_rejects_cross_company_invitation_before_write(self):
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.invite_routes.get_invite_by_id", return_value=None) as scoped_get, \
             patch("app.routes.invite_routes.update_invite_for_company") as scoped_update, \
             patch("app.services.email_service.send_invite_email") as send_email:
            response = self.client.post(
                "/api/invites/resend",
                headers=self.headers,
                json={"invite_id": 99},
            )

        self.assertEqual(response.status_code, 404)
        scoped_get.assert_called_once_with(99, 42)
        scoped_update.assert_not_called()
        send_email.assert_not_called()

    def test_cancel_uses_company_scoped_fetch_and_delete(self):
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.invite_routes.get_invite_by_id", return_value={"id": 7, "status": "pending"}) as scoped_get, \
             patch("app.routes.invite_routes.delete_invite", return_value={"id": 7}) as scoped_delete:
            response = self.client.delete("/api/invites/7", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        scoped_get.assert_called_once_with(7, 42)
        scoped_delete.assert_called_once_with(7, 42)

    def test_unexpected_create_error_is_sanitized(self):
        auth, user = self.auth(ADMIN)
        with auth, user, \
             patch("app.routes.invite_routes.get_user_by_email", return_value=None), \
             patch("app.routes.invite_routes.get_pending_invite_by_email", return_value=None), \
             patch("app.routes.invite_routes.can_add_team_member", return_value=True), \
             patch("app.routes.invite_routes.create_invite", side_effect=RuntimeError("secret database detail")):
            response = self.client.post(
                "/api/invites",
                headers=self.headers,
                json={"email": "new@example.test", "role": "member"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["message"], "Unable to create invitation.")
        self.assertNotIn("secret database detail", response.get_data(as_text=True))


class WorkspaceServiceTests(unittest.TestCase):
    def test_summary_uses_only_lightweight_team_dependencies(self):
        with patch(
            "app.services.workspace_service.get_company_by_id",
            return_value={"id": 42, "company_name": "Acme", "contact_email": "contact@acme.test", "contact_phone": "+60123456789"},
        ) as company, patch(
            "app.services.workspace_service.count_active_users_by_company",
            return_value=2,
        ) as active_users, patch(
            "app.services.workspace_service.count_valid_pending_invitations",
            return_value=1,
        ) as pending_invites, patch(
            "app.services.workspace_service.get_current_subscription",
            return_value={"plan": {"team_member_limit": 5}},
        ) as subscription, patch(
            "app.services.billing_service.get_company_usage",
            side_effect=RuntimeError("unrelated chatbot usage failed"),
        ) as full_usage:
            result = get_workspace_summary(42, ADMIN)

        company.assert_called_once_with(42)
        active_users.assert_called_once_with(42)
        pending_invites.assert_called_once_with(42)
        subscription.assert_called_once_with(42)
        full_usage.assert_not_called()
        self.assertEqual(result["current_user_role"], "admin")
        self.assertEqual(result["active_member_count"], 2)
        self.assertEqual(result["pending_invitation_count"], 1)
        self.assertEqual(result["plan_member_limit"], 5)
        self.assertEqual(result["remaining_seats"], 2)

    @patch("app.services.workspace_service.get_workspace_summary", return_value=WORKSPACE)
    @patch("app.services.workspace_service.update_company")
    def test_company_contact_update_is_normalized_and_never_updates_user_email(self, update, _summary):
        original_email = ADMIN["email"]
        update_workspace_company(42, ADMIN, {"company_name": " Acme Two ", "contact_email": " CONTACT@ACME.TEST ", "contact_phone": " +60 12 "})
        update.assert_called_once_with(42, {"company_name": "Acme Two", "contact_email": "contact@acme.test", "contact_phone": "+60 12"})
        self.assertEqual(ADMIN["email"], original_email)

    def test_member_service_update_is_rejected_before_repository_write(self):
        with patch("app.services.workspace_service.update_company") as update:
            with self.assertRaises(PermissionError):
                update_workspace_company(42, MEMBER, {"company_name": "Nope", "contact_email": "nope@test.test"})
        update.assert_not_called()


class UserRepositoryTests(unittest.TestCase):
    def test_active_user_count_uses_exact_head_query_scoped_by_company_and_status(self):
        table = MagicMock()
        select_query = MagicMock()
        company_filter = MagicMock()
        status_filter = MagicMock()
        table.select.return_value = select_query
        select_query.eq.return_value = company_filter
        company_filter.eq.return_value = status_filter
        status_filter.execute.return_value.count = 3

        with patch("app.database.user_repository.supabase") as supabase:
            supabase.table.return_value = table
            result = count_active_users_by_company(42)

        table.select.assert_called_once_with("id", count="exact", head=True)
        select_query.eq.assert_called_once_with("company_id", 42)
        company_filter.eq.assert_called_once_with("status", "active")
        self.assertEqual(result, 3)

    def test_active_user_count_requires_company_and_never_returns_negative(self):
        with self.assertRaises(ValueError):
            count_active_users_by_company(None)

        table = MagicMock()
        table.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = -2
        with patch("app.database.user_repository.supabase") as supabase:
            supabase.table.return_value = table
            self.assertEqual(count_active_users_by_company(42), 0)

    def test_company_scoped_update_filters_by_user_and_company(self):
        table = MagicMock()
        update_query = MagicMock()
        user_filter = MagicMock()
        company_filter = MagicMock()
        table.update.return_value = update_query
        update_query.eq.return_value = user_filter
        user_filter.eq.return_value = company_filter
        company_filter.execute.return_value.data = [{"id": 7, "company_id": 42, "role": "admin"}]

        with patch("app.database.user_repository.supabase") as supabase:
            supabase.table.return_value = table
            result = update_user_for_company(7, 42, {"role": "admin"})

        update_query.eq.assert_called_once_with("id", 7)
        user_filter.eq.assert_called_once_with("company_id", 42)
        self.assertEqual(result["company_id"], 42)


class InvitationRepositoryTests(unittest.TestCase):
    def _pending_query(self, rows):
        table = MagicMock()
        email_filter = MagicMock()
        company_filter = MagicMock()
        status_filter = MagicMock()
        ordered_query = MagicMock()
        table.select.return_value = email_filter
        email_filter.eq.return_value = company_filter
        company_filter.eq.return_value = status_filter
        status_filter.eq.return_value.order.return_value = ordered_query
        ordered_query.execute.return_value.data = rows
        return table, status_filter.eq.return_value

    def test_pending_duplicate_lookup_only_returns_unexpired_invitation(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        rows = [
            {"id": 1, "status": "pending", "expires_at": "2020-01-01T00:00:00+00:00"},
            {"id": 2, "status": "pending", "expires_at": None},
            {"id": 3, "status": "pending", "expires_at": "not-a-date"},
            {"id": 4, "status": "pending", "expires_at": future},
        ]
        table, pending_query = self._pending_query(rows)
        with patch("app.database.invite_repository.supabase") as supabase:
            supabase.table.return_value = table
            result = get_pending_invite_by_email(" USER@Example.Test ", 42)

        self.assertEqual(result["id"], 4)
        table.select.return_value.eq.assert_called_once_with("email", "user@example.test")
        pending_query.order.assert_called_once_with("id", desc=True)

    def test_expired_missing_and_malformed_pending_expiry_do_not_block_replacement(self):
        rows = [
            {"id": 1, "status": "pending", "expires_at": "2020-01-01T00:00:00+00:00"},
            {"id": 2, "status": "pending", "expires_at": None},
            {"id": 3, "status": "pending", "expires_at": "not-a-date"},
        ]
        table, pending_query = self._pending_query(rows)
        with patch("app.database.invite_repository.supabase") as supabase:
            supabase.table.return_value = table
            result = get_pending_invite_by_email("user@example.test", 42)

        self.assertIsNone(result)
        pending_query.order.assert_called_once_with("id", desc=True)

    def test_pending_lookup_returns_newest_row_when_expiry_is_not_required(self):
        rows = [
            {"id": 9, "status": "pending", "expires_at": "not-a-date"},
            {"id": 7, "status": "pending", "expires_at": "2020-01-01T00:00:00+00:00"},
        ]
        table, pending_query = self._pending_query(rows)
        with patch("app.database.invite_repository.supabase") as supabase:
            supabase.table.return_value = table
            result = get_pending_invite_by_email(
                "user@example.test",
                42,
                valid_only=False,
            )

        self.assertEqual(result["id"], 9)
        pending_query.order.assert_called_once_with("id", desc=True)

    def test_invitation_fetch_update_and_delete_filter_by_id_and_company(self):
        with self.subTest("fetch"):
            table = MagicMock()
            id_filter = MagicMock()
            company_filter = MagicMock()
            table.select.return_value.eq.return_value = id_filter
            id_filter.eq.return_value = company_filter
            company_filter.limit.return_value.execute.return_value.data = [{"id": 7, "company_id": 42}]
            with patch("app.database.invite_repository.supabase") as supabase:
                supabase.table.return_value = table
                get_invite_by_id(7, 42)
            table.select.return_value.eq.assert_called_once_with("id", 7)
            id_filter.eq.assert_called_once_with("company_id", 42)

        with self.subTest("update"):
            table = MagicMock()
            update_query = MagicMock()
            id_filter = MagicMock()
            company_filter = MagicMock()
            table.update.return_value = update_query
            update_query.eq.return_value = id_filter
            id_filter.eq.return_value = company_filter
            company_filter.execute.return_value.data = [{"id": 7, "company_id": 42}]
            with patch("app.database.invite_repository.supabase") as supabase:
                supabase.table.return_value = table
                update_invite_for_company(7, 42, {"token": "new"})
            update_query.eq.assert_called_once_with("id", 7)
            id_filter.eq.assert_called_once_with("company_id", 42)

        with self.subTest("delete"):
            table = MagicMock()
            delete_query = MagicMock()
            id_filter = MagicMock()
            company_filter = MagicMock()
            table.delete.return_value = delete_query
            delete_query.eq.return_value = id_filter
            id_filter.eq.return_value = company_filter
            company_filter.execute.return_value.data = [{"id": 7, "company_id": 42}]
            with patch("app.database.invite_repository.supabase") as supabase:
                supabase.table.return_value = table
                delete_invite(7, 42)
            delete_query.eq.assert_called_once_with("id", 7)
            id_filter.eq.assert_called_once_with("company_id", 42)

    def test_tenant_repository_operations_require_company_id(self):
        with self.assertRaises(ValueError):
            get_invite_by_id(7, None)
        with self.assertRaises(ValueError):
            update_invite_for_company(7, None, {"token": "new"})
        with self.assertRaises(ValueError):
            delete_invite(7, None)


class TeamFrontendRegressionTests(unittest.TestCase):
    def test_owner_rows_are_rendered_without_management_controls(self):
        # Behaviour lives in assets/js/team.js now; the browser-level proof is
        # in tests/browser/team.spec.js. This keeps the rule pinned cheaply.
        source = open("frontend/assets/js/team.js", encoding="utf-8").read()
        self.assertIn('var isOwner = normalizedRole === "owner";', source)
        self.assertIn("if (state.canManage && !isSelf && !isOwner)", source)
        # Owner must never be offered as a selectable role: the API rejects it.
        self.assertNotIn('value = "owner"', source)
        self.assertNotIn('["owner",', source)

    def test_team_table_and_action_styles_are_well_formed(self):
        css = open("frontend/assets/css/team.css", encoding="utf-8").read()
        html = page_source_path("team.html").read_text(encoding="utf-8")

        # The roster styles live in the extracted stylesheet.
        self.assertIn(".team-role-select", css)
        self.assertIn(".team-person", css)

        # The table head is well formed and every column is labelled, so the
        # Actions column is not an unnamed header to a screen reader.
        head = html[html.index("<thead>"):html.index("</thead>")]
        self.assertEqual(head.count("<tr>"), 1)
        self.assertEqual(head.count('scope="col"'), 5)
        self.assertIn("kw-visually-hidden", head)

class InvitationAcceptanceTests(unittest.TestCase):
    def make_google_client(self):
        staff_lookup = patch("app.database.platform_admin_repository.get_platform_admin_by_user_id", return_value=None)
        staff_lookup.start()
        self.addCleanup(staff_lookup.stop)
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()

    def google_token_response(self, **overrides):
        payload = {
            "aud": "configured-google-client",
            "email": "new@example.com",
            "email_verified": "true",
            "name": "New User",
            "sub": "google-id",
        }
        payload.update(overrides)
        google_response = MagicMock(status_code=200)
        google_response.json.return_value = payload
        return google_response

    def valid_invite(self, **overrides):
        invite = {
            "id": 7,
            "company_id": 42,
            "email": "new@example.com",
            "role": "member",
            "status": "pending",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        invite.update(overrides)
        return invite

    @patch("app.services.billing_guard.count_valid_pending_invitations", return_value=0)
    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.billing_guard._resolve_company_subscription")
    def test_malformed_pending_expiry_does_not_consume_team_seat(self, subscription, usage, pending):
        subscription.return_value = {"plan": {"team_member_limit": 2}}
        usage.return_value = {"usage": {"team_members": {"used": 1, "pending_invitations": 1}}}
        self.assertTrue(can_add_team_member(42))
        pending.assert_called_once_with(42)

    @patch("app.services.billing_guard.count_valid_pending_invitations", return_value=1)
    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.billing_guard._resolve_company_subscription")
    def test_valid_pending_invitation_consumes_team_seat(self, subscription, usage, pending):
        subscription.return_value = {"plan": {"team_member_limit": 2}}
        usage.return_value = {"usage": {"team_members": {"used": 1, "pending_invitations": 1}}}
        with self.assertRaises(BillingLimitError):
            can_add_team_member(42)
        pending.assert_called_once_with(42)

    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.billing_guard.count_valid_pending_invitations", return_value=1)
    @patch("app.services.billing_guard._resolve_company_subscription")
    def test_reserved_pending_seat_can_be_accepted_at_exact_limit(self, subscription, _pending, usage):
        subscription.return_value = {"plan": {"team_member_limit": 2}}
        usage.return_value = {"usage": {"team_members": {"used": 1, "pending_invitations": 1}}}
        self.assertTrue(can_accept_team_invitation(42))

    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.billing_guard.count_valid_pending_invitations", return_value=1)
    @patch("app.services.billing_guard._resolve_company_subscription")
    def test_acceptance_rejects_when_company_is_already_over_limit(self, subscription, _pending, usage):
        subscription.return_value = {"plan": {"team_member_limit": 2}}
        usage.return_value = {"usage": {"team_members": {"used": 2, "pending_invitations": 1}}}
        with self.assertRaises(BillingLimitError):
            can_accept_team_invitation(42)

    @patch("app.services.invitation_service.update_invite")
    @patch("app.services.invitation_service.create_user")
    @patch("app.services.invitation_service.can_accept_team_invitation", return_value=True)
    @patch("app.services.invitation_service.get_user_by_email", return_value=None)
    @patch("app.services.invitation_service.get_valid_pending_invitation")
    def test_acceptance_uses_invitation_company_without_creating_company(self, invite, _existing, _guard, create_user, update_invite):
        invite.return_value = self.valid_invite()
        create_user.return_value = {"id": 9, "company_id": 42, "email": "new@example.com", "role": "member"}
        result = accept_pending_invitation("token", "New User", "hash")
        self.assertEqual(result["company_id"], 42)
        self.assertEqual(create_user.call_args.kwargs["company_id"], 42)
        update_invite.assert_called_once_with("token", 42, {
            "status": "accepted",
            "accepted_at": update_invite.call_args.args[2]["accepted_at"],
        })

    def test_acceptance_rejects_invalid_invitation_data_before_user_creation(self):
        invalid_invites = [
            self.valid_invite(company_id=True),
            self.valid_invite(company_id=0),
            self.valid_invite(company_id="42"),
            self.valid_invite(email="   "),
            self.valid_invite(role="owner"),
            self.valid_invite(role="superadmin"),
            self.valid_invite(role="Admin"),
            self.valid_invite(status="accepted"),
            self.valid_invite(expires_at=None),
            self.valid_invite(expires_at="not-a-date"),
            self.valid_invite(expires_at="2020-01-01T00:00:00+00:00"),
        ]
        for invalid_invite in invalid_invites:
            with self.subTest(invite=invalid_invite), \
                 patch("app.services.invitation_service.get_invite_by_token", return_value=invalid_invite), \
                 patch("app.services.invitation_service.create_user") as create_user:
                with self.assertRaises(InvitationValidationError):
                    get_valid_pending_invitation("token")
                create_user.assert_not_called()

    def test_acceptance_normalizes_email_and_rejects_verified_email_mismatch(self):
        invite = self.valid_invite(email=" Invited@Example.Test ")
        with patch("app.services.invitation_service.get_valid_pending_invitation", return_value=invite), \
             patch("app.services.invitation_service.get_user_by_email") as existing_user, \
             patch("app.services.invitation_service.create_user") as create_user:
            with self.assertRaises(InvitationValidationError) as error:
                accept_pending_invitation(
                    "token",
                    "Invited User",
                    password_hash=None,
                    verified_email="different@example.test",
                )

        self.assertEqual(error.exception.status_code, 403)
        existing_user.assert_not_called()
        create_user.assert_not_called()

    def test_google_invitation_path_does_not_create_a_company(self):
        client = self.make_google_client()
        google_response = self.google_token_response(email="invited@example.com", name="Invited User")
        invited_user = {"id": 8, "company_id": 42, "email": "invited@example.com", "role": "member", "full_name": "Invited User"}
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.accept_pending_invitation", return_value=invited_user) as accept, \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_auth_token", return_value="jwt"):
            response = client.post("/api/auth/google", json={"credential": "google-token", "invite_token": "invite-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["company_id"], 42)
        accept.assert_called_once_with("invite-token", "Invited User", password_hash=None, verified_email="invited@example.com")
        create_company.assert_not_called()

    def test_google_existing_user_signs_in_without_password_fields(self):
        client = self.make_google_client()
        google_response = self.google_token_response(email="existing@example.com")
        existing_user = {
            "id": 7,
            "company_id": 42,
            "email": "existing@example.com",
            "role": "admin",
            "status": "active",
            "full_name": "Existing User",
            "password_hash": None,
        }
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=existing_user), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user, \
             patch("app.routes.auth_routes.create_auth_token", return_value="jwt"):
            response = client.post("/api/auth/google", json={"credential": "google-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        self.assertEqual(response.get_json()["token"], "jwt")
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_existing_password_user_signs_in_without_password_fields(self):
        client = self.make_google_client()
        google_response = self.google_token_response(email="password@example.com")
        existing_user = {
            "id": 8,
            "company_id": 42,
            "email": "password@example.com",
            "role": "member",
            "status": "active",
            "full_name": "Password User",
            "password_hash": generate_password_hash("StrongPass1!"),
        }
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=existing_user), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user, \
             patch("app.routes.auth_routes.create_auth_token", return_value="jwt"):
            response = client.post("/api/auth/google", json={"credential": "google-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_new_user_without_completion_fields_needs_company_without_creation(self):
        client = self.make_google_client()
        google_response = self.google_token_response()
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user:
            response = client.post("/api/auth/google", json={"credential": "google-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "needs_company")
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_new_user_with_company_only_is_not_created(self):
        client = self.make_google_client()
        google_response = self.google_token_response()
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user:
            response = client.post(
                "/api/auth/google",
                json={"credential": "google-token", "company_name": "Acme"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "needs_company")
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_new_user_missing_confirm_password_is_not_created(self):
        client = self.make_google_client()
        google_response = self.google_token_response()
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user:
            response = client.post(
                "/api/auth/google",
                json={
                    "credential": "google-token",
                    "company_name": "Acme",
                    "password": "StrongPass1!",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "needs_company")
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_new_user_password_mismatch_is_rejected_without_creation(self):
        client = self.make_google_client()
        google_response = self.google_token_response()
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user:
            response = client.post(
                "/api/auth/google",
                json={
                    "credential": "google-token",
                    "company_name": "Acme",
                    "password": "StrongPass1!",
                    "confirm_password": "DifferentPass1!",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("match", response.get_json()["message"].lower())
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_new_user_weak_password_is_rejected_without_creation(self):
        client = self.make_google_client()
        google_response = self.google_token_response()
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user:
            response = client.post(
                "/api/auth/google",
                json={
                    "credential": "google-token",
                    "company_name": "Acme",
                    "password": "weak",
                    "confirm_password": "weak",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Password must", response.get_json()["message"])
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_new_user_valid_completion_hashes_password(self):
        client = self.make_google_client()
        google_response = self.google_token_response(email="new@example.com")
        company = {"id": 42, "company_name": "Acme"}
        user = {"id": 9, "company_id": 42, "email": "new@example.com", "role": "admin", "full_name": "New User"}
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.generate_password_hash", return_value="hashed-password") as hash_password, \
             patch("app.routes.auth_routes.create_company", return_value=company), \
             patch("app.routes.auth_routes.create_user", return_value=user) as create_user, \
             patch("app.routes.auth_routes.ensure_default_company_subscription"), \
             patch("app.routes.auth_routes.create_auth_token", return_value="jwt"):
            response = client.post(
                "/api/auth/google",
                json={
                    "credential": "google-token",
                    "company_name": "Acme",
                    "password": "StrongPass1!",
                    "confirm_password": "StrongPass1!",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        hash_password.assert_called_once_with("StrongPass1!")
        self.assertEqual(create_user.call_args.kwargs["password_hash"], "hashed-password")
        self.assertNotEqual(create_user.call_args.kwargs["password_hash"], "StrongPass1!")

    def test_google_generated_password_hash_works_with_existing_password_checker(self):
        from app.routes.auth_routes import is_password_valid

        password = "StrongPass1!"
        password_hash = generate_password_hash(password)
        self.assertNotEqual(password_hash, password)
        self.assertTrue(is_password_valid(password_hash, password))

    def test_invalid_google_credential_cannot_create_account_with_password_fields(self):
        client = self.make_google_client()
        google_response = MagicMock(status_code=401)
        google_response.json.return_value = {"error_description": "Invalid Value"}
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.create_user") as create_user:
            response = client.post(
                "/api/auth/google",
                json={
                    "credential": "bad-google-token",
                    "company_name": "Acme",
                    "password": "StrongPass1!",
                    "confirm_password": "StrongPass1!",
                },
            )

        self.assertEqual(response.status_code, 401)
        create_company.assert_not_called()
        create_user.assert_not_called()

    def test_google_auth_fails_closed_when_client_id_is_missing(self):
        client = self.make_google_client()
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}), \
             patch("requests.get") as google_request:
            response = client.post("/api/auth/google", json={"credential": "google-token"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["message"], "Authentication is not configured properly.")
        google_request.assert_not_called()

    def test_google_auth_rejects_incorrect_audience(self):
        client = self.make_google_client()
        google_response = MagicMock(status_code=200)
        google_response.json.return_value = {
            "aud": "wrong-client",
            "email": "invited@example.com",
            "email_verified": "true",
        }
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.accept_pending_invitation") as accept:
            response = client.post(
                "/api/auth/google",
                json={"credential": "google-token", "invite_token": "invite-token"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("audience", response.get_json()["message"].lower())
        accept.assert_not_called()

    def test_google_auth_rejects_unverified_email(self):
        client = self.make_google_client()
        google_response = MagicMock(status_code=200)
        google_response.json.return_value = {
            "aud": "configured-google-client",
            "email": "invited@example.com",
            "email_verified": "false",
        }
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.accept_pending_invitation") as accept:
            response = client.post(
                "/api/auth/google",
                json={"credential": "google-token", "invite_token": "invite-token"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("not verified", response.get_json()["message"].lower())
        accept.assert_not_called()

    def test_google_invitation_rejects_email_mismatch(self):
        client = self.make_google_client()
        google_response = MagicMock(status_code=200)
        google_response.json.return_value = {
            "aud": "configured-google-client",
            "email": "different@example.com",
            "email_verified": "true",
            "name": "Different User",
        }
        mismatch = InvitationValidationError(
            "The Google account email does not match this invitation.",
            403,
        )
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "configured-google-client"}), \
             patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.accept_pending_invitation", side_effect=mismatch) as accept, \
             patch("app.routes.auth_routes.create_company") as create_company:
            response = client.post(
                "/api/auth/google",
                json={"credential": "google-token", "invite_token": "invite-token"},
            )

        self.assertEqual(response.status_code, 403)
        accept.assert_called_once_with(
            "invite-token",
            "Different User",
            password_hash=None,
            verified_email="different@example.com",
        )
        create_company.assert_not_called()


if __name__ == "__main__":
    unittest.main()
