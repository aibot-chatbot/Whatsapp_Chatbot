"""Customer-billed AI accounting contract regressions."""

import inspect
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


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

    def test_trial_deepseek_model_has_supported_pricing(self):
        from app.services import ai_router
        from app.services.ai_access_policy import TRIAL_MODEL
        from app.services.model_catalog import MODEL_CATALOG

        catalog_values = {
            model["value"]
            for model in MODEL_CATALOG["deepseek"]["models"]
        }

        self.assertEqual(TRIAL_MODEL, "deepseek-v4-flash")
        self.assertIn(TRIAL_MODEL, catalog_values)
        self.assertIn(TRIAL_MODEL, ai_router._SUPPORTED_DEEPSEEK_MODELS)


class TestBillingActivityLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_html = (REPO_ROOT / "frontend" / "profile.html").read_text(
            encoding="utf-8"
        )

    def test_recent_activity_has_labels_for_distinct_ai_operations(self):
        expected_labels = {
            '"knowledge_refinement_questions": "Refine Answers"',
            '"knowledge_refinement_verification": "Refine Answers"',
            '"test_scenario_generation": "Test Scenario Generation"',
            '"persona_derivation": "Persona Derivation"',
            '"profile_knowledge_match": "Profile / Knowledge Validation"',
            '"website_knowledge_extraction": "Website Knowledge Training"',
            '"knowledge_graph_extraction": "Knowledge Graph Training"',
        }

        for label in expected_labels:
            with self.subTest(label=label):
                self.assertIn(label, self.profile_html)

        self.assertIn(
            'return usageLabelMap[usageType] || formatOperationDisplayName(usageType) || "AI Usage";',
            self.profile_html,
        )


if __name__ == "__main__":
    unittest.main()
