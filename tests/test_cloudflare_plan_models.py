"""Exact plan choices and saved bot changes, with all persistence mocked."""
from datetime import datetime, timedelta, timezone
from inspect import unwrap
from unittest.mock import Mock

import pytest
from flask import Flask

from app.services import ai_access_policy as policy_module
from app.services import bot_service
from app.services.billing_guard import BillingLimitError
from app.services.model_catalog import (
    CLOUDFLARE_PLAN_MODELS, PLAN_MODELS, PRO_MODELS, CLOUDFLARE_QWEN_MODEL, default_model_for_plan, default_provider_for_plan,
    get_models_for_plan, get_models_with_tiers, validate_cloudflare_selection, validate_plan_selection,
)


def policy(plan):
    return policy_module.AIAccessPolicy(
        allowed=True, api_route=policy_module.ROUTE_OPENROUTER if plan == "pro" else policy_module.ROUTE_CLOUDFLARE,
        access_state="active_trial" if plan == "free" else plan,
        model_editable=plan != "free",
    )


@pytest.mark.parametrize("plan,count", [("free", 1), ("essential", 2), ("advanced", 3), ("pro", 3)])
def test_exact_plan_membership(plan, count):
    choices = get_models_for_plan(plan)
    assert set(choices) == ({"openai", "anthropic", "google"} if plan == "pro" else {"cloudflare"})
    offered = [m for entry in choices.values() for m in entry["models"]]
    assert len(offered) == count
    assert all(plan in m["plans"] for m in offered)
    assert [m["value"] for m in offered] == list(PLAN_MODELS[plan])
    for provider, entry in get_models_with_tiers().items():
        for candidate in entry["models"]:
            model = candidate["value"]
            if model in PLAN_MODELS[plan]:
                assert validate_plan_selection(provider, model, policy(plan)) == (provider, model)
            else:
                with pytest.raises(BillingLimitError):
                    validate_plan_selection(provider, model, policy(plan))


def test_pro_is_three_distinct_premium_families():
    assert PLAN_MODELS["pro"] == (
        "openai/gpt-5.5", "anthropic/claude-sonnet-4", "google/gemini-3.8-flash",
    )
    assert "pro" not in CLOUDFLARE_PLAN_MODELS
    with pytest.raises(BillingLimitError):
        validate_cloudflare_selection("cloudflare", "openai/gpt-5.6-sol", policy("pro"))
    assert get_models_for_plan("unknown") == {}
    assert set(get_models_with_tiers()) == {"cloudflare", "openai", "anthropic", "google"}


@pytest.mark.parametrize("plan", ["free", "essential", "advanced", "pro"])
def test_bot_create_defaults_to_its_plan(monkeypatch, plan):
    monkeypatch.setattr(bot_service, "resolve_ai_access", lambda _company: policy(plan))
    create = Mock(return_value={"id": 9})
    monkeypatch.setattr(bot_service, "create_bot", create)
    bot_service.add_bot({"bot_name": "Example"}, 42)
    data, company = create.call_args.args
    assert company == 42
    assert data["ai_provider"] == default_provider_for_plan(plan)
    assert data["model_name"] == default_model_for_plan(plan)


@pytest.mark.parametrize("provider,model", [("openai", "openai/gpt-5.6-sol"), ("cloudflare", "fake/model"), ("cloudflare", ""), ("", CLOUDFLARE_QWEN_MODEL)])
def test_invalid_creation_is_not_silently_repaired(monkeypatch, provider, model):
    monkeypatch.setattr(bot_service, "resolve_ai_access", lambda _company: policy("essential"))
    create = Mock()
    monkeypatch.setattr(bot_service, "create_bot", create)
    with pytest.raises(BillingLimitError):
        bot_service.add_bot({"bot_name": "Example", "ai_provider": provider, "model_name": model}, 42)
    create.assert_not_called()


def test_edit_denies_out_of_plan_and_preserves_valid_free_selection(monkeypatch):
    monkeypatch.setattr(bot_service, "resolve_ai_access", lambda _company: policy("free"))
    monkeypatch.setattr(bot_service, "get_bot_by_id", lambda *_args: {
        "id": 9, "ai_provider": "cloudflare", "model_name": CLOUDFLARE_QWEN_MODEL,
    })
    update = Mock(return_value={"id": 9})
    monkeypatch.setattr(bot_service, "update_bot", update)
    with pytest.raises(BillingLimitError):
        bot_service.edit_bot(9, {"model_name": CLOUDFLARE_PLAN_MODELS["essential"][1]}, 42)
    update.assert_not_called()
    bot_service.edit_bot(9, {"model_name": CLOUDFLARE_QWEN_MODEL}, 42)
    update.assert_called_once()


@pytest.mark.parametrize("plan", ["free", "essential", "advanced", "pro"])
def test_policy_routes_entitled_plans_through_correct_provider(monkeypatch, plan):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(policy_module, "_get_company_subscription", lambda _company: {
        "plan_id": 1, "status": "trialing" if plan == "free" else "active",
        "trial_ends_at": (now + timedelta(days=1)).isoformat(),
        "current_period_end": (now + timedelta(days=1)).isoformat(),
    })
    monkeypatch.setattr(policy_module, "get_plan_by_id", lambda _id: {"id": 1, "code": plan})
    resolved = policy_module.resolve_ai_access(42, now=now)
    assert resolved.allowed
    assert resolved.api_route == (policy_module.ROUTE_OPENROUTER if plan == "pro" else policy_module.ROUTE_CLOUDFLARE)
    assert resolved.model_editable == (plan != "free")


def test_expired_trial_remains_denied_with_readonly_catalog(monkeypatch):
    from app.routes import ai_model_routes
    denied = policy_module.AIAccessPolicy(access_state="expired_trial", denial_reason="Trial expired")
    monkeypatch.setattr(policy_module, "resolve_ai_access", lambda _company: denied)
    monkeypatch.setattr(ai_model_routes, "get_current_company_id", lambda: 42)
    with Flask(__name__).app_context():
        response, status = unwrap(ai_model_routes.get_ai_models)()
    body = response.get_json()
    assert status == 200
    assert body["read_only"] and not body["access_allowed"]
    assert body["data"] == get_models_for_plan("free")


def test_paid_conversion_uses_target_plan_and_keeps_valid_choice(monkeypatch):
    from app.database import bot_repository
    from app.services.billing_service import convert_trial_ai_configuration
    pro_model = PLAN_MODELS["pro"][1]
    monkeypatch.setattr(bot_repository, "get_all_bots", lambda _company: [
        {"id": 1, "ai_provider": "cloudflare", "model_name": CLOUDFLARE_QWEN_MODEL},
        {"id": 2, "ai_provider": "anthropic", "model_name": pro_model},
        {"id": 3, "ai_provider": "deepseek", "model_name": "deepseek-v4-flash"},
    ])
    update = Mock()
    monkeypatch.setattr(bot_repository, "update_bot", update)
    convert_trial_ai_configuration(42, "pro")
    assert [call.args[0] for call in update.call_args_list] == [1, 3]
    for call in update.call_args_list:
        assert call.args[1] == {"ai_provider": "openai", "model_name": default_model_for_plan("pro")}
        assert call.args[2] == 42
