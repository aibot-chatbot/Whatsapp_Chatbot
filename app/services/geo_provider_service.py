"""Official provider adapters for evidence-based GEO collection.

Every catalogued adapter calls the provider directly and returns the same
evidence shape. Provider response bodies and API keys are never logged.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import re
import time
from urllib.parse import urlparse

import requests

from app.services.ai_gateway import openrouter_chat_completions_url


PLATFORM_CAPABILITIES = {
    "chatgpt": {"label": "ChatGPT Search", "mode": "official_api", "surface": "OpenAI Responses API"},
    "gemini": {"label": "Gemini", "mode": "official_api", "surface": "Gemini grounded search API"},
    "claude": {"label": "Claude", "mode": "official_api", "surface": "Anthropic web search API"},
    "deepseek": {"label": "DeepSeek", "mode": "official_api", "surface": "DeepSeek Anthropic-compatible web search"},
    "perplexity": {"label": "Perplexity", "mode": "official_api", "surface": "Perplexity Agent API"},
}
LIVE_API_PLATFORMS = frozenset(key for key, value in PLATFORM_CAPABILITIES.items()
                               if value["mode"] == "official_api")


def _timeout():
    try:
        value = float(os.getenv("GEO_PROVIDER_TIMEOUT_SECONDS", "45"))
    except ValueError:
        value = 45
    return max(5, min(value, 120))


def _max_output_tokens():
    try:
        value = int(os.getenv("GEO_MAX_OUTPUT_TOKENS", "700"))
    except ValueError:
        value = 700
    return max(150, min(value, 1500))


def _locale_instruction(country, language):
    label = {"en": "English", "ms": "Bahasa Melayu", "zh": "Simplified Chinese"}[language]
    return (f"Answer in {label}. Treat {country} as the target market and user location. "
            "Do not change the meaning of the user's prompt.")


def _domain(url):
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host or None
    except (TypeError, ValueError):
        return None


def _citation(value, position):
    if isinstance(value, str):
        url, title, metadata = value, None, {}
    elif isinstance(value, dict):
        nested = value.get("url_citation") if isinstance(value.get("url_citation"), dict) else value
        url = nested.get("url") or nested.get("uri") or value.get("url") or value.get("uri")
        title = nested.get("title") or value.get("title")
        metadata = value
    else:
        return None
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return None
    return {"url": url, "domain": _domain(url), "title": str(title) if title else None,
            "position": position, "metadata": metadata}


def _unique_citations(values):
    seen, citations = set(), []
    for value in values:
        item = _citation(value, len(citations) + 1)
        if item and item["url"] not in seen:
            seen.add(item["url"])
            citations.append(item)
    return citations


def _message_text(content):
    """Normalize OpenAI-compatible string and content-block responses."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _failed(platform, surface, model, started, code):
    return {"platform": platform, "surface": surface, "model": model,
            "request_status": "failed", "raw_response": "", "citations": [],
            "latency_ms": int((time.monotonic() - started) * 1000), "cost_usd": None,
            "is_search_experience": False, "error_code": code, "provider_metadata": {}}


