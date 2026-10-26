import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:8000")
os.environ.setdefault("RATELIMIT_ENABLED", "false")

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app

from app.services.billing_guard import BillingLimitError


USER = {"id": 7, "company_id": 42, "role": "member", "status": "active"}


class GeoRouteTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.jwt = patch("app.decorators.auth_decorator.jwt.decode",
                         return_value={"user_id": 7, "company_id": 999, "role": "owner"})
        self.user = patch("app.database.user_repository.get_user_by_id", return_value=USER)
        self.status = patch("app.services.company_status_service.get_company_status_by_id",
                            return_value={"id": 42, "status": "active"})

    def _headers(self):
        return {"Authorization": "Bearer test-token"}

    def test_geo_routes_require_authentication(self):
        response = self.client.get("/api/geo/analyses")
        self.assertEqual(response.status_code, 401)

    def test_create_uses_refreshed_company_scope_for_paid_member(self):
        expected = {"id": "analysis-id", "status": "complete"}
        with self.jwt, self.user, self.status, \
             patch("app.routes.geo_routes.get_company_geo_entitlement", return_value={
                 "plan_code": "pro", "label": "Pro", "monthly_executions": 120,
                 "prompts_per_analysis": 4, "platforms": ["chatgpt", "gemini", "perplexity"],
                 "samples_per_prompt": 1, "history_limit": 50,
             }) as entitlement, \
             patch("app.routes.geo_routes.run_analysis", return_value=expected) as run:
            response = self.client.post("/api/geo/analyses", json={"brand_name": "Omnexa"},
                                        headers=self._headers())
        self.assertEqual(response.status_code, 201)
        entitlement.assert_called_once_with(42)
        run.assert_called_once_with(42, 7, {"brand_name": "Omnexa"}, entitlement.return_value)

    def test_free_plan_is_denied_before_provider_execution(self):
        denied = BillingLimitError("Upgrade required", code="feature_not_available")
        with self.jwt, self.user, self.status, \
             patch("app.routes.geo_routes.get_company_geo_entitlement", side_effect=denied), \
             patch("app.routes.geo_routes.run_analysis") as run:
            response = self.client.post("/api/geo/analyses", json={}, headers=self._headers())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "feature_not_available")
        run.assert_not_called()

    def test_oversized_request_is_rejected_before_provider_execution(self):
        entitlement = {"plan_code": "pro", "label": "Pro", "monthly_executions": 120,
                       "prompts_per_analysis": 4, "platforms": ["chatgpt", "gemini", "perplexity"],
                       "samples_per_prompt": 1, "history_limit": 50}
        with self.jwt, self.user, self.status, \
             patch("app.routes.geo_routes.get_company_geo_entitlement", return_value=entitlement), \
             patch("app.routes.geo_routes.run_analysis") as run:
            response = self.client.post("/api/geo/analyses", data=b"x" * 32769,
                                        headers={**self._headers(), "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "geo_request_too_large")
        run.assert_not_called()

    def test_capabilities_return_plan_platforms_and_monthly_usage(self):
        entitlement = {"plan_code": "advanced", "label": "Advanced", "monthly_executions": 40,
                       "prompts_per_analysis": 2, "platforms": ["chatgpt", "gemini", "perplexity"],
                       "samples_per_prompt": 1, "history_limit": 25}
        with self.jwt, self.user, self.status, \
             patch("app.routes.geo_routes.get_company_geo_entitlement", return_value=entitlement), \
             patch("app.routes.geo_routes.platform_capabilities", return_value={
                 "chatgpt": {"configured": True, "mode": "official_api"},
                 "gemini": {"configured": True, "mode": "official_api"},
                 "perplexity": {"configured": False, "mode": "official_api"}}), \
             patch("app.routes.geo_routes.comparison_capability", return_value={"enabled": False}), \
             patch("app.routes.geo_routes.geo_repository.get_monthly_usage", return_value=7):
            response = self.client.get("/api/geo/capabilities", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["usage"]["remaining"], 33)
        self.assertEqual(data["limits"]["minimum_reliable_samples"], 3)
        self.assertEqual(data["limits"]["rolling_analysis_window"], 5)
        self.assertEqual(data["limits"]["keywords"], 10)
        self.assertEqual(data["limits"]["executions"], 3)
        self.assertTrue(data["platforms"]["chatgpt"]["included"])
        self.assertFalse(data["platforms"]["perplexity"]["configured"])

    def test_comparison_is_paid_plan_scoped_and_uses_same_market_input(self):
        entitlement = {"plan_code": "pro", "label": "Pro", "monthly_executions": 120,
                       "prompts_per_analysis": 4, "platforms": ["chatgpt"],
                       "samples_per_prompt": 1, "history_limit": 50}
        expected = {"direct": {"request_status": "complete"},
                    "openrouter": {"request_status": "complete"}}
        with self.jwt, self.user, self.status, \
             patch("app.routes.geo_routes.get_company_geo_entitlement", return_value=entitlement), \
             patch("app.routes.geo_routes.compare_openai_routes", return_value=expected) as compare:
            response = self.client.post("/api/geo/provider-comparison", json={
                "prompt": "Best provider?", "country": "MY", "language": "en"},
                headers=self._headers())
        self.assertEqual(response.status_code, 200)
        compare.assert_called_once_with("Best provider?", "MY", "en")


if __name__ == "__main__":
    unittest.main()
