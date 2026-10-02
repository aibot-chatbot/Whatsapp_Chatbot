"""Tests for routing the AI provider calls through Cloudflare AI Gateway.

Every tenant's bot depends on these calls, so the cases that matter most are
the ones where a naive implementation would take the product down: the switch
defaulting to on, a half-configured gateway swallowing traffic instead of
falling back, or the transport quietly rewriting the model name that AI-credit
billing prices the request from.
"""

from unittest.mock import patch

import pytest

from app.services import ai_gateway, ai_router, deepseek_service, openrouter_service


ACCOUNT_ID = "synthetic-cloudflare-account-id"


@pytest.fixture(autouse=True)
def _isolated_gateway_env(monkeypatch):
    """Start every test from an unconfigured gateway, whatever the shell holds."""
    for name in ("AI_GATEWAY_ENABLED", "AI_GATEWAY_ACCOUNT_ID", "AI_GATEWAY_ID", "R2_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    yield


def _enable(monkeypatch, **overrides):
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("AI_GATEWAY_ACCOUNT_ID", ACCOUNT_ID)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)


class _Message:
    content = "synthetic reply"


class _Choice:
    message = _Message()


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15
    prompt_tokens_details = None


class _Completion:
    choices = [_Choice()]
    usage = _Usage()
    model = "deepseek-v4-flash"
    id = "synthetic-generation-id"


