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
    FRONTEND / "platform-admin-billing.html",
    FRONTEND / "platform-admin-support.html",
    FRONTEND / "platform-admin-users.html",
    FRONTEND / "platform-admin-audit-events.html",
]
API = FRONTEND / "assets" / "js" / "platform-admin-api.js"
SHELL = FRONTEND / "assets" / "js" / "platform-admin-shell.js"
DASHBOARD = FRONTEND / "assets" / "js" / "platform-admin-dashboard.js"
COMPANIES = FRONTEND / "assets" / "js" / "platform-admin-companies.js"
COMPANY = FRONTEND / "assets" / "js" / "platform-admin-company.js"
PLATFORM_BILLING = FRONTEND / "assets" / "js" / "platform-admin-billing.js"
SUPPORT = FRONTEND / "assets" / "js" / "platform-admin-support.js"
PLATFORM_ADMIN_USERS = FRONTEND / "assets" / "js" / "platform-admin-users.js"
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
        cls.controllers = [
            read(DASHBOARD),
            read(COMPANIES),
            read(COMPANY),
            read(PLATFORM_BILLING),
            read(SUPPORT),
            read(PLATFORM_ADMIN_USERS),
            read(AUDIT_EVENTS),
        ]

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
            "platform-admin-billing.html": "platform-admin-billing.js",
            "platform-admin-support.html": "platform-admin-support.js",
            "platform-admin-users.html": "platform-admin-users.js",
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
            "Internal / Controlled Access",
            "Dashboard",
            "Companies",
            "Billing",
            "Support",
            "Platform Admins",
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


class TestPlatformAdminDashboardVisualization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = read(DASHBOARD)
        cls.css = read(CSS)

    def test_dashboard_uses_existing_overview_api_without_extra_fetches(self):
        self.assertIn("PlatformAdminApi.getOverview({ signal: signal })", self.dashboard)
        self.assertNotIn("getBillingOverview", self.dashboard)
        self.assertNotIn("listCompanies(", self.dashboard)
        self.assertNotIn("platformFetch", self.dashboard)
        self.assertIn('window.PlatformAdminDashboard = Object.freeze', self.dashboard)

    def test_dashboard_has_visual_sections_for_supported_phase_6_contract(self):
        for label in (
            "Needs Attention",
            "Support Operations",
            "Messaging Health",
            "AI Usage",
            "Billing Health",
            "Companies requiring attention",
            "Platform Admin Activity",
        ):
            self.assertIn(label, self.dashboard)
        for helper in (
            "renderDistribution",
            "deliveryHealthRows",
            "renderChannelHealth",
            "renderOverviewCards",
            "renderAttentionCompanyCards",
            "compactMetricList",
        ):
            self.assertIn(f"function {helper}", self.dashboard)
        self.assertIn("platform-dashboard-health-grid", self.dashboard)

    def test_dashboard_keeps_top_level_cards_focused(self):
        overview_cards = re.search(
            r"function renderOverviewCards\(overview\) \{(.*?)\n    \}",
            self.dashboard,
            flags=re.S,
        ).group(1)
        for label in (
            "Total companies",
            "Active companies",
            "Active users",
            "Open support cases",
        ):
            self.assertIn(label, overview_cards)
        for crowded_label in ("Trialing", "Past due", "Expired", "Inactive companies"):
            self.assertNotIn(crowded_label, overview_cards)
        for first_level_detail in (
            "Tenant footprint",
            "Plan distribution",
            "Broadcast campaign status",
            "Broadcast recipient status",
            "Credit activity",
            "Order status",
        ):
            self.assertNotIn(first_level_detail, self.dashboard)

    def test_visualizations_handle_zero_and_missing_values_without_nan(self):
        for marker in (
            "function count(value)",
            "function valueFrom(map, key)",
            "platform-segment-empty",
            "total === 0",
            "No support cases found.",
            "No message delivery rows found.",
            "No AI request rows found.",
            "compactMetricList",
        ):
            self.assertIn(marker, self.dashboard)
        self.assertNotIn("innerHTML", self.dashboard)
        self.assertNotIn("insertAdjacentHTML", self.dashboard)

    def test_dashboard_security_copy_excludes_sensitive_data_domains(self):
        for copy in (
            "No SLA or overdue status is inferred.",
            "No message text, phone numbers, provider payloads, or raw provider errors are shown.",
            "Prompts, responses, provider payloads, and provider costs are excluded.",
            "Financial writes, refunds, plan changes, credit changes, and reconciliation mutations are not available here.",
            "Raw audit metadata is not shown on this dashboard.",
        ):
            self.assertIn(copy, self.dashboard)
        for forbidden in (
            "support reply body",
            "redacted_note",
            "phone_number",
            "provider_payload",
            "api_key",
            "access_token",
            "prompt_text",
            "response_text",
        ):
            self.assertNotIn(forbidden, self.dashboard)

    def test_native_css_visualization_classes_are_responsive(self):
        for css_class in (
            ".platform-kpi-grid",
            ".platform-chart",
            ".platform-segmented-meter",
            ".platform-bar-row",
            ".platform-alert-card",
            ".platform-channel-card",
            ".platform-visual-grid",
            ".platform-attention-company-cards",
            ".platform-attention-company-card",
        ):
            self.assertIn(css_class, self.css)
        self.assertIn("@media (max-width: 900px)", self.css)
        self.assertIn("@media (max-width: 767px)", self.css)
        self.assertIn(".platform-attention-company-cards {\n        display: grid;", self.css)


class TestPlatformAdminApiClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = read(API)
        cls.auth = read(FRONTEND / "assets" / "js" / "auth.js")

    def test_public_client_exposes_approved_platform_methods(self):
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
                "listApprovalRequests",
                "getApprovalRequest",
                "createApprovalRequest",
                "decideApprovalRequest",
                "updatePlatformAdminAccess",
                "recheckCompanyBillingOrder",
                "getOverview",
                "getBillingOverview",
                "listBillingCompanies",
                "listCompanies",
                "listAuditEvents",
                "listPlatformAdminUsers",
                "getPlatformAdminUser",
                "createPlatformAdminUser",
                "setPlatformAdminUserActive",
                "getCompany",
                "suspendCompany",
                "restoreCompany",
                "getCompanySubscription",
                "listCompanySubscriptionHistory",
                "getCompanyAiCreditUsage",
                "listCompanyAiCreditTransactions",
                "listCompanyBillingOrders",
                "listCompanyUsers",
                "listCompanyChatbots",
                "listSupportCases",
                "createSupportCase",
                "getSupportCase",
                "listSupportCaseAssignees",
                "listTenantSupportRequests",
                "getTenantSupportRequest",
                "updateTenantSupportRequest",
                "convertTenantSupportRequest",
                "addSupportCaseNote",
                "listSupportCaseReplies",
                "createSupportCaseReply",
                "assignSupportCase",
                "updateSupportCaseStatus",
                "updateSupportCasePriority",
            ],
        )

    def test_client_uses_allowlisted_methods_and_has_no_generic_public_request(self):
        self.assertIn('const requestMethod = method || "GET"', self.api)
        self.assertIn('method: requestMethod', self.api)
        self.assertNotIn('method: "PUT"', self.api)
        self.assertNotIn('method: "DELETE"', self.api)
        self.assertNotIn('"PUT"', self.api)
        self.assertNotIn('"DELETE"', self.api)
        self.assertNotIn("request: platformFetch", self.api)
        self.assertNotIn("mutation: platformFetch", self.api)
        self.assertNotIn("publicRequest", self.api)
        self.assertNotIn("genericMutation", self.api)
        self.assertNotIn("/api/admin/billing", self.api)
        approved_mutations = {
            "createSupportCase": ("/support-cases", "POST"),
            "updateTenantSupportRequest": ("/tenant-support-requests/\" + String(requestId)", "PATCH"),
            "convertTenantSupportRequest": ("/tenant-support-requests/\" + String(requestId) + \"/convert", "POST"),
            "addSupportCaseNote": ("/support-cases/\" + id + \"/notes", "POST"),
            "createSupportCaseReply": ("/support-cases/\" + id + \"/replies", "POST"),
            "assignSupportCase": ("/support-cases/\" + id + \"/assignment", "PATCH"),
            "updateSupportCaseStatus": ("/support-cases/\" + id + \"/status", "PATCH"),
            "updateSupportCasePriority": ("/support-cases/\" + id + \"/priority", "PATCH"),
            "createPlatformAdminUser": ("/platform-admin-users", "POST"),
            "setPlatformAdminUserActive": ("/platform-admin-users/\" + id + \"/active", "PATCH"),
            "suspendCompany": ("/companies/\" + id + \"/suspend", "POST"),
            "restoreCompany": ("/companies/\" + id + \"/restore", "POST"),
            "createApprovalRequest": ("/approval-requests", "POST"),
            "decideApprovalRequest": ('approvalPath(approvalId) + "/decision"', "POST"),
            "updatePlatformAdminAccess": ('requirePlatformAdminUserId(mappingId) + "/access"', "PATCH"),
            "recheckCompanyBillingOrder": ('String(orderId) + "/recheck"', "POST"),
        }
        seen_mutations = {}
        for function_name, body in re.findall(
            r"function (\w+)\([^)]*\) \{(.*?)\n    \}",
            self.api,
            flags=re.S,
        ):
            if '"POST"' not in body and '"PATCH"' not in body:
                continue
            seen_mutations[function_name] = body
        self.assertEqual(set(seen_mutations), set(approved_mutations))
        for function_name, (path_fragment, method) in approved_mutations.items():
            body = seen_mutations[function_name]
            self.assertIn(path_fragment, body)
            self.assertIn(f'"{method}"', body)
        for forbidden in (
            "/billing",
            "/companies/\" + id + \"/users",
            "/companies/\" + id + \"/subscription",
            "/companies/\" + id + \"/ai-credit",
            "/companies/\" + id + \"/billing-orders",
            "/chatbots",
            "/imperson",
            "/export",
            "/delete",
            "/messages",
        ):
            # The approved, ID-scoped recheck retries an existing payment only.
            other_mutations = (body for name, body in seen_mutations.items()
                               if name != "recheckCompanyBillingOrder")
            self.assertNotIn(forbidden, "\n".join(other_mutations))

    def test_tenant_support_intake_viewer_is_get_only_and_validates_display_paths(self):
        list_function = re.search(
            r"function listTenantSupportRequests\(options\) \{(.*?)\n    \}",
            self.api, flags=re.S,
        ).group(1)
        detail_function = re.search(
            r"function getTenantSupportRequest\(requestId, options\) \{(.*?)\n    \}",
            self.api, flags=re.S,
        ).group(1)
        self.assertIn('"/tenant-support-requests?', list_function)
        self.assertIn('"/tenant-support-requests/"', detail_function)
        self.assertNotIn('"POST"', list_function + detail_function)
        self.assertNotIn('"PATCH"', list_function + detail_function)
        self.assertIn('"invalid_request_id"', detail_function)
        support = read(SUPPORT)
        self.assertIn("tenantRequestDetail.replaceChildren()", support)
        self.assertIn("text only", support)
        for function_name in (
            "updateTenantSupportRequest",
            "convertTenantSupportRequest",
            "listSupportCaseReplies",
            "createSupportCaseReply",
        ):
            self.assertIn(function_name + ":", self.api)

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
            "suspendCompany",
            "restoreCompany",
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

    def test_company_lifecycle_controls_are_bounded_and_confirmed(self):
        company = read(COMPANY)
        self.assertIn("Operational state", company)
        self.assertIn("Suspend company", company)
        self.assertIn("Restore company", company)
        self.assertIn("window.confirm", company)
        self.assertIn("Tenant operational activity will be blocked", company)
        self.assertIn("button.disabled = true", company)
        self.assertIn("PlatformAdminApi.suspendCompany", company)
        self.assertIn("PlatformAdminApi.restoreCompany", company)
        self.assertIn("protected_company", company)
        for forbidden in (
            "delete company",
            "impersonat",
            "password reset",
            "manual credit",
            "role selector",
            "subscription mutation",
        ):
            self.assertNotIn(forbidden, company.casefold())

    def test_support_case_ids_use_invalid_case_id_validator(self):
        validator = re.search(
            r"function requireCaseId\(caseId\) \{(.*?)\n    \}",
            self.api,
            flags=re.S,
        ).group(1)
        self.assertIn('"invalid_case_id"', validator)
        for function_name in [
            "getSupportCase",
            "addSupportCaseNote",
            "listSupportCaseReplies",
            "createSupportCaseReply",
            "assignSupportCase",
            "updateSupportCaseStatus",
            "updateSupportCasePriority",
        ]:
            body = re.search(
                rf"function {function_name}\(caseId,.*?\) \{{(.*?)\n    \}}",
                self.api,
                flags=re.S,
            ).group(1)
            self.assertLess(body.index("requireCaseId(caseId)"), body.index("platformFetch("))

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
        cls.api = read(API)
        cls.audit_events = read(AUDIT_EVENTS)

    def test_tenant_support_has_bounded_authenticated_submission_form(self):
        page = read(TENANT_SUPPORT)
        self.assertIn("<h1>Support</h1>", page)
        self.assertIn('id="support-request-form"', page)
        self.assertIn('authenticatedFetch("/api/support/requests"', page)
        self.assertIn("Do not include passwords, tokens, cookies, payment details", page)
        self.assertIn("<chatbot-sidebar></chatbot-sidebar>", page)
        self.assertIn("requireLogin();", page)
        self.assertNotIn("Platform Administration", page)
        self.assertNotIn("PlatformAdminShell", page)
        self.assertNotIn("/api/platform-admin", page)
        payload = page.split("var values = {", 1)[1].split("};", 1)[0]
        for field in ("category", "title", "redacted_description"):
            self.assertIn(field, payload)
        # `priority` was forbidden here until the Help Desk redesign. It is now
        # tenant input: the requester states their own urgency (low/normal/urgent)
        # so staff can triage, and the server enum-validates it. It grants no
        # entitlement and feeds no billing or access decision, which makes it a
        # peer of `category`. `status` is different and stays forbidden - the
        # platform alone owns a request's lifecycle state.
        for forbidden in (
            "company_id", "user_id", "platform_admin", "status",
            "assignment", "audit_metadata", "payment_reference", "token", "cookie",
        ):
            self.assertNotIn(forbidden, payload)
        for forbidden_control in (
            "support-request-inbox",
            "support-request-message", "send message", "email integration",
            "type=\"file\"", "billing-action", "impersonation-control",
            "support-request-export", "support-request-chart",
        ):
            self.assertNotIn(forbidden_control, page.lower())
        self.assertIn("Support History", page)
        self.assertIn('authenticatedFetch("/api/support/requests?limit=25&offset=0"', page)
        self.assertIn('authenticatedFetch("/api/support/requests/" + String(requestId)', page)
        self.assertIn("Tenant-visible replies", page)

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
        for marker in [
            "Support Operations",
            "Messaging Health",
            "Billing Health",
            "AI Usage",
            "Platform Admin Activity",
            "Case status",
            "Delivery health",
            "Channel Health",
            "Request status",
            "platform-dashboard-health-grid",
            "platform-compact-metric-list",
            "Open Support Workspace",
            "View Audit Logs",
            "View Billing Details",
            "No SLA or overdue status is inferred.",
            "No message text, phone numbers, provider payloads, or raw provider errors are shown.",
            "Prompts, responses, provider payloads, and provider costs are excluded.",
            "Raw audit metadata is not shown on this dashboard.",
            "platform-segmented-meter",
            "platform-bar-row",
        ]:
            self.assertIn(marker, self.dashboard)
        self.assertNotIn("Read-only subscription alerts derived from the platform operations overview", self.dashboard)
        api_source = read(API)
        self.assertIn('return platformFetch("/overview"', api_source)
        self.assertNotIn("listOperationalAlerts", api_source)
        for forbidden in [
            "PlatformAdminApi.listCompanies({",
            "innerHTML",
            "JSON.stringify",
            "message_text",
            "phone_number",
            "model_input",
            "model_output",
            "access_token",
            "api_key",
            "authorization",
            "webhook_secret",
            "checkout_url",
            "gateway_order_id",
            "payment_reference",
            "last_reconciliation_error",
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

    def test_support_workspace_uses_cases_and_keeps_investigation_calls_bounded(self):
        self.assertIn("Support Workspace", read(FRONTEND / "platform-admin-support.html"))
        self.assertIn("PlatformAdminShell.start({ onAuthorized: initializeSupportWorkspace })", self.support)
        self.assertIn('ui.runRequest("support-overview"', self.support)
        self.assertIn("PlatformAdminApi.getOverview({ signal: signal })", self.support)
        self.assertIn('ui.runRequest("support-company-lookup"', self.support)
        self.assertIn("PlatformAdminApi.listCompanies({", self.support)
        self.assertIn("PlatformAdminApi.listSupportCases({", self.support)
        self.assertIn('parsePositiveQueryId("company_id")', self.support)
        self.assertIn("companyId: state.companyFilterId || undefined", self.support)
        self.assertIn("filtered to company #", self.support)
        self.assertIn("PlatformAdminApi.createSupportCase(", self.support)
        self.assertIn("PlatformAdminApi.getSupportCase(", self.support)
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

    def test_support_case_history_requests_are_paginated(self):
        detail_function = re.search(
            r"function getSupportCase\(caseId, options\) \{(.*?)\n    \}",
            self.api,
            flags=re.S,
        ).group(1)
        replies_function = re.search(
            r"function listSupportCaseReplies\(caseId, options\) \{(.*?)\n    \}",
            self.api,
            flags=re.S,
        ).group(1)
        self.assertIn('params.set("event_limit"', detail_function)
        self.assertIn('params.set("event_offset"', detail_function)
        self.assertIn('"/support-cases/" + id + "?"', detail_function)
        self.assertIn('params.set("limit"', replies_function)
        self.assertIn('params.set("offset"', replies_function)
        self.assertIn('"/support-cases/" + id + "/replies?"', replies_function)
        for marker in [
            "events_pagination",
            "replies_pagination",
            "Load more timeline",
            "Load more replies",
            "loadMoreSupportCaseEvents",
            "loadMoreSupportCaseReplies",
            "state.timelineLoading",
            "state.repliesLoading",
            "mergeById",
            'ui.runRequest("support-case-events-more"',
            'ui.runRequest("support-case-replies-more"',
            "eventOffset: pagination.offset + pagination.returned",
            "offset: pagination.offset + pagination.returned",
        ]:
            self.assertIn(marker, self.support)
        timeline_merge = re.search(
            r"state\.activeCaseData\.events = mergeById\((.*?)\);",
            self.support,
            flags=re.S,
        ).group(1)
        reply_merge = re.search(
            r"state\.activeCaseData\.public_replies = mergeById\((.*?)\);",
            self.support,
            flags=re.S,
        ).group(1)
        notification_merge = re.search(
            r"state\.activeCaseData\.reply_notifications = mergeById\((.*?)\);",
            self.support,
            flags=re.S,
        ).group(1)
        self.assertIn('"id"', timeline_merge)
        self.assertNotIn('"event_id"', timeline_merge)
        self.assertIn('"reply_id"', reply_merge)
        self.assertIn('"notification_id"', notification_merge)

    def test_support_case_assignee_labels_use_safe_identity_fields(self):
        label_function = re.search(
            r"function assigneeLabel\(assigneeId\) \{(.*?)\n    \}",
            self.support,
            flags=re.S,
        ).group(1)
        self.assertIn("match.user_full_name", label_function)
        self.assertIn("match.user_email", label_function)
        self.assertIn('fullName + " — " + email', label_function)
        self.assertIn("if (fullName) return fullName;", label_function)
        self.assertIn("if (email) return email;", label_function)
        self.assertIn('"Platform Admin #"', label_function)
        self.assertNotIn('"Admin mapping #"', label_function)
        self.assertNotIn('"user #"', label_function)
        self.assertNotIn("innerHTML", label_function)
        self.assertNotIn("insertAdjacentHTML", label_function)
        self.assertIn('value: String(item.id)', self.support)
        self.assertIn('label: assigneeLabel(item.id)', self.support)
        self.assertIn('assigned_platform_admin_user_id: selected', self.support)
        self.assertIn('{ value: "", label: "Unassigned" }', self.support)
        self.assertNotIn("assigned_platform_admin_user_id: selected.user_id", self.support)

    def test_support_case_historical_current_assignee_stays_selected_but_not_assignable(self):
        select_function = re.search(
            r"function selectField\(labelText, id, values, selected\) \{(.*?)\n    \}",
            self.support,
            flags=re.S,
        ).group(1)
        self.assertIn("option.disabled = value.disabled === true;", select_function)
        self.assertIn("option.selected = value.value === selected;", select_function)

        detail_function = re.search(
            r"function renderCaseDetail\(data\) \{(.*?)\n    async function loadMoreSupportCaseEvents",
            self.support,
            flags=re.S,
        ).group(1)
        for marker in [
            "const currentAssigneeId = current.assigned_platform_admin_user_id;",
            "const hasCurrentAssignee = Number.isSafeInteger(currentAssigneeId) && currentAssigneeId > 0;",
            "const currentAssigneeValue = hasCurrentAssignee ? String(currentAssigneeId) : \"\";",
            "const activeAssigneeValues = state.caseAssignees.map",
            "const currentAssigneeIsActive = hasCurrentAssignee && state.caseAssignees.some",
            "return item.id === currentAssigneeId;",
            "label: assigneeLabel(currentAssigneeId) + \" (inactive/current)\"",
            "disabled: true",
            "assigneeValues.push.apply(assigneeValues, activeAssigneeValues);",
            "assigneeValues.push({ value: \"\", label: \"Unassigned\" });",
            "updateAssignee.disabled = assignee.input.value === currentAssigneeValue;",
            "assigned_platform_admin_user_id: selected",
        ]:
            self.assertIn(marker, detail_function)
        self.assertNotIn("state.caseAssignees.push", detail_function)
        self.assertNotIn("state.caseAssignees.unshift", detail_function)
        self.assertNotIn("assigned_platform_admin_user_id: currentAssigneeId", detail_function)

    def test_support_workspace_has_internal_case_states_and_safe_controls(self):
        for marker in [
            "Tenant investigation with controlled internal case operations",
            "Internal support cases",
            "Internal notes are not customer-facing",
            "Tenant-visible conversation",
            "Send reply to tenant",
            "This reply will be visible to the tenant",
            "PlatformAdminApi.listSupportCaseReplies",
            "PlatformAdminApi.createSupportCaseReply",
            'ui.runRequest("support-case-public-reply"',
            "replyButton.disabled = true;",
            "} finally {",
            "replyButton.isConnected",
            "billing, export, impersonation, attachment, email, and SLA actions remain excluded",
            "Tenant-submitted support requests",
            "rendered as text only",
            "Approved review, close, and conversion controls",
            "Tenant-visible replies are bounded platform-admin workflows",
            "Mark reviewed",
            "Close request",
            "Convert to internal case",
            "window.confirm",
            "PlatformAdminApi.updateTenantSupportRequest",
            "PlatformAdminApi.convertTenantSupportRequest",
            "loadTenantSupportRequests();",
            "Open internal case #",
            "Loading support workspace...",
            "No companies currently require attention.",
            "No company search results found.",
            "Company lookup is temporarily unavailable.",
            "Search companies",
            "Investigate",
        ]:
            self.assertIn(marker, self.support)
        for forbidden in [
            "Send customer message",
            "Assign a tenant",
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
            self.assertNotIn(forbidden, self.support)
        for marker in [
            "Internal support cases",
            "Create internal case",
            "Redacted summary",
            "Add internal note",
            "Update status",
            "Update priority",
            "Update assignee",
            "Case activity timeline",
            "PlatformAdminApi.createSupportCase",
            "PlatformAdminApi.addSupportCaseNote",
            "PlatformAdminApi.assignSupportCase",
            "PlatformAdminApi.updateSupportCaseStatus",
            "PlatformAdminApi.updateSupportCasePriority",
        ]:
            self.assertIn(marker, self.support)

    def test_platform_admin_user_management_page_is_bounded_to_mapping_lifecycle(self):
        page = read(FRONTEND / "platform-admin-users.html")
        controller = read(PLATFORM_ADMIN_USERS)
        self.assertIn("Platform Admin Management", controller)
        self.assertIn("PlatformAdminShell.start({ onAuthorized: initialize })", controller)
        for marker in [
            "PlatformAdminApi.listPlatformAdminUsers",
            "PlatformAdminApi.createPlatformAdminUser",
            "PlatformAdminApi.setPlatformAdminUserActive",
            "Existing user ID",
            "protected internal company",
            "Invitations and new-account creation are not supported here.",
            "Recent platform activity",
            "Bootstrap/unknown",
            "Self-deactivation is rejected by policy.",
            "The final active platform admin cannot be deactivated.",
            "window.confirm",
            "button.disabled = true;",
            "} finally {",
            "button.isConnected",
            "recoverableOnFailure",
            "Platform-admin directory refresh failed. Retry to load the current state.",
            "Retry",
            "isAuthorizationFailure",
        ]:
            self.assertIn(marker, controller)
        for forbidden in [
            "PlatformAdminApi.listCompanyUsers",
            "PlatformAdminApi.getCompany(",
            "company_id",
            "created_by_user_id",
            "users.role",
            "role selector",
            "type = \"password\"",
            "Impersonate",
            "Delete Company",
            "Suspend Company",
            "Change Plan",
            "Billing Orders",
        ]:
            self.assertNotIn(forbidden, controller + page)

    def test_audit_log_viewer_uses_shell_client_and_safe_metadata_summary(self):
        self.assertIn("Audit Logs", read(FRONTEND / "platform-admin-audit-events.html"))
        self.assertIn("PlatformAdminShell.start({ onAuthorized: initializeAuditLogViewer })", self.audit_events)
        self.assertIn('ui.runRequest("audit-events"', self.audit_events)
        self.assertIn("PlatformAdminApi.listAuditEvents({", self.audit_events)
        self.assertIn("function applyUrlFilters()", self.audit_events)
        self.assertIn('params.get("resource_type")', self.audit_events)
        self.assertIn('params.get("resource_id")', self.audit_events)
        self.assertIn("RESOURCE_TYPES.indexOf(resourceType) !== -1", self.audit_events)
        self.assertIn("^[A-Za-z0-9_.:-]+$", self.audit_events)
        self.assertIn("Read-only platform-admin activity history", self.audit_events)
        self.assertIn("does not expose raw metadata or tenant records", self.audit_events)
        self.assertIn("Safe metadata summary", self.audit_events)
        self.assertIn("METADATA_KEYS", self.audit_events)
        self.assertIn("platform_admin.billing.overview.read", self.audit_events)
        self.assertIn("platform_admin.billing.company_list", self.audit_events)
        self.assertIn("platform_billing_overview", self.audit_events)
        self.assertIn("platform_billing_companies", self.audit_events)
        self.assertIn("platform_admin.company.billing_orders.read", self.audit_events)
        self.assertIn("company_billing_orders", self.audit_events)
        for safe_key in [
            "company_filter_applied",
            "subscription_status_filter_applied",
            "plan_filter_applied",
            "attention_filter_applied",
            "priority_filter_applied",
            "company_id",
            "status",
            "priority",
            "target_platform_admin_user_id",
            "target_user_id",
            "old_is_active",
            "new_is_active",
        ]:
            self.assertIn('"' + safe_key + '"', self.audit_events)
        for action in [
            "platform_admin.user.list",
            "platform_admin.user.read",
            "platform_admin.user.create",
            "platform_admin.user.activate",
            "platform_admin.user.deactivate",
        ]:
            self.assertIn(action, self.audit_events)
        self.assertIn("platform_admin_users", self.audit_events)

    def test_platform_billing_page_is_read_only_and_uses_bounded_client_methods(self):
        page = read(FRONTEND / "platform-admin-billing.html")
        controller = read(PLATFORM_BILLING)
        self.assertIn('active-page="billing"', page)
        self.assertIn("Platform Billing & Subscriptions", controller)
        self.assertIn("PlatformAdminShell.start({ onAuthorized: initializeBillingPage })", controller)
        self.assertIn("PlatformAdminApi.getBillingOverview", controller)
        self.assertIn("PlatformAdminApi.listBillingCompanies", controller)
        self.assertIn("platform-admin-company.html?company_id=", controller)
        self.assertIn("Tenant Billing Directory", controller)
        self.assertIn("AI-credit top-up attention", controller)
        self.assertIn('field("Subscription status", status)', controller)
        self.assertIn('field("Plan code", plan)', controller)
        self.assertIn('field("Attention", attention)', controller)
        self.assertIn('status.id = "platform-billing-subscription-status"', controller)
        self.assertIn('plan.id = "platform-billing-plan-code"', controller)
        self.assertIn('attention.id = "platform-billing-attention"', controller)
        self.assertIn("platform-billing-mobile-card-list", controller)
        self.assertIn("platform-billing-directory-cards", controller)
        self.assertIn("Tenant billing directory mobile cards", controller)
        self.assertIn("View Company", controller)
        self.assertIn("No subscription", controller)
        self.assertIn("{ mobileCards: false }", controller)
        self.assertIn(".platform-billing-mobile-card-list", read(FRONTEND / "assets" / "css" / "platform-admin.css"))
        self.assertIn("formatSen(plan.price_sen)", controller)
        self.assertNotIn("plan.price)", controller)
        self.assertIn('moneyMetric("Included balance", credit.total_included_balance_micro_myr)', controller)
        self.assertIn('moneyMetric("Top-up balance", credit.total_topup_balance_micro_myr)', controller)
        self.assertIn('ui.formatMicroMyr(value || 0)', controller)
        self.assertNotIn("innerHTML", controller)
        for forbidden in [
            "manual adjustment",
            "refund action",
            "retry payment",
            "change plan",
            "impersonate",
            "delete company",
            "password reset",
            "service_role",
            '"post"',
            '"patch"',
            '"put"',
            '"delete"',
        ]:
            self.assertNotIn(forbidden, controller.lower())
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
        self.assertIn("PlatformAdminApi.listTenantSupportRequests({", self.company)
        self.assertIn("PlatformAdminApi.listSupportCases({", self.company)
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

    def test_company_detail_support_history_is_lazy_safe_and_company_scoped(self):
        initialize = re.search(
            r"async function initializeCompanyDetail\(\) \{(.*?)\n    \}",
            self.company,
            flags=re.S,
        ).group(1)
        company_fetch = initialize.index("PlatformAdminApi.getCompany(companyId")
        support_panel = initialize.index("supportHistoryPanel(companyId)")
        self.assertLess(company_fetch, support_panel)
        for marker in [
            "Support history",
            "Load support history",
            "Loading support history...",
            "Open Support Workspace",
            "platform-admin-support.html?",
            'params.set("company_id", String(companyId))',
            'ui.runRequest("company-support-requests"',
            'ui.runRequest("company-support-cases"',
            "companyId: companyId",
            "Tenant support requests",
            "Internal support cases",
            "Internal notes and reply bodies are excluded",
        ]:
            self.assertIn(marker, self.company)

    def test_company_detail_links_to_company_scoped_platform_admin_audit(self):
        for marker in [
            "Platform Admin activity for this company",
            "This is not a tenant application audit history.",
            "Open Audit Logs",
            "platform-admin-audit-events.html?",
            'params.set("resource_type", "company")',
            'params.set("resource_id", String(companyId))',
        ]:
            self.assertIn(marker, self.company)

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
        sources = "\n".join([
            read(API),
            read(SHELL),
            self.dashboard,
            self.companies,
            self.company,
            read(PLATFORM_BILLING),
            self.support,
            read(PLATFORM_ADMIN_USERS),
        ])
        self.assertNotIn("innerHTML", sources)
        self.assertIn("textContent", sources)

    def test_no_raw_error_logging_or_unsupported_routes(self):
        sources = "\n".join([
            read(API),
            read(SHELL),
            self.dashboard,
            self.companies,
            self.company,
            read(PLATFORM_BILLING),
            self.support,
            read(PLATFORM_ADMIN_USERS),
        ])
        self.assertNotIn("console.", sources)
        self.assertNotIn("/api/admin/billing", sources)
        for method in ["PUT", "DELETE"]:
            self.assertNotIn(f'method: "{method}"', sources)

    def test_no_mutation_or_impersonation_controls_exist(self):
        pages_and_controllers = (
            "\n".join(read(path) for path in PAGES)
            + self.dashboard
            + self.companies
            + self.company
            + read(PLATFORM_BILLING)
            + self.support
            + read(PLATFORM_ADMIN_USERS)
        )
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
        sources = "\n".join(read(path) for path in PAGES + [
            API,
            SHELL,
            COMPANIES,
            COMPANY,
            SUPPORT,
            PLATFORM_ADMIN_USERS,
        ])
        self.assertNotIn("flow-builder", sources.lower())
        self.assertNotIn("broadcast", sources.lower())
        dashboard = read(DASHBOARD)
        self.assertIn("Delivery health", dashboard)
        self.assertNotIn("Broadcast campaign status", dashboard)


if __name__ == "__main__":
    unittest.main()
