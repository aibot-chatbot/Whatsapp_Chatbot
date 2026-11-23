"""Contracts for the Super Admin and Admin portals and their shared API client."""

import re
import unittest
from pathlib import Path

from tests.frontend_pages import page_source_path, WEB_PUBLIC_JS

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PAGES = [page_source_path(name) for name in ("superadmin.html", "admin.html")]
API = FRONTEND / "assets/js/platform-admin-api.js"
SHELL = FRONTEND / "assets/js/platform-admin-shell.js"
PORTAL = FRONTEND / "assets/js/superadmin-portal.js"
SIDEBAR = FRONTEND / "sidebar-component.js"
SUPPORT_JS = WEB_PUBLIC_JS / "support.js"


def read(path):
    return path.read_text(encoding="utf-8")


class TestPlatformAdminPageGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = read(SHELL)
        cls.controllers = [read(PORTAL), read(FRONTEND / "assets/js/admin-portal.js")]

    def test_both_portals_start_hidden_and_load_auth_before_data(self):
        for page, app_id in zip(PAGES, ("platform-app", "admin-app")):
            html = read(page)
            self.assertRegex(html, rf'<div id="{app_id}"[^>]* hidden')
            for marker in ('aria-busy="true"', "Checking access", 'class="skip-link"', "<main", "aria-live"):
                self.assertIn(marker, html)
            self.assertLess(html.index("assets/js/auth.js"), html.index("assets/js/platform-admin-api.js"))
            self.assertLess(html.index("assets/js/platform-admin-api.js"), html.index(f"assets/js/{page.stem}-portal.js"))
        self.assertIn("shell.start({ onAuthorized:", self.controllers[0])
        self.assertLess(self.shell.index("PlatformAdminApi.getMe"), self.shell.index("await lifecycle.onAuthorized(identity)"))
        self.assertIn("await api.getMe(", self.controllers[1])

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

    def test_retired_platform_pages_and_links_are_absent(self):
        self.assertEqual(list((ROOT / "web/src/pages").glob("platform-admin*.astro")), [])
        pattern = re.compile(r"platform-admin(?:-[a-z-]+)?\.html")
        for folder, extension in (("frontend/assets/js", "*.js"), ("web/src", "*.astro"),
                                  ("web/public", "*.js")):
            for source in (ROOT / folder).rglob(extension):
                self.assertIsNone(pattern.search(read(source)), str(source))

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
                "listOpenRouterKeys",
                "getOpenRouterKeyCompanies",
                "setOpenRouterKeyMaxClients",
                "replaceOpenRouterKey",
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
                "listSafetyFlags",
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
            "setOpenRouterKeyMaxClients": ('/openrouter-keys/" + id + "/max-clients', "PATCH"),
            "replaceOpenRouterKey": ('/openrouter-keys/" + id + "/replace', "POST"),
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
        company = read(PORTAL)
        action = company.split('if (action === "suspend-company"', 1)[1].split('if (action ===', 1)[0]
        self.assertIn("confirmAction(", action)
        self.assertIn("Customer users will lose access", action)
        self.assertIn("api.suspendCompany", action)
        self.assertIn("api.restoreCompany", action)
        for forbidden in (
            "delete company",
            "impersonat",
            "password reset",
            "manual credit",
            "role selector",
            "subscription mutation",
        ):
            self.assertNotIn(forbidden, action.casefold())

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


class TestTenantPageIsolation(unittest.TestCase):
    def test_tenant_support_has_bounded_authenticated_submission_form(self):
        page = read(page_source_path("support.html")) + read(SUPPORT_JS)
        self.assertIn("<h1>Support</h1>", page)
        self.assertIn('id="support-request-form"', page)
        self.assertIn('authenticatedFetch("/api/support/requests"', page)
        self.assertIn("Do not include passwords, tokens, cookies, payment details", page)
        # Sidebar and login pins move to page-smoke.spec.js's AppLayout support branch.
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

    def test_ordinary_tenant_sidebar_has_no_platform_entry(self):
        sidebar = read(SIDEBAR).lower()
        self.assertNotIn("platform-admin", sidebar)
        self.assertNotIn("platform administration", sidebar)


class TestSuperAdminSafetyFlags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portal = read(FRONTEND / "assets" / "js" / "superadmin-portal.js")
        cls.api = read(API)
        cls.safety = cls.portal.split("const safetyCategories =", 1)[1].split("async function render()", 1)[0]

    def test_section_uses_existing_super_admin_gate_and_request_lifecycle(self):
        self.assertIn('["safety", "Safety flags", "shield", ""]', self.portal)
        self.assertIn('if (route === "safety") { await safetyFlags(sequence); return; }', self.portal)
        self.assertIn('current?.platform_role !== "super_admin"', self.portal)
        self.assertIn('shell.runRequest("view", signal => api.listSafetyFlags', self.safety)
        self.assertIn('sequence !== viewSequence || !identity', self.safety)

    def test_safety_data_uses_text_nodes_and_hides_child_rule(self):
        self.assertIn('document.createElement(tag)', self.safety)
        self.assertIn('node.textContent = text', self.safety)
        self.assertIn('document.createTextNode', self.safety)
        self.assertNotIn('innerHTML', self.safety)
        self.assertNotIn('insertAdjacentHTML', self.safety)
        self.assertIn('item.category === "child_sexual" ? "Hidden for child safety" : item.rule', self.safety)
        for forbidden in ('item.payload', 'item.message', 'item.customer_phone', 'item.customer_name'):
            self.assertNotIn(forbidden, self.safety)

    def test_filters_tables_and_count_scope_are_accessible(self):
        for marker in ('"safety-days"', '"safety-company"', '"safety-category"', 'labelNode.htmlFor = id',
                       'form.reportValidity()', 'region.tabIndex = 0', 'cell.scope = "col"',
                       'status.setAttribute("aria-live", "polite")', '"warning"', '"pause_requested"',
                       '"Client summary · last 7 days"', '"Category counts · displayed flags"',
                       '"Recent flags · newest first"', 'maximum 200', 'full last 7 days'):
            self.assertIn(marker, self.safety)
        self.assertIn('days.max = "30"', self.safety)
        self.assertIn('Self-harm and log-mode flags do not count.', self.safety)
        self.assertIn('this view never pauses a Client.', self.safety)

    def test_shared_api_forwards_filters_and_abort_signal(self):
        method = self.api.split('function listSafetyFlags(options) {', 1)[1].split('function listAuditEvents', 1)[0]
        for marker in ('params.set("days", String(config.days ?? 7))',
                       'params.set("company_id", String(config.companyId))',
                       'params.set("category", config.category)',
                       'platformFetch("/safety-flags?" + params.toString(), config.signal)'):
            self.assertIn(marker, method)