def _post_json(url, *, headers, body):
    response = requests.post(url, headers=headers, json=body, timeout=_timeout())
    if not response.ok:
        raise RuntimeError(f"provider_http_{response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("provider_invalid_response")
    return payload


def _openai_model():
    return os.getenv("OPENAI_SEARCH_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"


def _openrouter_openai_model():
    """Use the same OpenAI model as the direct route, with OpenRouter's namespace."""
    model = _openai_model()
    return model if model.startswith("openai/") else f"openai/{model}"


def _supports_reasoning_effort(model):
    """Return whether this OpenAI family accepts the reasoning-effort parameter."""
    name = str(model or "").lower().removeprefix("openai/")
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def _openai(prompt, country, language):
    started = time.monotonic()
    model = _openai_model()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return _failed("chatgpt", "openai-web-search-api", model, started, "provider_not_configured")
    try:
        payload = _post_json("https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            body={"model": model, "input": prompt, "instructions": _locale_instruction(country, language),
                  "tools": [{"type": "web_search", "user_location": {
                      "type": "approximate", "country": country}}], "tool_choice": "required",
                  "max_output_tokens": _max_output_tokens(),
                  "include": ["web_search_call.action.sources"]})
        output = payload.get("output") if isinstance(payload.get("output"), list) else []
        contents = [content for item in output if item.get("type") == "message"
                    for content in (item.get("content") or []) if isinstance(content, dict)]
        text = payload.get("output_text") or "\n".join(str(item.get("text") or "") for item in contents)
        evidence = [annotation for item in contents for annotation in (item.get("annotations") or [])]
        evidence += [source for item in output if item.get("type") == "web_search_call"
                     for source in ((item.get("action") or {}).get("sources") or [])]
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return {"platform": "chatgpt", "surface": "openai-web-search-api", "model": model,
                "request_status": "complete", "raw_response": str(text).strip(),
                "citations": _unique_citations(evidence),
                "latency_ms": int((time.monotonic() - started) * 1000), "cost_usd": None,
                "is_search_experience": True, "error_code": None,
                "provider_metadata": {"response_id": payload.get("id"), "usage": usage,
                                      "route": ["Omnexa", "OpenAI"]}}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed("chatgpt", "openai-web-search-api", model, started, code)


def _gemini(prompt, country, language):
    started = time.monotonic()
    model = os.getenv("GEMINI_SEARCH_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return _failed("gemini", "gemini-grounded-search-api", model, started, "provider_not_configured")
    try:
        payload = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            body={"contents": [{"parts": [{"text": prompt}]}],
                  "systemInstruction": {"parts": [{"text": _locale_instruction(country, language)}]},
                  "generationConfig": {"maxOutputTokens": _max_output_tokens()},
                  "tools": [{"google_search": {}}]})
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        content = candidate.get("content") or {}
        text = "\n".join(str(part.get("text") or "") for part in (content.get("parts") or [])
                         if isinstance(part, dict)).strip()
        grounding = candidate.get("groundingMetadata") or {}
        chunks = grounding.get("groundingChunks") if isinstance(grounding.get("groundingChunks"), list) else []
        evidence = [{"url": (chunk.get("web") or {}).get("uri"),
                     "title": (chunk.get("web") or {}).get("title")}
                    for chunk in chunks if isinstance(chunk, dict)]
        return {"platform": "gemini", "surface": "gemini-grounded-search-api", "model": model,
                "request_status": "complete", "raw_response": text,
                "citations": _unique_citations(evidence),
                "latency_ms": int((time.monotonic() - started) * 1000), "cost_usd": None,
                "is_search_experience": True, "error_code": None,
                "provider_metadata": {"search_queries": grounding.get("webSearchQueries") or [],
                                      "route": ["Omnexa", "Google Gemini"]}}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed("gemini", "gemini-grounded-search-api", model, started, code)


def _anthropic_search(platform, prompt, country, language, *, url, key_name, model_name, default_model, surface):
    started = time.monotonic()
    model = os.getenv(model_name, default_model).strip() or default_model
    key = os.getenv(key_name, "").strip()
    if not key:
        return _failed(platform, surface, model, started, "provider_not_configured")
    try:
        payload = _post_json(url,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            body={"model": model, "max_tokens": _max_output_tokens(),
                  "system": _locale_instruction(country, language),
                  "messages": [{"role": "user", "content": prompt}],
                  "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5,
                             "user_location": {"type": "approximate", "country": country}}]})
        content = payload.get("content") if isinstance(payload.get("content"), list) else []
        text_blocks = [item for item in content if isinstance(item, dict) and item.get("type") == "text"]
        text = "\n".join(str(item.get("text") or "") for item in text_blocks).strip()
        evidence = [citation for item in text_blocks for citation in (item.get("citations") or [])]
        for item in content:
            if not isinstance(item, dict):
                continue
            evidence.extend(item.get("citations") or [])
            nested = item.get("content") if isinstance(item.get("content"), list) else []
            evidence.extend(value for value in nested if isinstance(value, dict) and value.get("url"))
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return {"platform": platform, "surface": surface, "model": model,
                "request_status": "complete", "raw_response": text,
                "citations": _unique_citations(evidence),
                "latency_ms": int((time.monotonic() - started) * 1000), "cost_usd": None,
                "is_search_experience": True, "error_code": None,
                "provider_metadata": {"response_id": payload.get("id"), "usage": usage,
                                      "route": ["Omnexa", "Anthropic" if platform == "claude" else "DeepSeek"]}}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed(platform, surface, model, started, code)


