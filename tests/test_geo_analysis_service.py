import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from app.services.geo_analysis_service import (
    build_findings, calculate_metrics, calculate_rolling_summary, count_mentions, validate_spec,
)
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
        with self.assertRaisesRegex(ValueError, "at most 20 provider executions"):
            validate_spec({
                "brand_name": "Omnexa", "owned_domains": [], "country": "MY", "language": "en",
                "platforms": ["chatgpt", "gemini", "perplexity"],
                "prompts": ["One", "Two", "Three", "Four"], "samples_per_prompt": 2,
            })

    def test_plan_limits_reject_extra_prompts_and_allow_all_platforms(self):
        essential = get_geo_plan_entitlement("essential")
        with self.assertRaisesRegex(ValueError, "at most 2 items"):
            validate_spec({
                "brand_name": "Omnexa", "owned_domains": [], "country": "MY", "language": "en",
                "platforms": ["gemini"], "prompts": ["One", "Two", "Three"], "samples_per_prompt": 1,
            }, essential)
        result = validate_spec({
            "brand_name": "Omnexa", "owned_domains": [], "country": "MY", "language": "en",
            "platforms": ["chatgpt", "gemini", "perplexity"],
            "prompts": ["One"], "samples_per_prompt": 1,
        }, essential)
        self.assertEqual(result["platforms"], ["chatgpt", "gemini", "perplexity"])

    def test_non_callable_surfaces_are_not_supported_analysis_options(self):
        with self.assertRaisesRegex(ValueError, "supported GEO platform"):
            validate_spec({
                "brand_name": "Omnexa", "owned_domains": [], "country": "MY", "language": "en",
                "platforms": ["google_ai_mode"], "prompts": ["One"], "samples_per_prompt": 1,
            }, get_geo_plan_entitlement("essential"))

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
        self.assertEqual(metrics["average_mention_rank"], 1)
        self.assertEqual(metrics["score_breakdown"]["mention"]["weight"], 60)
        self.assertEqual(metrics["score_breakdown"]["mention_rank"]["weight"], 40)
        self.assertLess(metrics["mention_rate_confidence_interval"]["lower"], 100)

    def test_score_uses_only_mention_rate_and_mention_rank(self):
        rows = [{
            "request_status": "complete", "platform": "chatgpt", "brand_mentioned": True,
            "brand_mention_count": 1, "owned_citation_count": 0, "recommendation_position": 2,
            "sentiment": "positive", "competitor_mentions": {}, "prompt_index": 0,
            "citations": [{"url": "https://industry.example/review", "domain": "industry.example"}],
        }]
        metrics = calculate_metrics(rows, prompt_count=1)
        self.assertEqual(metrics["geo_score"], 92)
        self.assertEqual(metrics["mention_rate"], 100)
        self.assertEqual(metrics["average_mention_rank"], 2)
        self.assertEqual(metrics["platform_summary"]["chatgpt"]["score"], 92)
        self.assertNotIn("citation_rate", metrics)

    def test_half_mentions_at_rank_one_scores_seventy(self):
        rows = [
            {"request_status": "complete", "platform": "chatgpt", "brand_mentioned": True,
             "brand_mention_count": 1, "recommendation_position": 1},
            {"request_status": "complete", "platform": "chatgpt", "brand_mentioned": False,
             "brand_mention_count": 0, "recommendation_position": None},
        ]
        metrics = calculate_metrics(rows, prompt_count=2)
        self.assertEqual(metrics["geo_score"], 70)
        self.assertEqual(metrics["mention_rate"], 50)
        self.assertEqual(metrics["average_mention_rank"], 1)
        self.assertEqual(metrics["sample_quality"], "insufficient")

    def test_rolling_summary_produces_middle_rate_from_comparable_scans(self):
        current = calculate_metrics([{
            "request_status": "complete", "platform": "chatgpt", "brand_mentioned": True,
            "recommendation_position": 1,
        }])
        prior = [
            {"id": "older-1", "brand_name": "Omnexa", "country": "MY", "language": "en",
             "metrics": calculate_metrics([{
                 "request_status": "complete", "platform": "chatgpt", "brand_mentioned": False,
                 "recommendation_position": None,
             }])},
            {"id": "older-2", "brand_name": "Omnexa", "country": "MY", "language": "en",
             "metrics": calculate_metrics([{
                 "request_status": "complete", "platform": "chatgpt", "brand_mentioned": True,
                 "recommendation_position": 3,
             }])},
        ]
        rolling = calculate_rolling_summary(
            current, prior, {"brand_name": "Omnexa", "country": "MY", "language": "en"}
        )["platform_summary"]["chatgpt"]
        self.assertEqual(rolling["mention_rate"], 66.67)
        self.assertEqual(rolling["average_mention_rank"], 2)
        self.assertEqual(rolling["sample_quality"], "sufficient")
        self.assertEqual(rolling["analysis_count"], 3)

    def test_findings_return_four_focused_action_pillars_for_each_platform(self):
        rows = [{
            "request_status": "complete", "platform": "gemini", "prompt": "Best automation tool?",
            "brand_mentioned": False, "brand_mention_count": 0, "owned_citation_count": 0,
            "competitor_mentions": {"Rival": 2}, "citations": [
                {"url": "https://review.example/best", "domain": "review.example"}
            ],
        }]
        findings = build_findings(rows, {"owned_domains": ["omnexa.my"]})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["platform"], "gemini")
        self.assertEqual(findings[0]["mention_rate"], 0)
        self.assertEqual(len(findings[0]["actions"]), 4)
        self.assertEqual(
            [pillar["key"] for pillar in findings[0]["action_pillars"]],
            ["website", "authority_posts", "local_context", "crawler_technical"],
        )
        self.assertIn("Google Business Profile", findings[0]["actions"][1])
        self.assertIn("nearby landmarks", findings[0]["actions"][2])
        self.assertIn("sitemap.xml", findings[0]["actions"][3])
        self.assertEqual(findings[0]["evidence"][0]["prompt"], "Best automation tool?")

    def test_owned_domain_and_citations_do_not_change_mention_score_or_plan(self):
        rows = [{
            "request_status": "complete", "platform": "perplexity", "prompt": "Best tool?",
            "brand_mentioned": True, "brand_mention_count": 1, "owned_citation_count": 0,
            "recommendation_position": 1, "sentiment": "positive", "competitor_mentions": {},
            "prompt_index": 0, "citations": [{"domain": "publisher.example"}],
        }]
        findings = build_findings(rows, {"owned_domains": []})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["platform"], "perplexity")
        self.assertEqual(len(findings[0]["actions"]), 4)
        self.assertEqual(findings[0]["priority"], "observe")
        self.assertEqual(calculate_metrics(rows, 1)["geo_score"], 100)

    def test_mention_rank_and_sentiment_require_exact_alias_mentions(self):
        from app.services.geo_analysis_service import enrich

        result = enrich({"request_status": "complete", "raw_response": "The said tool is best.",
                         "citations": [], "platform": "chatgpt"},
                        {"aliases": ["AI"], "competitors": [], "owned_domains": [],
                         "country": "MY", "language": "en"},
                        prompt="Which tool?", prompt_index=0, sample_index=0)
        self.assertFalse(result["brand_mentioned"])
        self.assertIsNone(result["recommendation_position"])
        self.assertEqual(result["sentiment"], "neutral")

    def test_mention_rank_follows_first_entity_appearance(self):
        from app.services.geo_analysis_service import enrich

        result = enrich({"request_status": "complete", "raw_response": "Rival is common. Omnexa is another option.",
                         "citations": [], "platform": "chatgpt"},
                        {"aliases": ["Omnexa"], "competitors": ["Rival"], "owned_domains": [],
                         "country": "MY", "language": "en"},
                        prompt="Which tool?", prompt_index=0, sample_index=0)
        self.assertTrue(result["brand_mentioned"])
        self.assertEqual(result["recommendation_position"], 2)

    def test_numbered_answer_list_provides_rank_without_competitor_configuration(self):
        from app.services.geo_analysis_service import enrich

        result = enrich({"request_status": "complete",
                         "raw_response": "1. Alpha\n2. Beta\n3. Omnexa\n4. Delta",
                         "citations": [], "platform": "chatgpt", "provider_metadata": {}},
                        {"aliases": ["Omnexa"], "competitors": [], "owned_domains": [],
                         "country": "MY", "language": "en"},
                        prompt="Which tool?", prompt_index=0, sample_index=0)
        self.assertEqual(result["recommendation_position"], 3)
        self.assertEqual(result["provider_metadata"]["mention_rank_method"], "explicit_result_list")

    def test_unopposed_prose_mention_is_not_invented_as_rank_one(self):
        from app.services.geo_analysis_service import enrich

        result = enrich({"request_status": "complete", "raw_response": "Omnexa is a useful option.",
                         "citations": [], "platform": "chatgpt", "provider_metadata": {}},
                        {"aliases": ["Omnexa"], "competitors": [], "owned_domains": [],
                         "country": "MY", "language": "en"},
                        prompt="Which tool?", prompt_index=0, sample_index=0)
        self.assertTrue(result["brand_mentioned"])
        self.assertIsNone(result["recommendation_position"])
        self.assertEqual(result["provider_metadata"]["mention_rank_method"], "mention_without_rank_evidence")


