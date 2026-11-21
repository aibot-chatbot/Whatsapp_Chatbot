"""Cloudflare unified inference with explicit token pricing and no retries."""

import json
import os
import re
import uuid

import requests

from app.services import ai_gateway
from app.services.model_catalog import CLOUDFLARE_MODELS

# USD micro-units per million tokens, from Cloudflare's model pages.
_NATIVE_PRICES = {
    "@cf/qwen/qwen3-30b-a3b-fp8": (50_900, 50_900, 335_000),
    "@cf/openai/gpt-oss-20b": (200_000, 200_000, 300_000),
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": (293_000, 293_000, 2_253_000),
}
_RATE_KEYS = (
    "input_micro_usd_per_million",
    "cached_input_micro_usd_per_million",
    "output_micro_usd_per_million",
)


def _integer(value):
    if type(value) is not int or value < 0:
        raise RuntimeError("Cloudflare AI returned invalid usage or pricing.")
    return value


def _pricing(model):
    try:
        configured = json.loads(os.getenv("CLOUDFLARE_AI_MODEL_PRICING_JSON", "{}"))
        if not isinstance(configured, dict):
            raise ValueError
        if model in configured:
            rates = tuple(_integer(configured[model][key]) for key in _RATE_KEYS)
        else:
            rates = _NATIVE_PRICES[model]
        if not rates[0] or not rates[2] or rates[1] > rates[0]:
            raise ValueError
        return rates
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Cloudflare AI model pricing is missing or invalid.") from None