def _claude(prompt, country, language):
    return _anthropic_search("claude", prompt, country, language,
        url="https://api.anthropic.com/v1/messages", key_name="ANTHROPIC_API_KEY",
        model_name="ANTHROPIC_SEARCH_MODEL", default_model="claude-sonnet-5-5",
        surface="anthropic-web-search-api")


def _deepseek(prompt, country, language):
    return _anthropic_search("deepseek", prompt, country, language,
        url="https://api.deepseek.com/anthropic/v1/messages", key_name="DEEPSEEK_API_KEY",
        model_name="DEEPSEEK_SEARCH_MODEL", default_model="deepseek-flash",
        surface="deepseek-web-search-api")


def _perplexity(prompt, country, language):
    started = time.monotonic()
    preset = os.getenv("PERPLEXITY_AGENT_PRESET", "fast").strip() or "fast"
    model = f"agent-preset:{preset}"
    key = os.getenv("PERPLEXITY_API_KEY", "").strip()
    if not key:
        return _failed("perplexity", "perplexity-sonar-api", model, started, "provider_not_configured")
    try:
        payload = _post_json("https://api.perplexity.ai/v1/agent",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            body={"preset": preset, "input": prompt,
                  "instructions": _locale_instruction(country, language) + " Use web search and cite sources.",
                  "tools": [{"type": "web_search"}], "max_output_tokens": _max_output_tokens()})
        output = payload.get("output") if isinstance(payload.get("output"), list) else []
        message_parts = [part for item in output if isinstance(item, dict) and item.get("type") == "message"
                         for part in (item.get("content") or []) if isinstance(part, dict)]
        text = payload.get("output_text") or "\n".join(str(part.get("text") or "") for part in message_parts)
        evidence = [annotation for part in message_parts for annotation in (part.get("annotations") or [])]
        evidence += [result for item in output if isinstance(item, dict)
                     and item.get("type") in {"search_results", "fetch_url_results"}
                     for result in (item.get("results") or item.get("contents") or [])]
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        cost = usage.get("cost") if isinstance(usage.get("cost"), dict) else {}
        return {"platform": "perplexity", "surface": "perplexity-agent-api", "model": model,
                "request_status": "complete", "raw_response": str(text).strip(),
                "citations": _unique_citations(evidence),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "cost_usd": cost.get("total_cost") if isinstance(cost.get("total_cost"), (int, float)) else None,
                "is_search_experience": True, "error_code": None,
                "provider_metadata": {"response_id": payload.get("id"), "usage": usage,
                                      "resolved_model": payload.get("model"),
                                      "route": ["Omnexa", "Perplexity Agent API"]}}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed("perplexity", "perplexity-sonar-api", model, started, code)


