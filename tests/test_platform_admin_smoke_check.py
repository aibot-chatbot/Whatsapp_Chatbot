"""Focused tests for the read-only platform-admin smoke checker."""

import contextlib
import io
import os
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import platform_admin_smoke_check as smoke


class FakeResponse:
    def __init__(self, data=None, status_code=200, method="GET"):
        self.status_code = status_code
        self.request = Mock(method=method)
        self._payload = {"status": "success", "data": data or {}}

    def json(self):
        return self._payload


def response_for(path):
    if path.endswith("/overview"):
        return FakeResponse({"operational_alerts": []})
    return FakeResponse({})


class TestPlatformAdminSmokeCheck(unittest.TestCase):
    def setUp(self):
        self.http_get = Mock(side_effect=lambda url, **kwargs: response_for(url))

    def test_token_must_come_from_environment_not_cli(self):
        with patch.dict(os.environ, {smoke.TOKEN_ENV: "env-token"}, clear=True):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = smoke.main(["--base-url", "http://localhost", "--token", "cli-secret"])
        self.assertEqual(result, 2)
        self.assertNotIn("cli-secret", output.getvalue())
        self.http_get.assert_not_called()

    def test_required_endpoints_use_get(self):
        results = smoke._run_with_overview_check(
            "http://localhost", "secret", None, 3, self.http_get
        )
        self.assertTrue(all(result.passed for result in results))
        self.assertEqual(self.http_get.call_count, 4)
        for call in self.http_get.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer secret")
            self.assertEqual(call.kwargs["timeout"], 3)
            self.assertEqual(call.kwargs["method"], "GET")
        self.assertTrue(all(result.path.startswith("/api/platform-admin/") for result in results))

    def test_child_endpoints_are_skipped_without_company_id(self):
        results = smoke._run_with_overview_check(
            "http://localhost", "secret", None, 3, self.http_get
        )
        self.assertEqual(len(results), 4)
        self.assertEqual(self.http_get.call_count, 4)

    def test_child_endpoints_are_checked_with_company_id(self):
        results = smoke._run_with_overview_check(
            "http://localhost", "secret", 42, 3, self.http_get
        )
        self.assertEqual(len(results), 12)
        self.assertEqual(self.http_get.call_count, 12)
        self.assertIn("/api/platform-admin/companies/42/chatbots", [result.path for result in results])

    def test_forbidden_billing_strings_fail(self):
        def unsafe_response(url, **kwargs):
            if url.endswith("/billing-orders"):
                return FakeResponse({"billing_orders": [{"MYR": "100"}]})
            return response_for(url)

        results = smoke._run_with_overview_check(
            "http://localhost", "secret", 42, 3, Mock(side_effect=unsafe_response)
        )
        billing = next(result for result in results if result.path.endswith("/billing-orders"))
        self.assertFalse(billing.passed)

    def test_token_is_not_printed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            smoke._print_results([smoke.CheckResult("/api/platform-admin/me", True, "HTTP 200")], None)
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("Bearer", output.getvalue())


if __name__ == "__main__":
    unittest.main()
