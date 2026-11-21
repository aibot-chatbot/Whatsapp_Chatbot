"""Optional Cloudflare AI Gateway transport for the AI provider calls.

This module handles transport URLs and publish-test timeouts. ai_access_policy
selects the provider and model. The model name in the request body remains the
same name used for AI-credit billing.

Why the per-provider endpoint and not Cloudflare's OpenAI-compatible /compat
endpoint: /compat requires the model to be provider-prefixed
("deepseek/deepseek-v4-flash" instead of "deepseek-v4-flash"). That string is
written into ai_usage_logs and is the key _compute_deepseek_provider_cost()
looks the price up by, so a prefix would silently drop every request out of
the priced-model set and change what the customer is charged. The per-provider
endpoint is a pure base-URL swap, which is also the smaller diff.

The kill switch: every tenant's bot depends on these calls, so AI_GATEWAY_ENABLED
defaults to OFF and is re-read on every call. Turning it off is a secret change,
never a deploy, and takes effect on the next request. When the switch is on but
the account id is missing, traffic falls back to the provider rather than being
sent to an address that cannot exist -- a half-finished configuration must not
be able to stop the product.

Routing through the gateway needs no Cloudflare API token: the provider key is
still the auth, carried in the same Authorization header as today.
"""

import logging
import os
from functools import lru_cache
from time import monotonic

from flask import g, has_request_context

#: Where the calls go when the gateway is off. These are the exact URLs the
#: providers were called on before this module existed; the disabled path must
#: stay byte-identical to production.
DEEPSEEK_DIRECT_BASE_URL = "https://api.deepseek.com"
OPENROUTER_DIRECT_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

#: A safety net, not the length control: the prompt rule keeps replies short. Reasoning shares
#: this budget, and real chat replies reached 617 tokens at the 95th percentile.
MAX_CHAT_REPLY_TOKENS = 800
#: Above the largest real job (9,913 tokens): a lower cap would cut extracted JSON mid-way.
MAX_SYSTEM_RESPONSE_TOKENS = 12000
DYNAMIC_SECTION_HEADER = "--- Conversation details ---"

_GATEWAY_ROOT = "https://gateway.ai.cloudflare.com/v1"

#: Cloudflare auto-creates a gateway named "default" on the first request, so
#: nothing has to be provisioned before the switch is flipped.
_DEFAULT_GATEWAY_ID = "default"

_TRUTHY = ("1", "true", "yes", "on")


def publish_test_timeout():
    """Share 40s between retrieval and provider attempts, leaving time to grade and save."""
    if not has_request_context() or not getattr(g, "publish_test", False):
        return None
    now = monotonic()
    if not hasattr(g, "publish_test_deadline"):
        g.publish_test_deadline = now + 40
    remaining = g.publish_test_deadline - now
    if remaining < 0.001:
        raise TimeoutError("The publish test provider deadline expired.")
    return min(20, remaining)


def publish_test_http_timeout(default):
    timeout = publish_test_timeout()
    if timeout is None:
        return default
    connect, read = default if isinstance(default, tuple) else (default, default)
    return min(connect, 3, timeout), min(read, timeout)


def is_enabled() -> bool:
    """Whether provider calls should be routed through the AI Gateway.

    Read from the environment on every call, never cached: an operator must be
    able to switch the gateway off without waiting for a deploy.
    """
    return os.getenv("AI_GATEWAY_ENABLED", "").strip().lower() in _TRUTHY


def _account_id() -> str:
    """The Cloudflare account that owns the gateway.

    Defaults to R2_ACCOUNT_ID because the AI Gateway lives in the same
    Cloudflare account as the document-storage bucket. AI_GATEWAY_ACCOUNT_ID
    exists so that coupling is visible in the environment and can be broken
    without touching storage.
    """
    explicit = os.getenv("AI_GATEWAY_ACCOUNT_ID", "").strip()
    return explicit or os.getenv("R2_ACCOUNT_ID", "").strip()


def _gateway_id() -> str:
    return os.getenv("AI_GATEWAY_ID", "").strip() or _DEFAULT_GATEWAY_ID


@lru_cache(maxsize=None)
def _warn_once(message: str) -> None:
    """Log a configuration problem once per process instead of per request."""
    logging.warning(message)


def _provider_base_url(provider_slug: str) -> str | None:
    """The gateway base URL for a provider, or None to call it directly."""
    if not is_enabled():
        return None

    account_id = _account_id()
    if not account_id:
        _warn_once(
            "AI_GATEWAY_ENABLED is set but no account id is configured "
            "(AI_GATEWAY_ACCOUNT_ID or R2_ACCOUNT_ID); calling AI providers directly."
        )
        return None

    return f"{_GATEWAY_ROOT}/{account_id}/{_gateway_id()}/{provider_slug}"


def deepseek_base_url() -> str:
    """Base URL for the DeepSeek OpenAI-SDK client.

    The SDK appends "/chat/completions" to whichever base it is given, so this
    returns the provider root in both modes.
    """
    return _provider_base_url("deepseek") or DEEPSEEK_DIRECT_BASE_URL


def openrouter_chat_completions_url() -> str:
    """Full chat-completions URL for the OpenRouter HTTP calls."""
    base = _provider_base_url("openrouter")
    if not base:
        return OPENROUTER_DIRECT_CHAT_COMPLETIONS_URL
    return f"{base}/chat/completions"
