"""Customer-billed AI accounting contract regressions."""

import inspect
import os
import sys
import types
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# --- Billing moved out of profile.html (2026-09) -------------------------------
# The billing surface now lives on its own page, split across markup, logic and
# styles. These assertions guard the billing guarantees, so they read all three
# parts of that page as one source rather than a single monolithic file.
def _read_billing_source():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _parts = []
    for _rel in (("billing.html",), ("assets", "js", "billing.js"), ("assets", "css", "billing.css")):
        _path = os.path.join(_root, "frontend", *_rel)
        with open(_path, "r", encoding="utf-8", errors="replace") as _fh:
            _parts.append(_fh.read())
    return chr(10).join(_parts)


def _fn_body(source, name):
    """Return the brace-matched body of a JS function declaration."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", source)
    if not m:
        raise AssertionError("function %s not found in billing source" % name)
    start = source.index("{", m.end() - 1)
    depth = 0
    for j in range(start, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError("unbalanced braces in %s" % name)
# ------------------------------------------------------------------------------



os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")

if "google" not in sys.modules:
    _google = types.ModuleType("google")
    _google.genai = types.ModuleType("google.genai")
    _google.genai.Client = MagicMock()
    sys.modules["google"] = _google
    sys.modules["google.genai"] = _google.genai

if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestCustomerBilledOperationInventory(unittest.TestCase):
    def test_ai_router_declares_expected_customer_billed_operation_types(self):
        from app.services import ai_router

        expected = {
            "chat_reply",
            "test_chat",
            "test_bot",
            "knowledge_refinement_questions",
            "knowledge_refinement_verification",
            "test_scenario_generation",
            "persona_derivation",
            "profile_knowledge_match",
            "website_knowledge_extraction",
            "knowledge_graph_extraction",
            "welcome_menu_generation",
            "ai_report",
        }
        actual = {
            value
            for name, value in vars(ai_router).items()
            if name.startswith("OPERATION_") and isinstance(value, str)
        }

        self.assertTrue(expected <= actual)

    def test_refine_answers_uses_distinct_operation_types(self):
        import app.routes.knowledge_routes as knowledge_routes

        source = inspect.getsource(knowledge_routes.get_refinement_questions)

        self.assertIn("OPERATION_KNOWLEDGE_REFINEMENT_QUESTIONS", source)
        self.assertIn("OPERATION_KNOWLEDGE_REFINEMENT_VERIFICATION", source)
        self.assertIn(
            "operation_type=OPERATION_KNOWLEDGE_REFINEMENT_QUESTIONS",
            source,
        )
        self.assertIn(
            "operation_type=OPERATION_KNOWLEDGE_REFINEMENT_VERIFICATION",
            source,
        )

    def test_distinct_customer_facing_system_features_do_not_reuse_generic_label(self):
        import app.services.knowledge_service as knowledge_service
        import app.services.match_service as match_service
        import app.services.persona_derivation_service as persona_service
        import app.services.test_scenario_service as scenario_service

        cases = [
            (knowledge_service.extract_business_knowledge, "OPERATION_WEBSITE_KNOWLEDGE_EXTRACTION"),
            (knowledge_service.extract_and_store_graph_supabase, "OPERATION_KNOWLEDGE_GRAPH_EXTRACTION"),
            (match_service.check_pdf_config_match, "OPERATION_PROFILE_KNOWLEDGE_MATCH"),
            (persona_service._request_persona, "OPERATION_PERSONA_DERIVATION"),
            (scenario_service.build_test_scenarios, "OPERATION_TEST_SCENARIO_GENERATION"),
        ]

        for func, operation_name in cases:
            with self.subTest(func=func.__name__):
                source = inspect.getsource(func)
                self.assertIn(operation_name, source)
                self.assertNotIn(
                    "operation_type=OPERATION_KNOWLEDGE_EXTRACTION",
                    source,
                )

    def test_embeddings_remain_outside_customer_ai_credit_debits(self):
        import app.services.rag_service as rag_service

        source = inspect.getsource(rag_service.generate_embedding)

        self.assertIn("embed_content", source)
        self.assertNotIn("insert_usage_log", source)
        self.assertNotIn("charge_logged_ai_usage", source)
        self.assertNotIn("charge_ai_usage_credit", source)


class TestGenerativeUsageDebitContract(unittest.TestCase):
    def test_known_cost_usage_log_creates_debit_transaction(self):
        from app.services import ai_router

        result = ai_router._ProviderResult(
            text="ok",
            provider="deepseek",
            model="deepseek-v4-flash",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            provider_cost_micro_usd=7,
            is_provider_response=True,
        )

        with patch.object(ai_router, "insert_usage_log", return_value={"id": 123}) as usage, \
             patch.object(ai_router, "is_ai_credit_enforcement_enabled", return_value=True), \
             patch.object(ai_router, "charge_logged_ai_usage", return_value={"status": "charged"}) as charge:
            record = ai_router._make_usage_log(
                result,
                company_id=42,
                chatbot_id=7,
                operation_type=ai_router.OPERATION_KNOWLEDGE_REFINEMENT_QUESTIONS,
                attempt_number=1,
            )

        self.assertEqual(record["id"], 123)
        self.assertEqual(
            usage.call_args.kwargs["operation_type"],
            "knowledge_refinement_questions",
        )
        charge.assert_called_once_with(
            123,
            markup_basis_points=None,
            fx_rate_micro_myr_per_usd=None,
        )

    def test_unknown_cost_fails_closed_without_silent_success(self):
        from app.services import ai_router

        result = ai_router._ProviderResult(
            text="ok",
            provider="deepseek",
            model="deepseek-chat",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            provider_cost_micro_usd=None,
            is_provider_response=True,
        )

        with patch.object(ai_router, "insert_usage_log", return_value={"id": 123}), \
             patch.object(ai_router, "is_ai_credit_enforcement_enabled", return_value=True), \
             patch.object(ai_router, "charge_logged_ai_usage", return_value={"status": "unknown_cost"}):
            with self.assertRaises(RuntimeError):
                ai_router._make_usage_log(
                    result,
                    company_id=42,
                    chatbot_id=7,
                    operation_type=ai_router.OPERATION_KNOWLEDGE_REFINEMENT_VERIFICATION,
                    attempt_number=1,
                )

    def test_usage_log_failure_fails_closed_when_enforcement_is_enabled(self):
        from app.services import ai_router

        result = ai_router._ProviderResult(
            text="ok",
            provider="openrouter",
            model="openai/gpt-5.5",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            provider_cost_micro_usd=7,
            is_provider_response=True,
        )

        with patch.object(ai_router, "insert_usage_log", side_effect=RuntimeError("db down")), \
             patch.object(ai_router, "is_ai_credit_enforcement_enabled", return_value=True), \
             patch.object(ai_router, "charge_logged_ai_usage") as charge:
            with self.assertRaises(RuntimeError):
                ai_router._make_usage_log(
                    result,
                    company_id=42,
                    chatbot_id=7,
                    operation_type=ai_router.OPERATION_AI_REPORT,
                    attempt_number=1,
                )

        charge.assert_not_called()

    def test_trial_cloudflare_model_has_supported_pricing(self):
        from app.services.cloudflare_service import extract_usage
        from app.services.ai_access_policy import TRIAL_MODEL
        from app.services.model_catalog import get_models_for_plan

        catalog_values = {
            model["value"] for model in get_models_for_plan("free")["cloudflare"]["models"]
        }
        self.assertEqual(TRIAL_MODEL, "@cf/qwen/qwen3-30b-a3b-fp8")
        self.assertIn(TRIAL_MODEL, catalog_values)
        with patch.dict(os.environ, {"CLOUDFLARE_AI_MODEL_PRICING_JSON": "{}"}):
            usage = extract_usage({
                "id": "trial-cost-test", "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            }, TRIAL_MODEL)
        self.assertEqual(usage["provider_cost_micro_usd"], 39)


class TestBillingActivityLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_html = _read_billing_source()

    def test_recent_activity_has_labels_for_distinct_ai_operations(self):
        expected_labels = [
            ("knowledge_refinement_questions", "Refine Answers"),
            ("knowledge_refinement_verification", "Refine Answers"),
            ("test_scenario_generation", "Test Scenario Generation"),
            ("persona_derivation", "Persona Derivation"),
            ("profile_knowledge_match", "Profile / Knowledge Validation"),
            ("website_knowledge_extraction", "Website Knowledge Training"),
            ("knowledge_graph_extraction", "Knowledge Graph Training"),
        ]

        # The rewritten billing page writes unquoted object keys; the data is
        # identical, so match either quoting style rather than a formatting
        # convention.
        for key, label in expected_labels:
            with self.subTest(label=key):
                self.assertRegex(self.profile_html, re.compile(
                    '"?' + re.escape(key) + '"?[ ]*:[ ]*"' + re.escape(label) + '"'))

        # Same three-tier fallback as before: explicit map, humanised slug,
        # then the generic label - asserted without pinning identifiers.
        self.assertRegex(_fn_body(self.profile_html, "usageLabel"), re.compile(
            r'return\s+\w+\[\w+\]\s*\|\|\s*\w+\(\w+\)\s*\|\|\s*"AI Usage";'))


if __name__ == "__main__":
    unittest.main()