class _RecordingOpenAI:
    """Stands in for ``openai.OpenAI`` and remembers how it was built."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _RecordingOpenAI.last = self
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **_kwargs):
        return _Completion()


# ── The kill switch ───────────────────────────────────────────────────────

def test_gateway_is_off_when_the_flag_is_unset():
    """Unset must mean off. An operator has to opt in deliberately."""
    assert ai_gateway.is_enabled() is False
    assert ai_gateway.deepseek_base_url() == "https://api.deepseek.com"
    assert (
        ai_gateway.openrouter_chat_completions_url()
        == "https://openrouter.ai/api/v1/chat/completions"
    )


def test_gateway_stays_off_for_a_falsey_flag(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_ACCOUNT_ID", ACCOUNT_ID)
    for value in ("", "0", "false", "no", "off", "maybe"):
        monkeypatch.setenv("AI_GATEWAY_ENABLED", value)
        assert ai_gateway.is_enabled() is False, value
        assert ai_gateway.deepseek_base_url() == "https://api.deepseek.com"


def test_the_switch_is_read_per_call_so_turning_it_off_needs_no_deploy(monkeypatch):
    """No import-time caching: flipping the secret takes effect immediately."""
    _enable(monkeypatch)
    assert ai_gateway.is_enabled() is True

    monkeypatch.setenv("AI_GATEWAY_ENABLED", "false")
    assert ai_gateway.is_enabled() is False
    assert ai_gateway.deepseek_base_url() == "https://api.deepseek.com"


def test_disabled_deepseek_reuses_the_module_client_object():
    """OFF is the same client instance as before the gateway existed."""
    assert deepseek_service._active_client() is deepseek_service.client
    assert str(deepseek_service.client.base_url).startswith("https://api.deepseek.com")


# ── URL construction when the gateway is on ───────────────────────────────

def test_enabled_gateway_builds_the_per_provider_deepseek_base_url(monkeypatch):
    _enable(monkeypatch)
    assert ai_gateway.deepseek_base_url() == (
        f"https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/default/deepseek"
    )


def test_enabled_gateway_builds_the_per_provider_openrouter_url(monkeypatch):
    _enable(monkeypatch)
    assert ai_gateway.openrouter_chat_completions_url() == (
        f"https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/default/openrouter/chat/completions"
    )


def test_gateway_id_defaults_to_default_but_is_overridable(monkeypatch):
    """Cloudflare auto-creates the 'default' gateway, so no pre-provisioning."""
    _enable(monkeypatch, AI_GATEWAY_ID="omnexa-prod")
    assert ai_gateway.deepseek_base_url().endswith(f"/{ACCOUNT_ID}/omnexa-prod/deepseek")


def test_account_id_falls_back_to_the_existing_r2_account_id(monkeypatch):
    """Same Cloudflare account; the coupling is explicit but overridable."""
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("R2_ACCOUNT_ID", "synthetic-r2-account-id")
    assert ai_gateway.deepseek_base_url() == (
        "https://gateway.ai.cloudflare.com/v1/synthetic-r2-account-id/default/deepseek"
    )


def test_an_explicit_account_id_wins_over_the_r2_one(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("R2_ACCOUNT_ID", "synthetic-r2-account-id")
    monkeypatch.setenv("AI_GATEWAY_ACCOUNT_ID", ACCOUNT_ID)
    assert f"/v1/{ACCOUNT_ID}/" in ai_gateway.deepseek_base_url()


# ── Half-configured gateway must never swallow traffic ────────────────────

@pytest.mark.parametrize("account_id", ["", "   "])
def test_blank_account_id_falls_back_to_the_provider_instead_of_crashing(monkeypatch, account_id):
    """A gateway turned on but never given an account id must not break bots."""
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("AI_GATEWAY_ACCOUNT_ID", account_id)
    monkeypatch.setenv("R2_ACCOUNT_ID", account_id)

    assert ai_gateway.deepseek_base_url() == "https://api.deepseek.com"
    assert (
        ai_gateway.openrouter_chat_completions_url()
        == "https://openrouter.ai/api/v1/chat/completions"
    )
    assert deepseek_service._active_client() is deepseek_service.client


def test_missing_account_id_entirely_falls_back_to_the_provider(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_ENABLED", "true")
    assert ai_gateway.deepseek_base_url() == "https://api.deepseek.com"
    assert (
        ai_gateway.openrouter_chat_completions_url()
        == "https://openrouter.ai/api/v1/chat/completions"
    )


def test_blank_gateway_id_falls_back_to_the_default_gateway(monkeypatch):
    _enable(monkeypatch, AI_GATEWAY_ID="   ")
    assert ai_gateway.deepseek_base_url().endswith(f"/{ACCOUNT_ID}/default/deepseek")


# ── The call sites actually use it ────────────────────────────────────────

def test_deepseek_chat_client_targets_the_gateway_when_enabled(monkeypatch):
    _enable(monkeypatch)
    client = deepseek_service._active_client()
    assert client is not deepseek_service.client
    assert str(client.base_url).rstrip("/") == (
        f"https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/default/deepseek"
    )


def test_gateway_deepseek_client_keeps_the_sixty_second_timeout(monkeypatch):
    """The 600s SDK default once held a gunicorn thread for ten minutes."""
    _enable(monkeypatch)
    assert deepseek_service._active_client().timeout == 60
    assert deepseek_service.client.timeout == 60


def test_openrouter_chat_request_posts_to_the_gateway_when_enabled(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", "synthetic-openrouter-key")

    with patch.object(openrouter_service.requests, "post") as post:
        post.return_value.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        openrouter_service._request("prompt", model="google/gemini-3.5-flash")

    assert post.call_args.args[0] == (
        f"https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/default/openrouter/chat/completions"
    )


def test_openrouter_chat_request_goes_direct_when_disabled(monkeypatch):
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", "synthetic-openrouter-key")

    with patch.object(openrouter_service.requests, "post") as post:
        post.return_value.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        openrouter_service._request("prompt", model="google/gemini-3.5-flash")

    assert post.call_args.args[0] == "https://openrouter.ai/api/v1/chat/completions"


def test_system_deepseek_call_targets_the_gateway_when_enabled(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-deepseek-key")

    with patch("openai.OpenAI", _RecordingOpenAI):
        ai_router._call_deepseek_direct("prompt", "deepseek-v4-flash", 0.3)

    assert _RecordingOpenAI.last.kwargs["base_url"] == (
        f"https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/default/deepseek"
    )


def test_system_deepseek_call_goes_direct_when_disabled(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-deepseek-key")

    with patch("openai.OpenAI", _RecordingOpenAI):
        ai_router._call_deepseek_direct("prompt", "deepseek-v4-flash", 0.3)

    assert _RecordingOpenAI.last.kwargs["base_url"] == "https://api.deepseek.com"


def test_system_openrouter_call_targets_the_gateway_when_enabled(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")

    with patch("requests.post") as post:
        post.return_value.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        ai_router._call_openrouter_direct("prompt", "google/gemini-3.5-flash", 0.3)

    assert post.call_args.args[0] == (
        f"https://gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/default/openrouter/chat/completions"
    )


def test_system_openrouter_call_goes_direct_when_disabled(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")

    with patch("requests.post") as post:
        post.return_value.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        ai_router._call_openrouter_direct("prompt", "google/gemini-3.5-flash", 0.3)

    assert post.call_args.args[0] == "https://openrouter.ai/api/v1/chat/completions"


# ── What the gateway must NOT touch ───────────────────────────────────────

def test_the_balance_monitor_never_goes_through_the_gateway(monkeypatch):
    """The key's remaining credit is an account fact, not an inference call.

    Routing it through the gateway would ask Cloudflare for OpenRouter's
    account endpoint, and a cached or rewritten answer here would misreport
    the one balance that funds every pooled tenant.
    """
    _enable(monkeypatch)
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", "synthetic-openrouter-key")

    with patch.object(openrouter_service.requests, "get") as get:
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"data": {"limit_remaining": 42.0}}
        assert openrouter_service.get_key_status() == {"limit_remaining": 42.0}

    assert get.call_args.args[0] == "https://openrouter.ai/api/v1/key"


def test_the_gateway_does_not_rewrite_the_model_name_billing_prices_from(monkeypatch):
    """AI-credit charging looks the model up by its exact provider name.

    The per-provider endpoint was chosen over Cloudflare's /compat endpoint
    precisely so 'deepseek-v4-flash' does not become 'deepseek/deepseek-v4-flash'
    and silently fall out of the priced-model set.
    """
    _enable(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-deepseek-key")

    with patch("openai.OpenAI", _RecordingOpenAI):
        result = ai_router._call_deepseek_direct("prompt", "deepseek-v4-flash", 0.3)

    assert result.model == "deepseek-v4-flash"
    assert "/compat" not in ai_gateway.deepseek_base_url()

    with patch.object(openrouter_service, "OPENROUTER_API_KEY", "synthetic-openrouter-key"), \
            patch.object(openrouter_service.requests, "post") as post:
        post.return_value.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        openrouter_service._request("prompt", model="google/gemini-3.5-flash")

    assert post.call_args.kwargs["json"]["model"] == "google/gemini-3.5-flash"
