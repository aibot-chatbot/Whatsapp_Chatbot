"""Source-contract tests for the read-only platform-admin frontend."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PAGES = [
    FRONTEND / "platform-admin.html",
    FRONTEND / "platform-admin-companies.html",
    FRONTEND / "platform-admin-company.html",
]
API = FRONTEND / "assets" / "js" / "platform-admin-api.js"
SHELL = FRONTEND / "assets" / "js" / "platform-admin-shell.js"
DASHBOARD = FRONTEND / "assets" / "js" / "platform-admin-dashboard.js"
COMPANIES = FRONTEND / "assets" / "js" / "platform-admin-companies.js"
COMPANY = FRONTEND / "assets" / "js" / "platform-admin-company.js"
CSS = FRONTEND / "assets" / "css" / "platform-admin.css"
SIDEBAR = FRONTEND / "sidebar-component.js"


def read(path):
    return path.read_text(encoding="utf-8", errors="strict")


class TestPlatformAdminPageGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {path.name: read(path) for path in PAGES}
        cls.shell = read(SHELL)
        cls.controllers = [read(DASHBOARD), read(COMPANIES), read(COMPANY)]

    def test_all_pages_begin_in_blocking_checking_access_state(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                self.assertIn('id="platform-access-state"', html)
                self.assertIn('aria-busy="true"', html)
                self.assertIn("Checking access", html)
                self.assertIn('id="platform-app" hidden', html)

    def test_all_pages_load_auth_api_shell_then_controller(self):
        expected_controllers = {
            "platform-admin.html": "platform-admin-dashboard.js",
            "platform-admin-companies.html": "platform-admin-companies.js",
            "platform-admin-company.html": "platform-admin-company.js",
        }
        for name, html in self.pages.items():
            with self.subTest(page=name):
                auth = html.index("assets/js/auth.js")
                api = html.index("assets/js/platform-admin-api.js")
                shell = html.index("assets/js/platform-admin-shell.js")
                controller = html.index(expected_controllers[name])
                self.assertLess(auth, api)
                self.assertLess(api, shell)
                self.assertLess(shell, controller)

    def test_every_controller_enters_through_shared_authorization_gate(self):
        for source in self.controllers:
            self.assertIn("PlatformAdminShell.start({ onAuthorized:", source)
        get_me = self.shell.index("PlatformAdminApi.getMe")
        page_callback = self.shell.index("await lifecycle.onAuthorized(identity)")
        self.assertLess(get_me, page_callback)

    def test_no_tenant_role_or_forged_local_flag_can_bypass_gate(self):
        sources = "\n".join([self.shell] + self.controllers + [read(API)])
        forbidden = [
            "requireAdminOrOwner",
            'sessionStorage.getItem("user")',
            "users.role",
            "jwt_decode",
            "atob(",
            "platform_admin_claim",
            "platformAdminFlag",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, sources)
        self.assertIn('sessionStorage.getItem("token")', self.shell)

    def test_platform_state_is_not_persisted(self):
        sources = "\n".join([read(API), self.shell] + self.controllers)
        self.assertNotIn("localStorage", sources)
        self.assertNotIn("sessionStorage.setItem", sources)


class TestPlatformAdminShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = read(SHELL)
        cls.pages = "\n".join(read(path) for path in PAGES)

    def test_dedicated_shell_has_only_approved_navigation(self):
        for label in [
            "Platform Administration",
            "Internal / Read Only",
            "Dashboard",
            "Companies",
            "Return to Tenant App",
            "Logout",
        ]:
            self.assertIn(label, self.shell)
        self.assertNotIn("chatbot-sidebar", self.shell.lower())

    def test_return_to_tenant_app_points_to_bots(self):
        self.assertGreaterEqual(self.shell.count('href = "bots.html"'), 1)

    def test_access_failures_clear_state_before_fixed_screen(self):
        for category, state in [
            ("access_denied", "access_denied"),
            ("unavailable", "unavailable"),
        ]:
            branch = re.search(
                rf'if \(category === "{category}"\) \{{(.*?)\n        \}}',
                self.shell,
                flags=re.S,
            )
            self.assertIsNotNone(branch)
            body = branch.group(1)
            self.assertLess(body.index("clearPlatformState();"), body.index(f'showBlockingState("{state}")'))

    def test_unauthorized_clears_state_then_logs_out(self):
        branch = re.search(
            r'if \(category === "unauthenticated"\) \{(.*?)\n        \}',
            self.shell,
            flags=re.S,
        ).group(1)
        self.assertLess(branch.index("clearPlatformState();"), branch.index("logout();"))

    def test_request_registry_aborts_replaced_and_all_active_requests(self):
        self.assertIn("requests: new Map()", self.shell)
        self.assertIn("if (previous) previous.controller.abort();", self.shell)
        self.assertIn("entry.controller.abort();", self.shell)
        self.assertIn('window.addEventListener("pagehide", clearPlatformState)', self.shell)

    def test_epoch_prevents_late_response_from_restoring_data(self):
        self.assertIn("lifecycle.epoch += 1", self.shell)
        self.assertIn("if (requestEpoch !== lifecycle.epoch)", self.shell)
        self.assertIn("node.replaceChildren();", self.shell)

    def test_accessibility_landmarks_and_live_states_exist(self):
        for html in self.pages.split("</html>")[:-1]:
            self.assertIn("platform-skip-link", html)
            self.assertIn("<main", html)
            self.assertIn("aria-live", html)
        self.assertIn('aria-label", "Platform Administration navigation"', self.shell)


class TestPlatformAdminApiClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = read(API)
        cls.auth = read(FRONTEND / "assets" / "js" / "auth.js")

    def test_public_client_exposes_only_seven_approved_methods(self):
        exported = re.search(
            r"window\.PlatformAdminApi = Object\.freeze\(\{(.*?)\}\);",
            self.api,
            flags=re.S,
        ).group(1)
        keys = re.findall(r"^\s*([A-Za-z][A-Za-z0-9]*):", exported, flags=re.M)
        self.assertEqual(
            keys,
            [
                "getMe",
                "listCompanies",
                "getCompany",
                "getCompanySubscription",
                "getCompanyAiCreditUsage",
                "listCompanyUsers",
                "listCompanyChatbots",
            ],
        )

    def test_client_is_get_only_and_has_no_generic_public_request(self):
        self.assertIn('method: "GET"', self.api)
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            self.assertNotIn(f'method: "{method}"', self.api)
        self.assertNotIn("request: platformFetch", self.api)
        self.assertNotIn("/api/admin/billing", self.api)

    def test_bearer_token_comes_from_existing_authenticated_session_helper(self):
        self.assertIn("authenticatedFetch(API_ROOT + path", self.api)
        self.assertIn('const token = sessionStorage.getItem("token")', self.auth)
        self.assertIn('options.headers["Authorization"] = `Bearer ${token}`', self.auth)
        self.assertNotIn("token=", self.api)

    def test_company_ids_are_validated_before_any_fetch(self):
        validator = re.search(
            r"function requireCompanyId\(companyId\) \{(.*?)\n    \}",
            self.api,
            flags=re.S,
        ).group(1)
        self.assertIn("Number.isSafeInteger(companyId)", validator)
        self.assertIn("companyId <= 0", validator)
        for function_name in [
            "getCompany",
            "getCompanySubscription",
            "getCompanyAiCreditUsage",
            "listCompanyUsers",
            "listCompanyChatbots",
        ]:
            body = re.search(
                rf"function {function_name}\(companyId, options\) \{{(.*?)\n    \}}",
                self.api,
                flags=re.S,
            ).group(1)
            self.assertLess(body.index("requireCompanyId(companyId)"), body.index("platformFetch("))

    def test_fixed_error_categories_cover_required_conditions(self):
        for marker in [
            'status === 400) return "validation"',
            'status === 401) return "unauthenticated"',
            'status === 403) return "access_denied"',
            'status === 404) return "not_found"',
            'status === 503) return "unavailable"',
            'error.name === "AbortError"',
        ]:
            self.assertIn(marker, self.api)

    def test_client_does_not_log_or_return_raw_error_messages(self):
        self.assertNotIn("console.", self.api)
        self.assertNotIn("payload.message", self.api)
        self.assertNotIn("response.text", self.api)


class TestPlatformAdminPageBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = read(DASHBOARD)
        cls.companies = read(COMPANIES)
        cls.company = read(COMPANY)

    def test_dashboard_uses_three_exact_audited_count_requests(self):
        self.assertEqual(self.dashboard.count("PlatformAdminApi.listCompanies({"), 3)
        self.assertGreaterEqual(self.dashboard.count("limit: 1, offset: 0"), 3)
        self.assertIn('status: "active"', self.dashboard)
        self.assertIn('status: "inactive"', self.dashboard)
        self.assertIn("each create a platform-admin audit event", self.dashboard)

    def test_directory_debounces_aborts_and_resets_pagination(self):
        self.assertIn("}, 350);", self.companies)
        self.assertIn('ui.runRequest("company-list"', self.companies)
        self.assertGreaterEqual(self.companies.count("state.offset = 0;"), 5)
        self.assertIn("pagination.offset - pagination.limit", self.companies)
        self.assertIn("pagination.offset + pagination.limit", self.companies)

    def test_directory_uses_backend_filter_and_sort_allowlists(self):
        for marker in [
            '["", "active", "inactive"]',
            '["created_at", "company_name", "status", "id"]',
            '["asc", "desc"]',
            "[25, 50, 100]",
            "maxLength = 100",
        ]:
            self.assertIn(marker, self.companies)

    def test_directory_renders_required_read_only_fields(self):
        for label in [
            "ID",
            "Company name",
            "Business type",
            "Status",
            "Contact email",
            "Created",
            "View details",
        ]:
            self.assertIn(label, self.companies)
        self.assertIn('"aria-sort"', self.companies)

    def test_path_company_id_controls_all_detail_requests(self):
        self.assertIn('new URLSearchParams(window.location.search).get("company_id")', self.company)
        self.assertIn("PlatformAdminApi.getCompany(companyId", self.company)
        self.assertIn("PlatformAdminApi.getCompanySubscription(companyId", self.company)
        self.assertIn("PlatformAdminApi.getCompanyAiCreditUsage(companyId", self.company)
        self.assertIn("PlatformAdminApi.listCompanyUsers(companyId", self.company)
        self.assertIn("PlatformAdminApi.listCompanyChatbots(companyId", self.company)
        company_fetch = self.company.index("PlatformAdminApi.getCompany(companyId")
        subscription_fetch = self.company.index("PlatformAdminApi.getCompanySubscription(companyId")
        ai_fetch = self.company.index("PlatformAdminApi.getCompanyAiCreditUsage(companyId")
        self.assertLess(company_fetch, subscription_fetch)
        self.assertLess(company_fetch, ai_fetch)

    def test_users_and_chatbots_are_lazy_loaded_after_company_detail(self):
        initialize = re.search(
            r"async function initializeCompanyDetail\(\) \{(.*?)\n    \}",
            self.company,
            flags=re.S,
        ).group(1)
        company_fetch = initialize.index("PlatformAdminApi.getCompany(companyId")
        users_panel = initialize.index("usersPanel(companyId)")
        chatbots_panel = initialize.index("chatbotsPanel(companyId)")
        self.assertLess(company_fetch, users_panel)
        self.assertLess(company_fetch, chatbots_panel)
        self.assertIn('"Load " + config.title.toLowerCase()', self.company)
        self.assertIn('title: "Users"', self.company)
        self.assertIn('title: "Chatbots"', self.company)
        self.assertIn('operationKey: "company-users"', self.company)
        self.assertIn('operationKey: "company-chatbots"', self.company)
        api_source = read(API)
        self.assertIn('params.set("search", config.search)', api_source)
        self.assertNotIn('"search": normalized_search', self.company)

    def test_users_and_chatbots_have_read_only_safe_fields_and_filters(self):
        for marker in [
            "Search email or full name",
            "Search bot name",
            "Full name",
            "Email",
            "Role",
            "Provider",
            "Model",
            "Current",
            "Archived",
            "All",
            "bot_name",
            "created_at",
            "updated_at",
        ]:
            self.assertIn(marker, self.company)
        for forbidden in [
            "password_hash",
            "is_verified",
            "deleted_at",
            "bot_description",
            "welcome_message",
            "fallback_message",
            "temperature",
        ]:
            self.assertNotIn(forbidden, self.company)

    def test_invalid_path_id_returns_before_company_api_call(self):
        initialize = re.search(
            r"async function initializeCompanyDetail\(\) \{(.*?)\n    \}",
            self.company,
            flags=re.S,
        ).group(1)
        invalid_branch = initialize.index("if (companyId === null)")
        early_return = initialize.index("return;", invalid_branch)
        api_call = initialize.index("PlatformAdminApi.getCompany(companyId")
        self.assertLess(early_return, api_call)

    def test_detail_has_missing_subscription_and_uninitialized_credit_states(self):
        self.assertIn("No subscription recorded", self.company)
        self.assertIn("AI-credit balance not initialized", self.company)
        for status in ["active", "trialing", "past-due", "expired", "cancelled"]:
            self.assertIn(status, read(SHELL))

    def test_api_values_are_rendered_as_text_not_html(self):
        sources = "\n".join([read(API), read(SHELL), self.dashboard, self.companies, self.company])
        self.assertNotIn("innerHTML", sources)
        self.assertIn("textContent", sources)

    def test_no_raw_error_logging_or_unsupported_routes(self):
        sources = "\n".join([read(API), read(SHELL), self.dashboard, self.companies, self.company])
        self.assertNotIn("console.", sources)
        self.assertNotIn("/api/admin/billing", sources)
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            self.assertNotIn(f'method: "{method}"', sources)

    def test_no_mutation_or_impersonation_controls_exist(self):
        pages_and_controllers = "\n".join(read(path) for path in PAGES) + self.dashboard + self.companies + self.company
        for label in [
            "Change Plan",
            "Cancel Subscription",
            "Delete Company",
            "Edit Company",
            "Export Companies",
            "Impersonate",
            "Login as tenant",
            "Adjust Credit",
            "Reconcile",
            "Send Message",
        ]:
            self.assertNotIn(label, pages_and_controllers)


class TestPlatformAdminResponsiveIsolation(unittest.TestCase):
    def test_css_has_mobile_table_cards_focus_and_reduced_motion(self):
        css = read(CSS)
        for marker in [
            "@media (max-width: 900px)",
            "@media (max-width: 767px)",
            "@media (max-width: 360px)",
            ".platform-company-cards",
            ":focus-visible",
            "@media (prefers-reduced-motion: reduce)",
        ]:
            self.assertIn(marker, css)

    def test_ordinary_tenant_sidebar_has_no_platform_entry(self):
        sidebar = read(SIDEBAR).lower()
        self.assertNotIn("platform-admin", sidebar)
        self.assertNotIn("platform administration", sidebar)

    def test_flow_builder_and_broadcast_files_are_not_referenced(self):
        sources = "\n".join(read(path) for path in PAGES + [API, SHELL, DASHBOARD, COMPANIES, COMPANY])
        self.assertNotIn("flow-builder", sources.lower())
        self.assertNotIn("broadcast", sources.lower())


if __name__ == "__main__":
    unittest.main()