def extract_usage(data, model):
    """Return router usage fields; reasoning is already in completion tokens.

    This calculates the configured token tariff, not Cloudflare's account invoice
    (which may include a shared free allowance or credit purchase fees).
    """
    try:
        usage = data["usage"]
        prompt = _integer(usage["prompt_tokens"])
        completion = _integer(usage["completion_tokens"])
        total = _integer(usage.get("total_tokens", prompt + completion))
        cached = _integer((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
        reasoning = _integer((usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0))
        if not total or total != prompt + completion or cached > prompt or reasoning > completion:
            raise ValueError
        # Cache-write tokens have a different tariff. Do not silently underbill.
        if _integer(usage.get("cache_creation_input_tokens", 0)):
            raise ValueError
        rates = data.get("_cloudflare_pricing") or _pricing(model)
        numerator = (prompt - cached) * rates[0] + cached * rates[1] + completion * rates[2]
        generation_id = data.get("id") or data.get("_cloudflare_request_id")
        if not isinstance(generation_id, str) or not generation_id.strip():
            raise ValueError
        return {
            "provider": "cloudflare", "model": model,
            "prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": total, "cached_tokens": cached, "reasoning_tokens": reasoning,
            "provider_cost_micro_usd": (numerator + 999_999) // 1_000_000,
            "generation_id": generation_id,
        }
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise RuntimeError("Cloudflare AI returned incomplete or invalid billing usage.") from None


def _normalize_response(data, protocol):
    """Normalize provider wire formats without exposing thinking blocks."""
    if protocol == "chat/completions":
        return data
    try:
        usage = data["usage"]
        prompt = _integer(usage["input_tokens"])
        completion = _integer(usage["output_tokens"])
        if protocol == "responses":
            if data.get("status") != "completed":
                raise ValueError
            content = "\n".join(
                part["text"] for item in data["output"]
                if item.get("type") == "message" and item.get("role") == "assistant"
                and item.get("phase") in (None, "final_answer")
                for part in item["content"] if part.get("type") == "output_text"
            )
            details = usage.get("input_tokens_details") or {}
            cached = _integer(details.get("cached_tokens", 0))
            created = _integer(details.get("cache_write_tokens", 0))
            reasoning = _integer((usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0))
        else:
            if data.get("type") != "message" or data.get("stop_reason") not in ("end_turn", "stop_sequence"):
                raise ValueError
            content = "\n".join(part["text"] for part in data["content"] if part.get("type") == "text")
            cached = _integer(usage.get("cache_read_input_tokens", 0))
            created = _integer(usage.get("cache_creation_input_tokens", 0))
            # Anthropic input_tokens excludes cache-read and cache-write tokens.
            prompt += cached + created
            reasoning = 0  # Included in output_tokens; no separate count supplied.
        return {"id": data.get("id"), "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                          "total_tokens": usage.get("total_tokens", prompt + completion),
                          "prompt_tokens_details": {"cached_tokens": cached},
                          "completion_tokens_details": {"reasoning_tokens": reasoning},
                          "cache_creation_input_tokens": created}}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("Cloudflare AI returned an invalid provider response.") from None


def request(prompt, model, temperature=0.7, json_response=False, *, timeout=(10, 90), platform_review=False):
    """Make one non-streaming request; reject oversized prompts before billing.

    A 128,000-byte cap keeps Pro below the 200k long-context pricing threshold
    without adding a tokenizer. Cloudflare enforces each native model's context
    window. Output is capped at 4,096 tokens. Platform reviews use native
    Workers AI without the customer model catalogue, tariffs or usage contract.
    """
    if platform_review:
        if not isinstance(model, str) or not re.fullmatch(r"@cf/[a-z0-9._-]+/[a-z0-9._-]+", model):
            raise RuntimeError("Platform review requires a native Workers AI model.")
    else:
        if not isinstance(model, str) or model not in {item["value"] for item in CLOUDFLARE_MODELS}:
            raise RuntimeError("Cloudflare AI model is not available.")
        rates = _pricing(model)
    account = os.getenv("CLOUDFLARE_AI_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_AI_API_TOKEN", "").strip()
    gateway = os.getenv("AI_GATEWAY_ID", "default").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
        raise RuntimeError("Cloudflare AI account and API token are not configured.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", gateway):
        raise RuntimeError("Cloudflare AI gateway is not configured correctly.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError("Cloudflare AI requires a non-empty prompt.")
    try:
        prompt_bytes = len(prompt.encode("utf-8"))
    except UnicodeEncodeError:
        raise RuntimeError("Cloudflare AI requires a valid UTF-8 prompt.") from None
    if prompt_bytes > 128_000:
        raise RuntimeError("Cloudflare AI prompt exceeds the supported size.")
    messages = [{"role": "user", "content": prompt}]
    if json_response:
        # All selected models accept messages; avoid unsupported provider-specific
        # JSON schema parameters. The calling service validates the JSON result.
        messages.insert(0, {"role": "system", "content": "Return only valid JSON matching the requested structure, without markdown fences."})
    payload = {"model": model, "messages": messages, "stream": False}
    protocol = "chat/completions"
    if model == "openai/gpt-5.6-sol":
        protocol = "responses"
        payload = {"model": model, "input": prompt, "max_output_tokens": 4096,
                   "store": False, "stream": False}
        if json_response:
            payload["instructions"] = messages[0]["content"]
    elif model == "anthropic/claude-sonnet-5":
        protocol = "messages"
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                   "max_tokens": 4096, "stream": False}
        if json_response:
            payload["system"] = messages[0]["content"]
    else:
        payload["max_tokens"] = 4096
        payload["temperature"] = temperature
        if platform_review and json_response:
            payload["response_format"] = {"type": "json_object"}
    try:
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/{protocol}",
            headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                "cf-aig-gateway-id": gateway, "cf-aig-skip-cache": "true",
                "cf-aig-collect-log": "false", "cf-aig-max-attempts": "1",
            },
            json=payload, timeout=ai_gateway.publish_test_http_timeout(timeout), allow_redirects=False,
        )
        if response.status_code != 200:
            raise RuntimeError("Cloudflare AI request failed.")
        data = response.json()
        # Some Cloudflare API clients return the usual result envelope.
        if isinstance(data, dict) and "result" in data:
            if (data.get("success") is False
                    or data.get("state") not in (None, "Completed")
                    or not (data.get("success") is True or data.get("state") == "Completed")):
                raise RuntimeError("Cloudflare AI request failed.")
            data = data["result"]
        data = _normalize_response(data, protocol)
        if not isinstance(data, dict) or not isinstance(data.get("choices"), list):
            raise RuntimeError("Cloudflare AI returned an invalid response.")
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError
        except (IndexError, KeyError, TypeError, ValueError):
            raise RuntimeError("Cloudflare AI returned an invalid completion.") from None
        if platform_review:
            return data
        data["_cloudflare_pricing"] = rates
        log_id = response.headers.get("cf-aig-log-id")
        data["_cloudflare_request_id"] = (
            log_id if isinstance(log_id, str) and log_id.strip() else "cf-" + uuid.uuid4().hex
        )
        extract_usage(data, model)
        return data
    except (requests.RequestException, ValueError):
        raise RuntimeError("Cloudflare AI request failed; it was not retried.") from None
