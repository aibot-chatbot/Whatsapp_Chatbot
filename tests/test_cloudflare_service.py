"""Mocked Cloudflare transport and integer billing regression checks."""

import json
from unittest.mock import Mock

import pytest
import requests

from app.services import cloudflare_service as service


MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"


def _provider_response(model, prompt=10, completion=20):
    if model.startswith("openai/"):
        return {"id": "response-1", "status": "completed", "output": [
            {"type": "reasoning", "summary": [{"text": "private thinking"}]},
            {"type": "message", "role": "assistant", "phase": "final_answer",
             "content": [{"type": "output_text", "text": "Hello"}]}],
            "usage": {"input_tokens": prompt, "output_tokens": completion,
                      "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 5}}}
    if model.startswith("anthropic/"):
        return {"id": "message-1", "type": "message", "stop_reason": "end_turn",
                "content": [{"type": "thinking", "thinking": "private thinking"},
                            {"type": "text", "text": "Hello"}],
                "usage": {"input_tokens": prompt, "output_tokens": completion}}
    return {"choices": [{"message": {"content": "Hello"}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


def test_request_usage_and_no_retry_or_customer_content_logging(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "test-token")
    monkeypatch.setenv("AI_GATEWAY_ID", "default")
    monkeypatch.delenv("CLOUDFLARE_AI_MODEL_PRICING_JSON", raising=False)
    data = {
        "id": "generation-1", "choices": [{"message": {"content": "Hello"}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
                  "completion_tokens_details": {"reasoning_tokens": 20}},
    }
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value=data)))
    monkeypatch.setattr(service.requests, "post", post)
    result = service.request("Hello", MODEL, json_response=True)
    assert service.extract_usage(result, MODEL)["provider_cost_micro_usd"] == 85
    assert service.extract_usage(result, MODEL)["reasoning_tokens"] == 20
    assert post.call_count == 1
    kwargs = post.call_args.kwargs
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["cf-aig-skip-cache"] == "true"
    assert kwargs["headers"]["cf-aig-collect-log"] == "false"
    assert kwargs["headers"]["cf-aig-max-attempts"] == "1"
    assert kwargs["json"]["messages"][0]["role"] == "system"
    assert "matching the requested structure" in kwargs["json"]["messages"][0]["content"]

    # Price configuration must be valid before incurring provider costs.
    post.reset_mock()
    with pytest.raises(RuntimeError, match="pricing"):
        service.request("Hello", "openai/gpt-5.6-sol")
    post.assert_not_called()
    rates = {"input_micro_usd_per_million": 1_000_000,
             "cached_input_micro_usd_per_million": 100_000,
             "output_micro_usd_per_million": 2_000_000}
    monkeypatch.setenv("CLOUDFLARE_AI_MODEL_PRICING_JSON", json.dumps({"openai/gpt-5.6-sol": rates}))
    post.return_value.json.return_value = _provider_response("openai/gpt-5.6-sol", 1000, 100)
    result = service.request("Hello", "openai/gpt-5.6-sol")
    assert "temperature" not in post.call_args.kwargs["json"]
    assert post.call_args.kwargs["json"]["max_output_tokens"] == 4096
    result["usage"]["prompt_tokens_details"] = {"cached_tokens": 500}
    assert service.extract_usage(result, "openai/gpt-5.6-sol")["provider_cost_micro_usd"] == 750

    for bad in (-1, True, 0.5, "100", None):
        result["usage"]["prompt_tokens"] = bad
        with pytest.raises(RuntimeError):
            service.extract_usage(result, "openai/gpt-5.6-sol")
    post.reset_mock()
    post.side_effect = requests.ReadTimeout("secret-token/private-prompt")
    with pytest.raises(RuntimeError) as error:
        service.request("Hello", MODEL)
    assert "secret-token" not in str(error.value)
    assert post.call_count == 1


def test_missing_usage_redirect_and_invalid_account_fail_closed(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "test-token")
    monkeypatch.setenv("AI_GATEWAY_ID", "default")
    monkeypatch.delenv("CLOUDFLARE_AI_MODEL_PRICING_JSON", raising=False)
    post = Mock(return_value=Mock(status_code=302))
    monkeypatch.setattr(service.requests, "post", post)
    with pytest.raises(RuntimeError):
        service.request("Hello", MODEL)
    post.return_value = Mock(status_code=200, json=Mock(return_value={"choices": [{"message": {"content": "Hello"}}]}))
    with pytest.raises(RuntimeError, match="billing usage"):
        service.request("Hello", MODEL)
    post.reset_mock()
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "../other-account")
    with pytest.raises(RuntimeError, match="account"):
        service.request("Hello", MODEL)
    post.assert_not_called()


def test_all_models_envelopes_identity_and_preflight_limits(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "test-token")
    monkeypatch.setenv("AI_GATEWAY_ID", "default")
    models = [item["value"] for item in service.CLOUDFLARE_MODELS]
    rates = dict(zip(service._RATE_KEYS, (1_000_000, 100_000, 2_000_000)))
    monkeypatch.setenv("CLOUDFLARE_AI_MODEL_PRICING_JSON", json.dumps({model: rates for model in models if not model.startswith("@cf/")}))
    post = Mock()
    monkeypatch.setattr(service.requests, "post", post)
    for model in models:
        for envelope in ({"success": True}, {"state": "Completed"}):
            completion = _provider_response(model)
            post.return_value = Mock(status_code=200, headers={"cf-aig-log-id": "cf-log-id"},
                                     json=Mock(return_value=dict(envelope, result=completion)))
            result = service.request("Hello", model)
            assert service.extract_usage(result, model)["generation_id"] == completion.get("id", "cf-log-id")
            assert result["choices"][0]["message"]["content"] == "Hello"
            if model.startswith(("openai/gpt-5", "anthropic/claude-sonnet-")):
                assert "temperature" not in post.call_args.kwargs["json"]
    post.reset_mock()
    # Existing knowledge/menu prompts may exceed 16k bytes; do not truncate them.
    post.return_value.json.return_value = _provider_response(MODEL)
    service.request("a" * 20_000, MODEL)
    post.reset_mock()
    for model, prompt in ((MODEL, "a" * 128_001), (models[-1], "a" * 128_001),
                          (MODEL, "中" * 42667), ("arbitrary/model", "Hello")):
        with pytest.raises(RuntimeError):
            service.request(prompt, model)
    post.assert_not_called()
    for envelope in ({"state": "Failed", "result": {}}, {"success": False, "result": {}},
                     {"choices": []}, {"choices": [{"message": {"content": None}}]}):
        post.return_value = Mock(status_code=200, json=Mock(return_value=envelope))
        with pytest.raises(RuntimeError):
            service.request("Hello", MODEL)


def test_native_pro_protocols_and_billing_details(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "test-token")
    monkeypatch.setenv("AI_GATEWAY_ID", "default")
    gpt, claude = "openai/gpt-5.6-sol", "anthropic/claude-sonnet-5"
    rates = dict(zip(service._RATE_KEYS, (1_000_000, 100_000, 2_000_000)))
    monkeypatch.setenv("CLOUDFLARE_AI_MODEL_PRICING_JSON", json.dumps({gpt: rates, claude: rates}))
    post = Mock(return_value=Mock(status_code=200, headers={}))
    monkeypatch.setattr(service.requests, "post", post)
    for model, endpoint in ((gpt, "responses"), (claude, "messages")):
        raw = _provider_response(model, 1000, 100)
        if model == gpt:
            raw["usage"]["input_tokens_details"]["cached_tokens"] = 500
        else:
            raw["usage"]["input_tokens"] = 500
            raw["usage"]["cache_read_input_tokens"] = 500
        post.return_value.json.return_value = raw
        result = service.request("Return []", model, json_response=True)
        assert post.call_args.args[0].endswith("/" + endpoint)
        payload = post.call_args.kwargs["json"]
        assert "temperature" not in payload
        if model == gpt:
            assert payload["store"] is False
            assert payload["input"] == "Return []"
            assert "requested structure" in payload["instructions"]
        else:
            assert "requested structure" in payload["system"]
        usage = service.extract_usage(result, model)
        assert usage["provider_cost_micro_usd"] == 750
        assert usage["completion_tokens"] == 100
        assert usage["cached_tokens"] == 500
        assert usage["reasoning_tokens"] == (5 if model == gpt else 0)

    raw["usage"]["cache_creation_input_tokens"] = 20
    with pytest.raises(RuntimeError):
        service.request("Hello", claude)
    for status in ("failed", "incomplete", "in_progress"):
        raw = _provider_response(gpt)
        raw["status"] = status
        post.return_value.json.return_value = raw
        with pytest.raises(RuntimeError):
            service.request("Hello", gpt)