class GeoEntitlementTests(unittest.TestCase):
    def test_all_paid_plan_codes_allow_geo_without_rollout_flag(self):
        for code in ("essential", "advanced", "pro"):
            with self.subTest(code=code), patch(
                "app.services.billing_guard._resolve_company_subscription",
                return_value={"plan": {"code": code, "feature_flags": {}}},
            ):
                self.assertTrue(can_use_geo_analysis(42))

    def test_paid_plans_receive_cost_bounded_contracts(self):
        expected = {"essential": (10, 2, 5), "advanced": (40, 3, 5), "pro": (120, 4, 5)}
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
        self.assertEqual(body["tool_choice"], "required")
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

    def test_perplexity_uses_direct_official_api(self):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {"output_text": "Answer", "model": "openai/gpt-5.6-sol",
            "output": [{"type": "search_results", "results": [{"url": "https://example.com/source"}]}],
            "usage": {"cost": {"total_cost": 0.004}}}
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-perplexity-key"}), patch(
            "app.services.geo_provider_service.requests.post", return_value=response
        ) as post:
            result = geo_provider_service.collect("perplexity", "Prompt", "MY", "en")
        self.assertEqual(post.call_args.args[0], "https://api.perplexity.ai/v1/agent")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-perplexity-key")
        self.assertEqual(post.call_args.kwargs["json"]["tools"], [{"type": "web_search"}])
        self.assertEqual(result["citations"][0]["domain"], "example.com")
        self.assertEqual(result["cost_usd"], 0.004)

    def test_claude_uses_anthropic_native_web_search_tool(self):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {"id": "msg-1", "content": [{"type": "text", "text": "Answer",
            "citations": [{"url": "https://anthropic.example/source"}]}]}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-anthropic-key"}), patch(
            "app.services.geo_provider_service.requests.post", return_value=response
        ) as post:
            result = geo_provider_service.collect("claude", "Prompt", "MY", "en")
        self.assertEqual(post.call_args.args[0], "https://api.anthropic.com/v1/messages")
        self.assertEqual(post.call_args.kwargs["json"]["tools"][0]["type"], "web_search_20250305")
        self.assertEqual(result["request_status"], "complete")

    def test_openrouter_comparison_pins_openai_native_search_without_fallback(self):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {"choices": [{"message": {"content": "Answer"}}]}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter-key",
                                     "OPENAI_SEARCH_MODEL": "gpt-4.1-mini",
                                     "OPENROUTER_OPENAI_SEARCH_MODEL": "openai/gpt-5-mini"}), patch(
            "app.services.geo_provider_service.requests.post", return_value=response
        ) as post:
            result = geo_provider_service._openrouter_openai("Prompt", "MY", "en")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "openai/gpt-4.1-mini")
        self.assertEqual(result["model"], "gpt-4.1-mini")
        self.assertEqual(result["provider_metadata"]["request_model"], "openai/gpt-4.1-mini")
        self.assertEqual(body["tools"][0]["parameters"]["engine"], "native")
        self.assertNotIn("tool_choice", body)
        self.assertNotIn("reasoning", body)
        self.assertEqual(body["max_completion_tokens"], geo_provider_service._max_output_tokens())
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["provider"], {"order": ["openai"], "allow_fallbacks": False,
                                             "require_parameters": True})
        self.assertEqual(result["provider_metadata"]["route"], ["Omnexa", "OpenRouter", "OpenAI"])

    def test_openrouter_uses_low_reasoning_only_for_reasoning_models(self):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {"choices": [{"message": {"content": "Answer"}}]}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter-key",
                                     "OPENAI_SEARCH_MODEL": "gpt-5-mini"}), patch(
            "app.services.geo_provider_service.requests.post", return_value=response
        ) as post:
            geo_provider_service._openrouter_openai("Prompt", "MY", "en")
        self.assertEqual(post.call_args.kwargs["json"]["reasoning"], {"effort": "low"})

    def test_openrouter_empty_completion_is_reported_as_failure(self):
        response = MagicMock()
        response.ok = True
        response.json.return_value = {"id": "gen-empty", "choices": [{
            "finish_reason": "length", "message": {"content": ""}}],
            "usage": {"cost": 0.001, "completion_tokens": 700}}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter-key"}), patch(
            "app.services.geo_provider_service.requests.post", return_value=response
        ):
            result = geo_provider_service._openrouter_openai("Prompt", "MY", "en")
        self.assertEqual(result["request_status"], "failed")
        self.assertEqual(result["error_code"], "provider_output_truncated")
        self.assertEqual(result["provider_metadata"]["finish_reason"], "length")
        self.assertEqual(result["cost_usd"], 0.001)

    def test_removed_surfaces_cannot_be_misrepresented_as_api_calls(self):
        for platform in ("google_ai_mode", "microsoft_copilot"):
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "does not expose"):
                geo_provider_service.collect(platform, "Prompt", "MY", "en")

    def test_output_token_budget_is_bounded(self):
        with patch.dict(os.environ, {"GEO_MAX_OUTPUT_TOKENS": "999999"}):
            self.assertEqual(geo_provider_service._max_output_tokens(), 1500)
        with patch.dict(os.environ, {"GEO_MAX_OUTPUT_TOKENS": "1"}):
            self.assertEqual(geo_provider_service._max_output_tokens(), 150)


if __name__ == "__main__":
    unittest.main()
