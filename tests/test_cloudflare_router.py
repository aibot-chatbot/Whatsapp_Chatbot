"""Cloudflare uses the same tenant, prompt, credit and settlement boundaries."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import ai_router, ai_access_policy
from app.services.model_catalog import CLOUDFLARE_PLAN_MODELS, PLAN_MODELS, PRO_MODELS
from app.services.billing_guard import BillingLimitError


@pytest.fixture
def cloudflare(monkeypatch):
    model = CLOUDFLARE_PLAN_MODELS["free"][0]  # the trial is the only Cloudflare-routed plan
    policy = ai_access_policy.AIAccessPolicy(
        allowed=True, access_state="active_trial", api_route="cloudflare", model_editable=False,
    )
    monkeypatch.setattr(ai_router, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(ai_access_policy, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda _: {
        "company_id": 7, "ai_provider": "cloudflare", "model_name": model,
    })
    monkeypatch.setattr(ai_router, "_try_process_flow_message", lambda *a, **k: SimpleNamespace(
        handled=False, should_handoff_to_ai=True,
    ))
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", lambda **k: {"prompt": "tenant knowledge"})
    preflight = Mock()
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", preflight)
    transport = Mock(return_value={
        "id": "unique-call", "choices": [{"message": {"content": "Available on Tuesday."}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    })
    monkeypatch.setattr(ai_router.cloudflare_service, "request", transport)
    settle = Mock()
    monkeypatch.setattr(ai_router, "_make_usage_log", settle)
    return model, transport, preflight, settle


@pytest.mark.parametrize("system", [False, True])
def test_chat_and_system_log_once_after_cloudflare(cloudflare, system):
    model, transport, preflight, settle = cloudflare
    if system:
        text = ai_router.generate_system_response("tenant knowledge", 3, json_response=True)
        assert transport.call_args.kwargs["json_response"] is True
    else:
        text = ai_router.generate_response("What sessions are available?", 4, 3)
    assert text == "Available on Tuesday."
    transport.assert_called_once()
    assert preflight.called
    settle.assert_called_once()
    result, company_id, chatbot_id, _ = settle.call_args.args
    assert (company_id, chatbot_id) == (7, 3)
    assert result.provider == "cloudflare" and result.model == model
    assert result.provider_cost_micro_usd > 0
    assert result.is_provider_response


@pytest.mark.parametrize("system", [False, True])
def test_settlement_failure_never_retries_provider(cloudflare, system):
    _, transport, _, settle = cloudflare
    settle.side_effect = RuntimeError("settlement failed")
    if system:
        with pytest.raises(RuntimeError, match="settlement failed"):
            ai_router.generate_system_response("request", 3)
    else:
        assert "trouble" in ai_router.generate_response("request", 4, 3)
    transport.assert_called_once()


@pytest.mark.parametrize("system", [False, True])
def test_out_of_plan_and_legacy_selection_blocked(cloudflare, system):
    _, transport, _, _ = cloudflare
    enforce = ai_router._get_system_provider_for_enforcement if system else ai_router._route_for_enforcement
    for provider, model in [("cloudflare", PLAN_MODELS["pro"][0]),
                            ("deepseek", "deepseek-v4-flash"), ("cloudflare", None)]:
        with pytest.raises(BillingLimitError):
            enforce(provider, model, 7)
    transport.assert_not_called()


def test_local_reply_does_not_invoke_or_charge_cloudflare(cloudflare, monkeypatch):
    from app.services import chat_logic_service
    _, transport, preflight, settle = cloudflare
    monkeypatch.setattr(chat_logic_service, "detect_intent", lambda _: "greeting")
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", lambda **k: {"direct_reply": "Welcome"})
    assert ai_router.generate_response("hi", 4, 3) == "Welcome"
    transport.assert_not_called()
    preflight.assert_not_called()
    settle.assert_not_called()


@pytest.mark.parametrize("system", [False, True])
@pytest.mark.parametrize("selection", PRO_MODELS)
def test_pro_existing_brand_runs_openrouter_only(cloudflare, monkeypatch, system, selection):
    _, cloudflare_transport, preflight, settle = cloudflare
    policy = ai_access_policy.AIAccessPolicy(
        allowed=True, access_state="pro", api_route="openrouter", model_editable=True,
    )
    monkeypatch.setattr(ai_router, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(ai_access_policy, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda _: {
        "company_id": 7, "ai_provider": selection["provider"], "model_name": selection["value"],
    })
    data = {"id": "pro-usage", "choices": [{"message": {"content": "Tuesday."}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.0001}}
    chat_transport = Mock(return_value=(True, data))
    system_transport = Mock(return_value=ai_router._complete_provider_result("Tuesday.", "openrouter", selection["value"], data))
    monkeypatch.setattr(ai_router.openrouter_service, "_request", chat_transport)
    monkeypatch.setattr(ai_router, "_call_openrouter_direct", system_transport)
    result = ai_router.generate_system_response("request", 3) if system else ai_router.generate_response("request", 4, 3)
    assert result == "Tuesday."
    cloudflare_transport.assert_not_called()
    (system_transport if system else chat_transport).assert_called_once()
    settle.assert_called_once()
    assert settle.call_args.args[0].provider == "openrouter"
    assert settle.call_args.args[0].model == selection["value"]


@pytest.mark.parametrize("system", [False, True])
def test_pro_cloudflare_and_bad_pair_are_denied(cloudflare, monkeypatch, system):
    policy = ai_access_policy.AIAccessPolicy(allowed=True, access_state="pro", api_route="openrouter")
    monkeypatch.setattr(ai_router, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(ai_access_policy, "resolve_ai_access", lambda _: policy)
    enforce = ai_router._get_system_provider_for_enforcement if system else ai_router._route_for_enforcement
    for provider, model in [("cloudflare", "openai/gpt-5.6-sol"), ("google", "openai/gpt-5.5"), ("openai", "fake/model")]:
        with pytest.raises(BillingLimitError):
            enforce(provider, model, 7)
