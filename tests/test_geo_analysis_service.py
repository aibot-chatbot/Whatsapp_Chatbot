import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from app.services.geo_analysis_service import build_findings, calculate_metrics, count_mentions, validate_spec
from app.services import geo_provider_service
from app.services.billing_guard import BillingLimitError, can_use_geo_analysis, get_company_geo_entitlement
from app.services.geo_plan_service import get_geo_plan_entitlement


class GeoMetricTests(unittest.TestCase):
    def test_validate_spec_normalises_market_and_brand_alias(self):
        result = validate_spec({
            "brand_name": "Omnexa", "aliases": ["Omnexa AI"], "competitors": ["Other"],
            "owned_domains": ["https://www.omnexa.my/path"], "country": "my", "language": "ms",
            "platforms": ["chatgpt", "perplexity"], "prompts": ["Best chatbot?"], "samples_per_prompt": 2,
        })
        self.assertEqual(result["aliases"], ["Omnexa", "Omnexa AI"])
        self.assertEqual(result["owned_domains"], ["omnexa.my"])
        self.assertEqual(result["country"], "MY")

    def test_exact_mentions_do_not_double_count_overlapping_aliases(self):
        self.assertEqual(count_mentions("Omnexa AI recommends Omnexa.", ["Omnexa", "Omnexa AI"]), 2)
        self.assertEqual(count_mentions("Omnexable", ["Omnexa"]), 0)

    def test_analysis_rejects_unbounded_provider_fanout(self):
        with self.assertRaisesRegex(ValueError, "at most 12 provider executions"):
            validate_spec({
                "brand_name": "Omnexa", "owned_domains": [], "country": "MY", "language": "en",
                "platforms": ["chatgpt", "gemini", "perplexity"],
                "prompts": ["One", "Two", "Three"], "samples_per_prompt": 2,
            })

    def test_plan_limits_reject_extra_prompts_and_allow_all_platforms(self):
        essential = get_geo_plan_entitlement("essential")
        with self.assertRaisesRegex(ValueError, "at most 1 items"):
            validate_spec({
                "brand_name": "Omnexa", "owned_domains": [], "country": "MY", "language": "en",
                "platforms": ["gemini"], "prompts": ["One", "Two"], "samples_per_prompt": 1,
            }, essential)
        result = validate_spec({
            "brand_name": "Omnexa", "owned_domains": [], "country": "MY", "language": "en",
            "platforms": ["chatgpt", "gemini", "perplexity"],
            "prompts": ["One"], "samples_per_prompt": 1,
        }, essential)
        self.assertEqual(result["platforms"], ["chatgpt", "gemini", "perplexity"])

    def test_metrics_exclude_failed_requests_from_rate_denominator(self):
        rows = [
            {"request_status": "complete", "brand_mentioned": True, "brand_mention_count": 1,
             "owned_citation_count": 1, "recommendation_position": 1, "sentiment": "positive",
             "competitor_mentions": {"Other": 1}, "prompt_index": 0,
             "citations": [{"citation_position": 2}]},
            {"request_status": "failed", "brand_mentioned": False, "brand_mention_count": 0,
             "owned_citation_count": 0, "recommendation_position": None, "sentiment": "neutral",
             "competitor_mentions": {}, "prompt_index": 1, "citations": []},
        ]
        metrics = calculate_metrics(rows, prompt_count=2)
        self.assertEqual(metrics["geo_score"], 100)
        self.assertEqual(metrics["mention_rate"], 100)
        self.assertEqual(metrics["share_of_voice"], 50)
        self.assertEqual(metrics["prompt_coverage"], 50)
        self.assertEqual(metrics["average_citation_position"], 2)
        self.assertEqual(metrics["owned_citation_rate"], 100)
        self.assertEqual(metrics["sentiment_distribution"], {"positive": 1, "neutral": 0, "negative": 0})
        self.assertLess(metrics["mention_rate_confidence_interval"]["lower"], 100)

    def test_third_party_citation_earns_citation_points_without_owned_domain(self):
        rows = [{
            "request_status": "complete", "platform": "chatgpt", "brand_mentioned": True,
            "brand_mention_count": 1, "owned_citation_count": 0, "recommendation_position": 1,
            "sentiment": "positive", "competitor_mentions": {}, "prompt_index": 0,
            "citations": [{"url": "https://industry.example/review", "domain": "industry.example"}],
        }]
        metrics = calculate_metrics(rows, prompt_count=1)
        self.assertEqual(metrics["geo_score"], 100)
        self.assertEqual(metrics["citation_rate"], 100)
        self.assertEqual(metrics["owned_citation_rate"], 0)
        self.assertEqual(metrics["score_breakdown"]["citation"]["points"], 30)
        self.assertEqual(metrics["platform_summary"]["chatgpt"]["citation_rate"], 100)
        self.assertEqual(metrics["platform_summary"]["chatgpt"]["owned_citation_rate"], 0)

    def test_70_is_valid_only_when_an_answer_has_no_citations(self):
        rows = [{
            "request_status": "complete", "platform": "chatgpt", "brand_mentioned": True,
            "brand_mention_count": 1, "owned_citation_count": 0, "recommendation_position": 1,
            "sentiment": "positive", "competitor_mentions": {}, "prompt_index": 0,
            "citations": [],
        }]
        metrics = calculate_metrics(rows, prompt_count=1)
        self.assertEqual(metrics["geo_score"], 70)
        self.assertEqual(metrics["citation_rate"], 0)
        self.assertEqual(metrics["score_breakdown"]["citation"]["points"], 0)

    def test_findings_return_actions_and_evidence_from_measured_results(self):
        rows = [{
            "request_status": "complete", "platform": "gemini", "prompt": "Best automation tool?",
            "brand_mentioned": False, "brand_mention_count": 0, "owned_citation_count": 0,
            "competitor_mentions": {"Rival": 2}, "citations": [
                {"url": "https://review.example/best", "domain": "review.example"}
            ],
        }]
        findings = build_findings(rows, {"owned_domains": ["omnexa.my"]})
        by_type = {item["type"]: item for item in findings}
        self.assertIn("visibility_gap", by_type)
        self.assertIn("competitor_gap", by_type)
        self.assertIn("source_opportunity", by_type)
        self.assertTrue(by_type["visibility_gap"]["actions"])
        self.assertEqual(by_type["visibility_gap"]["evidence"][0]["prompt"], "Best automation tool?")
        self.assertEqual(by_type["source_opportunity"]["evidence"][0]["domains"], ["review.example"])

    def test_missing_owned_domain_is_setup_advice_not_a_score_penalty(self):
        rows = [{
            "request_status": "complete", "platform": "perplexity", "prompt": "Best tool?",
            "brand_mentioned": True, "brand_mention_count": 1, "owned_citation_count": 0,
            "recommendation_position": 1, "sentiment": "positive", "competitor_mentions": {},
            "prompt_index": 0, "citations": [{"domain": "publisher.example"}],
        }]
        findings = build_findings(rows, {"owned_domains": []})
        setup = next(item for item in findings if item["type"] == "owned_domain_setup")
        self.assertIn("does not reduce the GEO score", setup["summary"])
        self.assertEqual(calculate_metrics(rows, 1)["geo_score"], 100)

    def test_recommendation_and_sentiment_require_exact_alias_mentions(self):
        from app.services.geo_analysis_service import enrich

        result = enrich({"request_status": "complete", "raw_response": "The said tool is best.",
                         "citations": [], "platform": "chatgpt"},
                        {"aliases": ["AI"], "competitors": [], "owned_domains": [],
                         "country": "MY", "language": "en"},
                        prompt="Which tool?", prompt_index=0, sample_index=0)
        self.assertFalse(result["brand_mentioned"])
        self.assertIsNone(result["recommendation_position"])
        self.assertEqual(result["sentiment"], "neutral")