def _openrouter_openai(prompt, country, language):
    """Comparison-only OpenRouter route pinned to OpenAI native web search."""
    started = time.monotonic()
    display_model = _openai_model()
    model = _openrouter_openai_model()
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return _failed("openrouter_chatgpt", "openrouter-openai-native-search", display_model, started,
                       "provider_not_configured")
    try:
        body = {"model": model, "messages": [
                    {"role": "system", "content": _locale_instruction(country, language)
                     + " Search the web before answering and return a concise, sourced final answer."},
                    {"role": "user", "content": prompt}],
                "tools": [{"type": "openrouter:web_search", "parameters": {"engine": "native"}}],
                "provider": {"order": ["openai"], "allow_fallbacks": False,
                             "require_parameters": True},
                "max_completion_tokens": _max_output_tokens()}
        if _supports_reasoning_effort(display_model):
            body["reasoning"] = {"effort": "low"}
        payload = _post_json(openrouter_chat_completions_url(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": os.getenv("FRONTEND_URL", "https://omnexa.my"),
                     "X-OpenRouter-Title": "Omnexa GEO Route Comparison"},
            body=body)
        choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        text = _message_text(message.get("content"))
        evidence = list(payload.get("citations") or []) + list(message.get("citations") or [])
        evidence += list(message.get("annotations") or [])
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        metadata = {"response_id": payload.get("id"), "usage": usage,
                    "finish_reason": choice.get("finish_reason"),
                    "request_model": model,
                    "route": ["Omnexa", "OpenRouter", "OpenAI"],
                    "provider_pinned": "openai", "fallbacks_allowed": False,
                    "search_engine": "native"}
        if not text:
            code = "provider_output_truncated" if choice.get("finish_reason") == "length" else "provider_empty_response"
            failed = _failed("openrouter_chatgpt", "openrouter-openai-native-search", display_model, started, code)
            failed["cost_usd"] = usage.get("cost") if isinstance(usage.get("cost"), (int, float)) else None
            failed["provider_metadata"] = metadata
            return failed
        return {"platform": "openrouter_chatgpt", "surface": "openrouter-openai-native-search",
                "model": display_model, "request_status": "complete",
                "raw_response": text,
                "citations": _unique_citations(evidence),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "cost_usd": usage.get("cost") if isinstance(usage.get("cost"), (int, float)) else None,
                "is_search_experience": True, "error_code": None,
                "provider_metadata": metadata}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed("openrouter_chatgpt", "openrouter-openai-native-search", display_model, started, code)


def collect(platform, prompt, country, language):
    adapters = {"chatgpt": _openai, "gemini": _gemini, "claude": _claude,
                "deepseek": _deepseek, "perplexity": _perplexity}
    if platform not in adapters:
        raise ValueError("This GEO surface does not expose a supported official answer API.")
    return adapters[platform](prompt, country, language)


def configured_platforms():
    return {"chatgpt": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "claude": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
            "deepseek": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
            "perplexity": bool(os.getenv("PERPLEXITY_API_KEY", "").strip())}


def platform_capabilities():
    configured = configured_platforms()
    return {key: {**value, "configured": configured[key]} for key, value in PLATFORM_CAPABILITIES.items()}


def comparison_capability():
    direct = bool(os.getenv("OPENAI_API_KEY", "").strip())
    routed = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
    return {"enabled": direct and routed, "direct_openai_configured": direct,
            "openrouter_configured": routed, "calls_per_run": 2}


def _terms(value):
    return set(re.findall(r"[\w'-]+", str(value or "").casefold()))


def compare_openai_routes(prompt, country, language):
    """Run one prompt through direct OpenAI and OpenRouter-pinned OpenAI."""
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 500:
        raise ValueError("Prompt must contain 1 to 500 characters.")
    country = str(country or "MY").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("Country must be a two-letter ISO code.")
    language = str(language or "en").strip().lower()
    if language not in {"en", "ms", "zh"}:
        raise ValueError("Language must be English, Bahasa Melayu or Chinese.")
    with ThreadPoolExecutor(max_workers=2) as pool:
        direct_future = pool.submit(_openai, prompt.strip(), country, language)
        routed_future = pool.submit(_openrouter_openai, prompt.strip(), country, language)
        direct, routed = direct_future.result(), routed_future.result()
    left, right = _terms(direct.get("raw_response")), _terms(routed.get("raw_response"))
    direct_domains = {item.get("domain") for item in direct.get("citations") or [] if item.get("domain")}
    routed_domains = {item.get("domain") for item in routed.get("citations") or [] if item.get("domain")}
    return {"prompt": prompt.strip(), "country": country, "language": language,
            "direct": direct, "openrouter": routed,
            "comparison": {
                "answer_term_overlap_percent": round(len(left & right) / max(len(left | right), 1) * 100, 1),
                "citation_domain_overlap_percent": round(
                    len(direct_domains & routed_domains) / max(len(direct_domains | routed_domains), 1) * 100, 1),
                "shared_citation_domains": sorted(direct_domains & routed_domains),
            },
            "methodology": {
                "calls": 2,
                "statement": "Both routes use web search, but only the direct route is the official OpenAI API relationship. OpenRouter is a gateway and is pinned to OpenAI with fallbacks disabled.",
                "warning": "One run is a route demonstration, not a statistically reliable model benchmark.",
            }}
