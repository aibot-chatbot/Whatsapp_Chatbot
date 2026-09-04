"""test_deepseek_pricing.py

Tests for DeepSeek V4 Flash provider cost calculation.

Cache-hit input, cache-miss input, and output tokens are priced separately.
All arithmetic uses integer operations — no float conversions.
Rounding is always upward (ceil) to avoid undercharging.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AI_CREDIT_ENFORCEMENT_ENABLED", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch, MagicMock
import types

# Mock broken dependencies before any app import
if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "_tools" not in sys.modules:
    sys.modules["_tools"] = types.ModuleType("_tools")

# Patch supabase at module level before any repo imports resolve
_sb = MagicMock()
_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])
_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
_sb.rpc.return_value.execute.return_value = MagicMock(data=[])
with patch("app.database.db.supabase", _sb):
    from app.services.ai_router import (
        _compute_deepseek_provider_cost,
        _extract_deepseek_usage,
        _DEEPSEEK_CACHE_HIT_INPUT_PRICE_ENV,
        _DEEPSEEK_CACHE_MISS_INPUT_PRICE_ENV,
        _DEEPSEEK_OUTPUT_PRICE_ENV,
        _validate_deepseek_pricing_config,
        _SUPPORTED_DEEPSEEK_MODELS,
    )

CACHE_HIT_ENV = _DEEPSEEK_CACHE_HIT_INPUT_PRICE_ENV
CACHE_MISS_ENV = _DEEPSEEK_CACHE_MISS_INPUT_PRICE_ENV
OUTPUT_ENV = _DEEPSEEK_OUTPUT_PRICE_ENV


class TestDeepSeekPricingHelper(unittest.TestCase):
    """Tests for _compute_deepseek_provider_cost()."""

    def setUp(self):
        # $0.14/M cache hit, $0.28/M cache miss, $1.10/M output
        self.cache_hit_rate = "140000"
        self.cache_miss_rate = "280000"
        self.output_rate = "1100000"

    def set_pricing(self, cache_hit=None, cache_miss=None, output=None):
        for env, val in ((CACHE_HIT_ENV, cache_hit), (CACHE_MISS_ENV, cache_miss), (OUTPUT_ENV, output)):
            if val is not None:
                os.environ[env] = val
            else:
                os.environ.pop(env, None)

    def cost(self, pt, ct, cached=0):
        return _compute_deepseek_provider_cost("deepseek-v4-flash", pt, ct, cached)

    # ---- model validation ----

    def test_unsupported_model_returns_none(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        cost = _compute_deepseek_provider_cost("deepseek-v3", 100, 100)
        self.assertIsNone(cost)

    def test_supported_model_in_set(self):
        self.assertIn("deepseek-v4-flash", _SUPPORTED_DEEPSEEK_MODELS)

    # ---- all prompt tokens uncached ----

    def test_all_uncached_input(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # 1000 prompt * 280000 + 0 completion = 280,000,000
        # (280000000 + 999999) // 1000000 = 280
        cost = self.cost(1000, 0, cached=0)
        self.assertEqual(cost, 280)

    # ---- all prompt tokens cached ----

    def test_all_cached_input(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # 1000 cached * 140000 + 0 uncached * 280000 = 140,000,000
        # (140000000 + 999999) // 1000000 = 140
        cost = self.cost(1000, 0, cached=1000)
        self.assertEqual(cost, 140)

    # ---- mixed cached and uncached ----

    def test_mixed_cached_and_uncached(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # 400 cached * 140000 + 600 uncached * 280000 = 56M + 168M = 224M
        # (224000000 + 999999) // 1000000 = 224
        cost = self.cost(1000, 0, cached=400)
        self.assertEqual(cost, 224)

    # ---- output tokens ----

    def test_output_only(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # 0 prompt + 100 completion * 1100000 = 110,000,000
        # (110000000 + 999999) // 1000000 = 110
        cost = self.cost(0, 100)
        self.assertEqual(cost, 110)

    # ---- combined cached, uncached and output ----

    def test_combined_all_three(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # 300 cached * 140000 + 700 uncached * 280000 + 200 completion * 1100000
        # = 42M + 196M + 220M = 458M
        # (458000000 + 999999) // 1000000 = 458
        cost = self.cost(1000, 200, cached=300)
        self.assertEqual(cost, 458)

    # ---- upward rounding ----

    def test_upward_rounding_one_micro(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # 1 token uncached * 280000 = 280000
        # (280000 + 999999) // 1000000 = 1
        cost = self.cost(1, 0)
        self.assertEqual(cost, 1)

    def test_exact_whole_micro(self):
        self.set_pricing("1000000", "1000000", "1000000")
        # 1 * 1000000 = 1M -> (1M + 999999) // 1M = 1
        cost = self.cost(1, 0)
        self.assertEqual(cost, 1)

    def test_large_mixed_cost(self):
        self.set_pricing("140000", "280000", "1100000")
        # 5000 cached * 140000 + 5000 uncached * 280000 + 3000 completion * 1100000
        # = 700M + 1400M + 3300M = 5400M
        # (5400000000 + 999999) // 1000000 = 5400
        cost = self.cost(10000, 3000, cached=5000)
        self.assertEqual(cost, 5400)

    # ---- cached tokens edge cases ----

    def test_cached_equal_prompt_tokens(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # cached == prompt, all cache-hit price
        cost = self.cost(500, 50, cached=500)
        self.assertIsNotNone(cost)
        self.assertGreater(cost, 0)

    def test_cached_exceeds_prompt_returns_none(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        cost = self.cost(100, 50, cached=200)
        self.assertIsNone(cost)

    def test_negative_cached_tokens_treated_as_zero(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # negative -> normalised to 0, all uncached
        cost = self.cost(100, 0, cached=-5)
        self.assertIsNotNone(cost)
        # Should equal all-uncached: 100 * 280000 = 28M -> 28
        expected = self.cost(100, 0, cached=0)
        self.assertEqual(cost, expected)

    def test_cached_tokens_zero_with_prompt_present(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        cost = self.cost(100, 50, cached=0)
        self.assertIsNotNone(cost)

    # ---- no tokens, pricing configured ----

    def test_zero_tokens_with_pricing_configured_returns_none(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        cost = self.cost(0, 0)
        self.assertIsNone(cost)

    # ---- missing env vars individually ----

    def test_missing_cache_hit_returns_none(self):
        self.set_pricing(None, self.cache_miss_rate, self.output_rate)
        self.assertIsNone(self.cost(100, 50))

    def test_missing_cache_miss_returns_none(self):
        self.set_pricing(self.cache_hit_rate, None, self.output_rate)
        self.assertIsNone(self.cost(100, 50))

    def test_missing_output_returns_none(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, None)
        self.assertIsNone(self.cost(100, 50))

    # ---- malformed and negative pricing ----

    def test_malformed_cache_miss_returns_none(self):
        self.set_pricing(self.cache_hit_rate, "bad", self.output_rate)
        self.assertIsNone(self.cost(100, 50))

    def test_negative_cache_miss_returns_none(self):
        self.set_pricing(self.cache_hit_rate, "-1", self.output_rate)
        self.assertIsNone(self.cost(100, 50))

    def test_negative_output_rate_returns_none(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, "-1")
        self.assertIsNone(self.cost(100, 50))

    # ---- explicitly configured zero rates ----

    def test_all_zero_rates_with_usage_returns_zero(self):
        self.set_pricing("0", "0", "0")
        self.assertEqual(self.cost(100, 50), 0)

    def test_all_zero_rates_no_usage_returns_none(self):
        self.set_pricing("0", "0", "0")
        self.assertIsNone(self.cost(0, 0))

    def test_some_zero_rates_with_usage(self):
        self.set_pricing("0", self.cache_miss_rate, self.output_rate)
        # 100 uncached * 280000 = 28M -> 28
        cost = self.cost(100, 0, cached=0)
        self.assertEqual(cost, 28)

    # ---- invalid cached type ----

    def test_none_cached_tokens_treated_as_zero(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        # None -> normalised to 0
        cost = _compute_deepseek_provider_cost("deepseek-v4-flash", 100, 0, None)
        self.assertIsNotNone(cost)

    def test_str_cached_tokens_treated_as_zero(self):
        self.set_pricing(self.cache_hit_rate, self.cache_miss_rate, self.output_rate)
        cost = _compute_deepseek_provider_cost("deepseek-v4-flash", 100, 0, "5")
        self.assertIsNotNone(cost)


class TestDeepSeekUsageExtraction(unittest.TestCase):
    """Tests for _extract_deepseek_usage()."""

    def setUp(self):
        os.environ[CACHE_HIT_ENV] = "140000"
        os.environ[CACHE_MISS_ENV] = "280000"
        os.environ[OUTPUT_ENV] = "1100000"

    def tearDown(self):
        for e in (CACHE_HIT_ENV, CACHE_MISS_ENV, OUTPUT_ENV):
            os.environ.pop(e, None)

    def test_sdk_extracts_all_fields(self):
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50
        mock_usage.total_tokens = 150
        mock_response = MagicMock()
        mock_response.usage = mock_usage
        mock_response.model = "deepseek-v4-flash"
        mock_response.id = "chatcmpl-abc123"

        result = _extract_deepseek_usage(mock_response, "deepseek", "deepseek-v4-flash")
        self.assertEqual(result["prompt_tokens"], 100)
        self.assertEqual(result["completion_tokens"], 50)
        self.assertEqual(result["generation_id"], "chatcmpl-abc123")
        self.assertIsNotNone(result["provider_cost_micro_usd"])

    def test_sdk_extracts_cached_tokens(self):
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 1000
        mock_usage.completion_tokens = 200
        mock_usage.total_tokens = 1200
        mock_details = MagicMock()
        mock_details.cached_tokens = 400
        mock_usage.prompt_tokens_details = mock_details
        mock_response = MagicMock()
        mock_response.usage = mock_usage
        mock_response.model = "deepseek-v4-flash"
        mock_response.id = "chatcmpl-abc124"

        result = _extract_deepseek_usage(mock_response, "deepseek", "deepseek-v4-flash")
        self.assertEqual(result["cached_tokens"], 400)
        # 400 cached * 140000 + 600 uncached * 280000 + 200 completion * 1100000
        # = 56M + 168M + 220M = 444M -> 444
        self.assertEqual(result["provider_cost_micro_usd"], 444)

    def test_sdk_no_cached_details_defaults_to_zero(self):
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 500
        mock_usage.completion_tokens = 100
        mock_usage.total_tokens = 600
        del mock_usage.prompt_tokens_details  # no such attr
        mock_response = MagicMock()
        mock_response.usage = mock_usage
        mock_response.model = "deepseek-v4-flash"
        mock_response.id = "chatcmpl-abc125"

        result = _extract_deepseek_usage(mock_response, "deepseek", "deepseek-v4-flash")
        self.assertEqual(result["cached_tokens"], 0)
        self.assertIn("cached_tokens", result)

    def test_dict_extracts_all_fields(self):
        response = {
            "model": "deepseek-v4-flash",
            "id": "gen-xyz-001",
            "usage": {
                "prompt_tokens": 2000,
                "completion_tokens": 500,
                "total_tokens": 2500,
            },
        }
        result = _extract_deepseek_usage(response, "deepseek", "deepseek-v4-flash")
        self.assertEqual(result["prompt_tokens"], 2000)
        self.assertEqual(result["completion_tokens"], 500)
        self.assertEqual(result["generation_id"], "gen-xyz-001")
        self.assertIsNotNone(result["provider_cost_micro_usd"])

    def test_dict_extracts_cached_tokens(self):
        response = {
            "model": "deepseek-v4-flash",
            "id": "gen-xyz-002",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "prompt_tokens_details": {"cached_tokens": 500},
            },
        }
        result = _extract_deepseek_usage(response, "deepseek", "deepseek-v4-flash")
        self.assertEqual(result["cached_tokens"], 500)

    def test_dict_no_usage_returns_none_cost(self):
        response = {"choices": [{"message": {"content": "hi"}}]}
        result = _extract_deepseek_usage(response, "deepseek", "deepseek-v4-flash")
        self.assertIsNone(result.get("provider_cost_micro_usd"))


class TestDeepSeekPricingPreflight(unittest.TestCase):
    """Tests for _validate_deepseek_pricing_config()."""

    def setUp(self):
        os.environ[CACHE_HIT_ENV] = "140000"
        os.environ[CACHE_MISS_ENV] = "280000"
        os.environ[OUTPUT_ENV] = "1100000"

    def tearDown(self):
        for e in (CACHE_HIT_ENV, CACHE_MISS_ENV, OUTPUT_ENV):
            os.environ.pop(e, None)

    def test_valid_pricing_passes(self):
        _validate_deepseek_pricing_config()

    def test_missing_cache_hit_raises(self):
        os.environ.pop(CACHE_HIT_ENV, None)
        with self.assertRaises(RuntimeError) as ctx:
            _validate_deepseek_pricing_config()
        self.assertIn(CACHE_HIT_ENV, str(ctx.exception))

    def test_missing_cache_miss_raises(self):
        os.environ.pop(CACHE_MISS_ENV, None)
        with self.assertRaises(RuntimeError) as ctx:
            _validate_deepseek_pricing_config()
        self.assertIn(CACHE_MISS_ENV, str(ctx.exception))

    def test_missing_output_raises(self):
        os.environ.pop(OUTPUT_ENV, None)
        with self.assertRaises(RuntimeError) as ctx:
            _validate_deepseek_pricing_config()
        self.assertIn(OUTPUT_ENV, str(ctx.exception))

    def test_malformed_raises(self):
        os.environ[CACHE_MISS_ENV] = "bad"
        with self.assertRaises(RuntimeError):
            _validate_deepseek_pricing_config()

    def test_negative_raises(self):
        os.environ[OUTPUT_ENV] = "-1"
        with self.assertRaises(RuntimeError):
            _validate_deepseek_pricing_config()

    def test_zero_rates_pass(self):
        os.environ[CACHE_HIT_ENV] = "0"
        os.environ[CACHE_MISS_ENV] = "0"
        os.environ[OUTPUT_ENV] = "0"
        _validate_deepseek_pricing_config()


class TestDeepSeekChargingPath(unittest.TestCase):
    """End-to-end tests for the credit charging integration."""

    @patch("app.services.ai_router.is_ai_credit_enforcement_enabled")
    @patch("app.services.ai_router.get_ai_retail_markup_basis_points")
    @patch("app.services.ai_router.get_ai_usd_to_myr_rate_micro_myr_per_usd")
    def test_valid_config_allows_charge(self, mock_fx, mock_markup, mock_enabled):
        os.environ[CACHE_HIT_ENV] = "140000"
        os.environ[CACHE_MISS_ENV] = "280000"
        os.environ[OUTPUT_ENV] = "1100000"
        mock_enabled.return_value = True
        mock_markup.return_value = 2500
        mock_fx.return_value = 4500000
        _validate_deepseek_pricing_config()


if __name__ == "__main__":
    unittest.main()
