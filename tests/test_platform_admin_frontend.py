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
    FRONTEND / "platform-admin-support.html",
    FRONTEND / "platform-admin-audit-events.html",
]
API = FRONTEND / "assets" / "js" / "platform-admin-api.js"
SHELL = FRONTEND / "assets" / "js" / "platform-admin-shell.js"
DASHBOARD = FRONTEND / "assets" / "js" / "platform-admin-dashboard.js"
COMPANIES = FRONTEND / "assets" / "js" / "platform-admin-companies.js"
COMPANY = FRONTEND / "assets" / "js" / "platform-admin-company.js"
SUPPORT = FRONTEND / "assets" / "js" / "platform-admin-support.js"
AUDIT_EVENTS = FRONTEND / "assets" / "js" / "platform-admin-audit-events.js"
CSS = FRONTEND / "assets" / "css" / "platform-admin.css"
SIDEBAR = FRONTEND / "sidebar-component.js"
TENANT_SUPPORT = FRONTEND / "support.html"


def read(path):
    return path.read_text(encoding="utf-8", errors="strict")


class TestPlatformAdminPageGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {path.name: read(path) for path in PAGES}
        cls.shell = read(SHELL)
        cls.controllers = [read(DASHBOARD), read(COMPANIES), read(COMPANY), read(SUPPORT), read(AUDIT_EVENTS)]

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
            "platform-admin-support.html": "platform-admin-support.js",
            "platform-admin-audit-events.html": "platform-admin-audit-events.js",
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
            "Support",
            "Audit Logs",
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

    def test_public_client_exposes_only_twelve_approved_methods(self):
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
                "getOverview",
                "listCompanies",
                "listAuditEvents",
                "getCompany",
                "getCompanySubscription",
                "listCompanySubscriptionHistory",
                "getCompanyAiCreditUsage",
                "listCompanyAiCreditTransactions",
                "listCompanyBillingOrders",
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

    def test_audit_event_client_uses_only_approved_filters(self):
        function = re.search(
            r"function listAuditEvents\(options\) \{(.*?)\n    \}",
            self.api,
            flags=re.S,
        ).group(1)
        for key in [
            "limit",
            "offset",
            "action",
            "resource_type",
            "actor_user_id",
            "resource_id",
            "created_after",
            "created_before",
        ]:
            self.assertIn(key, function)
        for forbidden in ["metadata", "search", "sort_by", "export", "download"]:
            self.assertNotIn(forbidden, function)
        self.assertIn('platformFetch("/audit-events?"', function)

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
            "listCompanySubscriptionHistory",
            "getCompanyAiCreditUsage",
            "listCompanyAiCreditTransactions",
            "listCompanyBillingOrders",
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
        cls.support = read(SUPPORT)
        cls.audit_events = read(AUDIT_EVENTS)

    def test_tenant_support_remains_tenant_facing_static_help(self):
        page = read(TENANT_SUPPORT)
        self.assertIn("<h1>Support</h1>", page)
        self.assertIn("Direct support contact is not configured yet.", page)
        self.assertIn("<chatbot-sidebar></chatbot-sidebar>", page)
        self.assertIn("requireLogin();", page)
        self.assertNotIn("Platform Administration", page)
        self.assertNotIn("PlatformAdminShell", page)
        self.assertNotIn("/api/platform-admin", page)

    def test_dashboard_uses_single_operations_overview_request(self):
        self.assertEqual(self.dashboard.count("PlatformAdminApi.getOverview({"), 1)
        self.assertNotIn("PlatformAdminApi.listCompanies({", self.dashboard)
        self.assertIn('ui.runRequest("operations-overview"', self.dashboard)
        self.assertIn("Platform operations", self.dashboard)
        self.assertIn("Read-only overview of tenant and subscription health", self.dashboard)
        self.assertIn("Operational alerts", self.dashboard)
        self.assertIn("No operational alerts found.", self.dashboard)
        self.assertIn("subscription_past_due", self.dashboard)
        self.assertIn("subscription_expired", self.dashboard)
        self.assertIn("Critical alerts", self.dashboard)
        self.assertIn("Warning alerts", self.dashboard)
        self.assertIn("Companies requiring attention", self.dashboard)
        self.assertIn("platform-admin-company.html?", self.dashboard)
        self.assertIn("Number.isSafeInteger(company.company_id)", self.dashboard)
        api_source = read(API)
        self.assertIn('return platformFetch("/overview"', api_source)
        self.assertNotIn("listOperationalAlerts", api_source)
        for forbidden in [
            "PlatformAdminApi.listCompanies({",
            "innerHTML",
            "JSON.stringify",
            "Reconcile",
            "Retry payment",
            "Activate",
            "Change plan",
            "Credit manually",
            "Checkout",
            "Payment link",
            "Message tenant",
            "Create ticket",
            "Export",
            "Download",
            "Chart",
        ]:
            self.assertNotIn(forbidden, self.dashboard)

    def test_support_workspace_reuses_only_overview_and_company_directory(self):
        self.assertIn("Support Workspace", read(FRONTEND / "platform-admin-support.html"))
        self.assertIn("PlatformAdminShell.start({ onAuthorized: initializeSupportWorkspace })", self.support)
        self.assertIn('ui.runRequest("support-overview"', self.support)
        self.assertIn("PlatformAdminApi.getOverview({ signal: signal })", self.support)
        self.assertIn('ui.runRequest("support-company-lookup"', self.support)
        self.assertIn("PlatformAdminApi.listCompanies({", self.support)
        for forbidden_call in [
            "PlatformAdminApi.getCompany(",
            "PlatformAdminApi.getCompanySubscription(",
            "PlatformAdminApi.listCompanySubscriptionHistory(",
            "PlatformAdminApi.getCompanyAiCreditUsage(",
            "PlatformAdminApi.listCompanyAiCreditTransactions(",
            "PlatformAdminApi.listCompanyUsers(",
            "PlatformAdminApi.listCompanyChatbots(",
        ]:
            self.assertNotIn(forbidden_call, self.support)
        self.assertIn("platform-admin-company.html?", self.support)

    def test_support_workspace_is_read_only_and_has_safe_states(self):
        for marker in [
            "Read-only tenant investigation",
            "does not submit tickets",
            "Loading support workspace...",
            "No companies currently require attention.",
            "No company search results found.",
            "Company lookup is temporarily unavailable.",
            "Search companies",
            "Investigate",
        ]:
            self.assertIn(marker, self.support)
        for forbidden in [
            "ticket",
            "case notes",
            "Assign",
            "Impersonate",
            "Reset Password",
            "Suspend",
            "Reactivate",
            "Adjust Credit",
            "Reconcile",
            "Checkout",
            "Payment link",
            "Export",
        ]:
            if forbidden == "ticket":
                self.assertIn("does not submit tickets", self.support)
            else:
                self.assertNotIn(forbidden, self.support)

    def test_audit_log_viewer_uses_shell_client_and_safe_metadata_summary(self):
        self.assertIn("Audit Logs", read(FRONTEND / "platform-admin-audit-events.html"))
        self.assertIn("PlatformAdminShell.start({ onAuthorized: initializeAuditLogViewer })", self.audit_events)
        self.assertIn('ui.runRequest("audit-events"', self.audit_events)
        self.assertIn("PlatformAdminApi.listAuditEvents({", self.audit_events)
        self.assertIn("Read-only platform-admin activity history", self.audit_events)
        self.assertIn("does not expose raw metadata or tenant records", self.audit_events)
        self.assertIn("Safe metadata summary", self.audit_events)
        self.assertIn("METADATA_KEYS", self.audit_events)
        self.assertNotIn("JSON.stringify", self.audit_events)
        self.assertNotIn("textarea", self.audit_events)
        for forbidden in [
            "Export",
            "Download",
            "Delete audit",
            "Edit audit",
            "Platform Admin Mapping",
            "metadata search",
        ]:
            self.assertNotIn(forbidden, self.audit_events)

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
        self.assertIn("PlatformAdminApi.listCompanySubscriptionHistory(companyId", self.company)
        self.assertIn("PlatformAdminApi.getCompanyAiCreditUsage(companyId", self.company)
        self.assertIn("PlatformAdminApi.listCompanyAiCreditTransactions(companyId", self.company)
        self.assertIn("PlatformAdminApi.listCompanyBillingOrders(companyId", self.company)
        self.assertIn("PlatformAdminApi.listCompanyUsers(companyId", self.company)
        self.assertIn("PlatformAdminApi.listCompanyChatbots(companyId", self.company)
        initialize = re.search(
            r"async function initializeCompanyDetail\(\) \{(.*?)\n    \}",
            self.company,
            flags=re.S,
        ).group(1)
        company_fetch = initialize.index("PlatformAdminApi.getCompany(companyId")
        subscription_fetch = initialize.index("PlatformAdminApi.getCompanySubscription(companyId")
        subscription_history_panel = initialize.index("subscriptionHistoryPanel(companyId)")
        billing_orders_panel = initialize.index("billingOrdersPanel(companyId)")
        ai_fetch = initialize.index("PlatformAdminApi.getCompanyAiCreditUsage(companyId")
        self.assertLess(company_fetch, subscription_fetch)
        self.assertLess(company_fetch, subscription_history_panel)
        self.assertLess(company_fetch, billing_orders_panel)
        self.assertLess(company_fetch, ai_fetch)

    def test_subscription_history_is_lazy_read_only_and_uses_bounded_contract(self):
        initialize = re.search(
            r"async function initializeCompanyDetail\(\) \{(.*?)\n    \}",
            self.company,
            flags=re.S,
        ).group(1)
        company_fetch = initialize.index("PlatformAdminApi.getCompany(companyId")
        history_panel = initialize.index("subscriptionHistoryPanel(companyId)")
        self.assertLess(company_fetch, history_panel)
        self.assertIn("Load subscription history", self.company)
        self.assertIn("Loading subscription history...", self.company)
        self.assertNotIn("â€¦", self.company)
        self.assertIn("Historical subscription records. This is not a complete event-level transition timeline.", self.company)
        self.assertIn('ui.runRequest("company-subscription-history"', self.company)
        self.assertIn("PlatformAdminApi.listCompanySubscriptionHistory(companyId", self.company)
        self.assertIn("All statuses", self.company)
        for status in ["trialing", "active", "past_due", "expired", "cancelled"]:
            self.assertIn(status, self.company)
        for label in [
            "Current period",
            "Trial ends",
            "Pending plan",
            "Cancellation",
            "Status updated",
            "Created",
        ]:
            self.assertIn(label, self.company)
        api_source = read(API)
        self.assertIn('"/subscription-history?"', api_source)
        self.assertIn('params.set("limit", String(config.limit))', api_source)
        self.assertIn('params.set("offset", String(config.offset))', api_source)
        self.assertIn('if (config.status) params.set("status", config.status)', api_source)
        self.assertNotIn("order_reference", self.company)
        self.assertNotIn("gateway_order_id", self.company)
        self.assertNotIn("payment_reference", self.company)

    def test_ai_credit_transactions_are_lazy_read_only_and_use_bounded_contract(self):
        initialize = re.search(
            r"async function initializeCompanyDetail\(\) \{(.*?)\n    \}",
            self.company,
            flags=re.S,
        ).group(1)
        company_fetch = initialize.index("PlatformAdminApi.getCompany(companyId")
        ai_usage_fetch = initialize.index("PlatformAdminApi.getCompanyAiCreditUsage(companyId")
        transactions_panel = initialize.index("aiCreditTransactionsPanel(companyId)")
        self.assertLess(company_fetch, transactions_panel)
        self.assertLess(ai_usage_fetch, transactions_panel)
        self.assertIn("Load AI-credit transactions", self.company)
        self.assertIn("Loading AI-credit transactions...", self.company)
        self.assertNotIn("â€¦", self.company)
        self.assertIn('ui.runRequest("company-ai-credit-transactions"', self.company)
        self.assertIn("PlatformAdminApi.listCompanyAiCreditTransactions(companyId", self.company)
        self.assertIn("All transaction types", self.company)
        for transaction_type in [
            "included_credit_grant",
            "trial_credit_grant",
            "usage_debit",
            "topup_purchase",
            "refund",
            "manual_adjustment",
            "expiry",
            "reversal",
        ]:
            self.assertIn(transaction_type, self.company)
        for label in [
            "Included delta",
            "Top-up delta",
            "Customer charge",
            "Uncovered",
            "Included balance after",
            "Top-up balance after",
            "Period",
        ]:
            self.assertIn(label, self.company)
        api_source = read(API)
        self.assertIn('"/ai-credit-transactions?"', api_source)
        self.assertIn('params.set("limit", String(config.limit))', api_source)
        self.assertIn('params.set("offset", String(config.offset))', api_source)
        self.assertIn('if (config.transactionType) params.set("transaction_type", config.transactionType)', api_source)
        for prohibited in [
            "fx_rate_micro_myr_per_usd",
            "markup_basis_points",
            "payment_reference",
            "idempotency_key",
            "ai_usage_log_id",
            "subscription_id",
            "reversal_of_transaction_id",
        ]:
            self.assertNotIn(prohibited, self.company)

    def test_billing_orders_are_lazy_read_only_and_use_bounded_contract(self):
        initialize = re.search(
            r"async function initializeCompanyDetail\(\) \{(.*?)\n    \}",
            self.company,
            flags=re.S,
        ).group(1)
        company_fetch = initialize.index("PlatformAdminApi.getCompany(companyId")
        history_panel = initialize.index("subscriptionHistoryPanel(companyId)")
        billing_orders_panel = initialize.index("billingOrdersPanel(companyId)")
        self.assertLess(company_fetch, billing_orders_panel)
        self.assertLess(history_panel, billing_orders_panel)
        self.assertIn("Load billing orders", self.company)
        self.assertIn("Loading billing orders...", self.company)
        self.assertIn('ui.runRequest("company-billing-orders"', self.company)
        self.assertIn("PlatformAdminApi.listCompanyBillingOrders(companyId", self.company)
        self.assertIn("Amounts are shown as integer sen as stored; currency is not returned or inferred.", self.company)
        self.assertIn('String(value) + " sen"', self.company)
        for label in [
            "Billing orders",
            "Status",
            "Created after",
            "Created before",
            "Amount",
            "New plan",
            "Source plan",
            "Activation status",
            "Activation type",
            "Reconciliation required",
            "Paid",
            "Credited",
            "Expires",
            "Activation claimed",
            "Activation completed",
            "Credit granted",
        ]:
            self.assertIn(label, self.company)
        api_source = read(API)
        self.assertIn('"/billing-orders?"', api_source)
        self.assertIn('params.set("limit", String(config.limit))', api_source)
        self.assertIn('params.set("offset", String(config.offset))', api_source)
        self.assertIn('if (config.status) params.set("status", config.status)', api_source)
        self.assertIn('if (config.createdAfter) params.set("created_after", config.createdAfter)', api_source)
        self.assertIn('if (config.createdBefore) params.set("created_before", config.createdBefore)', api_source)
        for forbidden in [
            "order_reference",
            "gateway_order_id",
            "checkout_url",
            "payment_reference",
            "payment_gateway",
            "idempotency_key",
            "activation_error_message",
            "last_reconciliation_error",
            "reconciliation_attempt_count",
            "subscription_id",
            "created_by_user_id",
            "RM",
            "export",
            "download",
            "reconcile",
        ]:
            self.assertNotIn(forbidden, self.company)

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
        sources = "\n".join([read(API), read(SHELL), self.dashboard, self.companies, self.company, self.support])
        self.assertNotIn("innerHTML", sources)
        self.assertIn("textContent", sources)

    def test_no_raw_error_logging_or_unsupported_routes(self):
        sources = "\n".join([read(API), read(SHELL), self.dashboard, self.companies, self.company, self.support])
        self.assertNotIn("console.", sources)
        self.assertNotIn("/api/admin/billing", sources)
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            self.assertNotIn(f'method: "{method}"', sources)

    def test_no_mutation_or_impersonation_controls_exist(self):
        pages_and_controllers = "\n".join(read(path) for path in PAGES) + self.dashboard + self.companies + self.company + self.support
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
            "Case notes",
            "Create Ticket",
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
        sources = "\n".join(read(path) for path in PAGES + [API, SHELL, DASHBOARD, COMPANIES, COMPANY, SUPPORT])
        self.assertNotIn("flow-builder", sources.lower())
        self.assertNotIn("broadcast", sources.lower())


if __name__ == "__main__":
    unittest.main()
