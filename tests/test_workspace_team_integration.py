import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8000")
os.environ.setdefault("FLASK_DEBUG", "1")
os.environ.setdefault("RATELIMIT_ENABLED", "false")

from app import create_app
from app.services.invitation_service import accept_pending_invitation
from app.services.workspace_service import get_workspace_summary, update_workspace_company
from app.services.billing_guard import BillingLimitError, can_accept_team_invitation
from app.database.user_repository import update_user_for_company


ADMIN = {"id": 1, "company_id": 42, "email": "admin@example.com", "role": "admin", "status": "active"}
MEMBER = {"id": 2, "company_id": 42, "email": "member@example.com", "role": "member", "status": "active"}
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
            patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": user["id"], "company_id": jwt_company, "role": jwt_role}),
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
             patch("app.routes.invite_routes.can_add_team_member", side_effect=limit_error), \
             patch("app.routes.invite_routes.create_invite") as create_invite:
            response = self.client.post("/api/invites", headers=self.headers, json={"email": "new@example.com", "role": "member"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "team_member_limit")
        create_invite.assert_not_called()


class WorkspaceServiceTests(unittest.TestCase):
    @patch("app.services.workspace_service.get_company_usage")
    @patch("app.services.workspace_service.get_company_by_id")
    def test_summary_reports_role_counts_limit_and_remaining_seats(self, company, usage):
        company.return_value = {"id": 42, "company_name": "Acme", "contact_email": "contact@acme.test", "contact_phone": "+60123456789"}
        usage.return_value = {"usage": {"team_members": {"used": 2, "pending_invitations": 1, "limit": 5}}}
        result = get_workspace_summary(42, ADMIN)
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


class TeamFrontendRegressionTests(unittest.TestCase):
    def test_owner_rows_are_rendered_without_management_controls(self):
        source = open("frontend/team.html", encoding="utf-8").read()
        self.assertIn('var isOwner = normalizedRole === "owner";', source)
        self.assertIn("if (isAdminView && !isCurrentUser && !isOwner)", source)
        self.assertNotIn('<option value=\\"owner\\"', source)

    def test_team_table_and_action_styles_are_well_formed(self):
        source = open("frontend/team.html", encoding="utf-8").read()
        actions_start = source.index(".team-actions-wrap {")
        actions_end = source.index("}", actions_start)
        role_start = source.index(".team-role-select {")
        self.assertLess(actions_end, role_start)
        header = source[source.index('<table class="team-table"'):source.index('<tbody id="team-tbody">')]
        self.assertIn("</tr>", header)


class InvitationAcceptanceTests(unittest.TestCase):
    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.billing_guard._resolve_company_subscription")
    def test_reserved_pending_seat_can_be_accepted_at_exact_limit(self, subscription, usage):
        subscription.return_value = {"plan": {"team_member_limit": 2}}
        usage.return_value = {"usage": {"team_members": {"used": 1, "pending_invitations": 1}}}
        self.assertTrue(can_accept_team_invitation(42))

    @patch("app.services.billing_guard.get_company_usage")
    @patch("app.services.billing_guard._resolve_company_subscription")
    def test_acceptance_rejects_when_company_is_already_over_limit(self, subscription, usage):
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
        invite.return_value = {"company_id": 42, "email": "new@example.com", "role": "member", "status": "pending"}
        create_user.return_value = {"id": 9, "company_id": 42, "email": "new@example.com", "role": "member"}
        result = accept_pending_invitation("token", "New User", "hash")
        self.assertEqual(result["company_id"], 42)
        self.assertEqual(create_user.call_args.kwargs["company_id"], 42)
        update_invite.assert_called_once()

    def test_google_invitation_path_does_not_create_a_company(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        google_response = MagicMock(status_code=200)
        google_response.json.return_value = {"aud": os.getenv("GOOGLE_CLIENT_ID", ""), "email": "invited@example.com", "email_verified": "true", "name": "Invited User", "sub": "google-id"}
        invited_user = {"id": 8, "company_id": 42, "email": "invited@example.com", "role": "member", "full_name": "Invited User"}
        with patch("requests.get", return_value=google_response), \
             patch("app.routes.auth_routes.get_user_by_email", return_value=None), \
             patch("app.routes.auth_routes.accept_pending_invitation", return_value=invited_user) as accept, \
             patch("app.routes.auth_routes.create_company") as create_company, \
             patch("app.routes.auth_routes.jwt.encode", return_value="jwt"):
            response = client.post("/api/auth/google", json={"credential": "google-token", "invite_token": "invite-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["company_id"], 42)
        accept.assert_called_once_with("invite-token", "Invited User", password_hash=None, verified_email="invited@example.com")
        create_company.assert_not_called()


if __name__ == "__main__":
    unittest.main()
