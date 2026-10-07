"""Provider adapters for evidence-based GEO collection.

Each adapter returns the same structure and clearly identifies whether the
response came from a search-enabled API. Provider response bodies and API keys
are never logged.
"""
import os
import time
from urllib.parse import urlparse

import requests

from app.services.ai_gateway import openrouter_chat_completions_url


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


def _openai(prompt, country, language):
    started = time.monotonic()
    model = os.getenv("OPENAI_SEARCH_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return _failed("chatgpt", "openai-web-search-api", model, started, "provider_not_configured")
    try:
        payload = _post_json("https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            body={"model": model, "input": prompt, "instructions": _locale_instruction(country, language),
                  "tools": [{"type": "web_search", "user_location": {
                      "type": "approximate", "country": country}}], "tool_choice": "auto",
                  "max_output_tokens": _max_output_tokens(),
                  "include": ["web_search_call.action.sources"]})
        output = payload.get("output") if isinstance(payload.get("output"), list) else []
        contents = [content for item in output if item.get("type") == "message"
                    for content in (item.get("content") or []) if isinstance(content, dict)]
        text = payload.get("output_text") or "\n".join(str(item.get("text") or "") for item in contents)
        evidence = [annotation for item in contents for annotation in (item.get("annotations") or [])]
        evidence += [source for item in output if item.get("type") == "web_search_call"
                     for source in ((item.get("action") or {}).get("sources") or [])]
        return {"platform": "chatgpt", "surface": "openai-web-search-api", "model": model,
                "request_status": "complete", "raw_response": str(text).strip(),
                "citations": _unique_citations(evidence),
                "latency_ms": int((time.monotonic() - started) * 1000), "cost_usd": None,
                "is_search_experience": True, "error_code": None,
                "provider_metadata": {"response_id": payload.get("id")}}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed("chatgpt", "openai-web-search-api", model, started, code)


def _gemini(prompt, country, language):
    started = time.monotonic()
    model = os.getenv("GEMINI_SEARCH_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
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
                "provider_metadata": {"search_queries": grounding.get("webSearchQueries") or []}}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed("gemini", "gemini-grounded-search-api", model, started, code)


def _perplexity(prompt, country, language):
    started = time.monotonic()
    model = os.getenv("OPENROUTER_PERPLEXITY_MODEL", "perplexity/sonar-pro").strip() or "perplexity/sonar-pro"
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return _failed("perplexity", "perplexity-search-api", model, started, "provider_not_configured")
    try:
        payload = _post_json(openrouter_chat_completions_url(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": os.getenv("FRONTEND_URL", "https://omnexa.my"), "X-Title": "Omnexa GEO"},
            body={"model": model, "messages": [
                {"role": "system", "content": _locale_instruction(country, language)},
                {"role": "user", "content": prompt}], "max_tokens": _max_output_tokens()})
        choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
        message = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
        evidence = list(payload.get("citations") or []) + list(message.get("citations") or [])
        evidence += list(message.get("annotations") or [])
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return {"platform": "perplexity", "surface": "perplexity-search-api", "model": model,
                "request_status": "complete", "raw_response": str(message.get("content") or "").strip(),
                "citations": _unique_citations(evidence),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "cost_usd": usage.get("cost") if isinstance(usage.get("cost"), (int, float)) else None,
                "is_search_experience": True, "error_code": None,
                "provider_metadata": {"response_id": payload.get("id"), "usage": usage}}
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        code = str(exc) if str(exc).startswith("provider_") else "provider_unavailable"
        return _failed("perplexity", "perplexity-search-api", model, started, code)


def collect(platform, prompt, country, language):
    adapters = {"chatgpt": _openai, "gemini": _gemini, "perplexity": _perplexity}
    if platform not in adapters:
        raise ValueError("Unsupported GEO platform")
    return adapters[platform](prompt, country, language)


def configured_platforms():
    return {"chatgpt": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "perplexity": bool(os.getenv("OPENROUTER_API_KEY", "").strip())}