class GeoEntitlementTests(unittest.TestCase):
    def test_all_paid_plan_codes_allow_geo_without_rollout_flag(self):
        for code in ("essential", "advanced", "pro"):
            with self.subTest(code=code), patch(
                "app.services.billing_guard._resolve_company_subscription",
                return_value={"plan": {"code": code, "feature_flags": {}}},
            ):
                self.assertTrue(can_use_geo_analysis(42))

    def test_paid_plans_receive_cost_bounded_contracts(self):
        expected = {"essential": (10, 1, 3), "advanced": (40, 2, 3), "pro": (120, 4, 3)}
        for code, values in expected.items():
            with self.subTest(code=code), patch(
                "app.services.billing_guard._resolve_company_subscription",
                return_value={"plan": {"code": code}},
            ):
                entitlement = get_company_geo_entitlement(42)
                self.assertEqual((entitlement["monthly_executions"], entitlement["prompts_per_analysis"],
                                  len(entitlement["platforms"])), values)

    def test_free_plan_cannot_use_geo(self):
        with patch("app.services.billing_guard._resolve_company_subscription",
                   return_value={"plan": {"code": "free", "feature_flags": {}}}), \
             self.assertRaises(BillingLimitError) as error:
            can_use_geo_analysis(42)
        self.assertEqual(error.exception.code, "feature_not_available")


class GeoProviderTests(unittest.TestCase):
    def test_openai_request_carries_country_language_and_native_citation(self):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {
            "id": "response-1", "output_text": "Omnexa is recommended.",
            "output": [{"type": "message", "content": [{"text": "Omnexa is recommended.",
                        "annotations": [{"url_citation": {"url": "https://omnexa.my/page", "title": "Omnexa"}}]}]}],
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "app.services.geo_provider_service.requests.post", return_value=response
        ) as post:
            result = geo_provider_service.collect("chatgpt", "Recommend a chatbot", "MY", "ms")
        body = post.call_args.kwargs["json"]
        self.assertIn("Bahasa Melayu", body["instructions"])
        self.assertEqual(body["tools"][0]["user_location"]["country"], "MY")
        self.assertEqual(body["max_output_tokens"], 700)
        self.assertTrue(result["is_search_experience"])
        self.assertEqual(result["citations"][0]["domain"], "omnexa.my")

    def test_missing_provider_key_is_a_visible_failed_execution(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            result = geo_provider_service.collect("chatgpt", "Prompt", "MY", "en")
        self.assertEqual(result["request_status"], "failed")
        self.assertEqual(result["error_code"], "provider_not_configured")

    def test_gemini_key_is_sent_in_header_not_url(self):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Answer"}]}}]}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}), patch(
            "app.services.geo_provider_service.requests.post", return_value=response
        ) as post:
            result = geo_provider_service.collect("gemini", "Prompt", "MY", "en")
        self.assertNotIn("test-gemini-key", post.call_args.args[0])
        self.assertNotIn("?key=", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-gemini-key")
        self.assertEqual(result["request_status"], "complete")

    def test_output_token_budget_is_bounded(self):
        with patch.dict(os.environ, {"GEO_MAX_OUTPUT_TOKENS": "999999"}):
            self.assertEqual(geo_provider_service._max_output_tokens(), 1500)
        with patch.dict(os.environ, {"GEO_MAX_OUTPUT_TOKENS": "1"}):
            self.assertEqual(geo_provider_service._max_output_tokens(), 150)


if __name__ == "__main__":
    unittest.main()
