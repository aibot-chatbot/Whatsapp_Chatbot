"""Shared access invariants; all persistence and provider boundaries are mocked."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from app.decorators.auth_decorator import token_required
from app.routes.agent_routes import agent_blueprint
from app.routes.flow_routes import flow_blueprint
from app.services import ai_access_policy, billing_guard, company_status_service
from app.services import subscription_lifecycle_service as lifecycle
from app.services.free_trial_status_service import resolve_subscription_entitlement


FUTURE = "2099-01-01T00:00:00+00:00"
PAST = "2000-01-01T00:00:00+00:00"
PLAN = {"code": "pro", "feature_flags": {"single_website_scraping": True}}
INVALID = [
    ("past_due", FUTURE), ("expired", FUTURE), ("cancelled", FUTURE),
    ("active", None), ("active", ""), ("active", "not-a-date"),
    ("active", PAST), ("active", 20990101), ("unknown", FUTURE), (None, FUTURE),
]


def subscription(status="active", end=FUTURE, plan=None, **extra):
    return {"status": status, "current_period_end": end, "plan_id": 5,
            "plan": plan or PLAN, **extra}


@pytest.mark.parametrize("status,end", INVALID)
def test_shared_policy_denies_invalid_paid_state(status, end):
    row = subscription(status, end, effective_status="active", can_renew=False)
    result = resolve_subscription_entitlement(row)
    assert result["paid_entitled"] is False
    assert result["entitled"] is False
    assert row["status"] == status  # Presentation/enforcement never normalizes DB rows.


@pytest.mark.parametrize("status,end", INVALID)
def test_feature_guard_denies_stale_flag_without_default_fallback(status, end):
    with patch.object(billing_guard, "get_current_subscription", return_value=subscription(status, end)), \
         patch.object(billing_guard, "ensure_default_company_subscription") as fallback:
        with pytest.raises(billing_guard.BillingLimitError) as exc:
            billing_guard.can_use_plan_feature(42, "single_website_scraping")
        assert exc.value.code == "no_subscription"
        fallback.assert_not_called()


@pytest.mark.parametrize("status,end", INVALID)
def test_ai_policy_denies_invalid_paid_state(status, end):
    with patch.object(ai_access_policy, "_get_company_subscription", return_value=subscription(status, end)), \
         patch.object(ai_access_policy, "get_plan_by_id", return_value=PLAN):
        result = ai_access_policy.resolve_ai_access(42)
    assert not result.allowed
    assert result.api_route == ai_access_policy.ROUTE_DENIED
    assert result.max_model_tier is None
    assert not result.top_up_allowed


@pytest.mark.parametrize("extra", [{}, {"cancellation_scheduled_at": PAST, "cancellation_effective_at": FUTURE},
                                  {"pending_plan_id": 2, "plan_change_effective_at": FUTURE}])
def test_valid_paid_and_scheduled_changes_preserve_access(extra):
    row = subscription(**extra)
    assert resolve_subscription_entitlement(row)["paid_entitled"]
    with patch.object(billing_guard, "get_current_subscription", return_value=row), \
         patch.object(ai_access_policy, "_get_company_subscription", return_value=row), \
         patch.object(ai_access_policy, "get_plan_by_id", return_value=PLAN):
        assert billing_guard.can_use_plan_feature(42, "single_website_scraping")
        policy = ai_access_policy.resolve_ai_access(42)
        assert policy.allowed and policy.max_model_tier == "premium"


def test_period_end_exact_boundary_is_denied_but_grace_presentation_preserved():
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = resolve_subscription_entitlement(subscription(end=now.isoformat()), now=now)
    assert result["effective_status"] == "past_due"
    assert not result["entitled"]


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_free_trial_uses_its_own_dates_and_configured_features(status):
    plan = {"code": "free", "feature_flags": {"knowledge_refinement": True}}
    row = subscription(status, None, plan, trial_ends_at=FUTURE)
    result = resolve_subscription_entitlement(row)
    assert result["entitled"] and not result["paid_entitled"]
    with patch.object(billing_guard, "get_current_subscription", return_value=row), \
         patch.object(ai_access_policy, "_get_company_subscription", return_value=row), \
         patch.object(ai_access_policy, "get_plan_by_id", return_value=plan):
        assert billing_guard.can_use_plan_feature(42, "knowledge_refinement")
        policy = ai_access_policy.resolve_ai_access(42)
        # A free trial runs on DeepSeek's own API again since 2026-10-16.
        assert policy.allowed and policy.api_route == ai_access_policy.ROUTE_DIRECT_DEEPSEEK
        assert not policy.top_up_allowed and not policy.model_editable


@pytest.mark.parametrize("end", [None, "bad", PAST, 20990101])
def test_free_trial_invalid_end_does_not_fall_back_to_paid_period(end):
    row = subscription(plan={"code": "free"}, trial_ends_at=end)
    assert not resolve_subscription_entitlement(row)["entitled"]


def test_default_subscription_is_also_validated():
    with patch.object(billing_guard, "get_current_subscription", return_value=None), \
         patch.object(billing_guard, "ensure_default_company_subscription", return_value=subscription(end=None)):
        with pytest.raises(billing_guard.BillingLimitError):
            billing_guard.can_use_plan_feature(42, "single_website_scraping")


def test_suspended_company_denied_by_shared_entitlement_callers(monkeypatch):
    monkeypatch.setattr(company_status_service, "get_company_status_by_id", lambda _: {"status": "suspended"})
    with patch.object(billing_guard, "get_current_subscription") as billing_read, \
         patch.object(ai_access_policy, "_get_company_subscription") as ai_read:
        with pytest.raises(billing_guard.BillingLimitError):
            billing_guard.can_use_plan_feature(42, "single_website_scraping")
        assert not ai_access_policy.resolve_ai_access(42).allowed
    billing_read.assert_not_called()
    ai_read.assert_not_called()


@pytest.fixture
def client(monkeypatch, handed_over_staff_chat):
    app = Flask(__name__)
    app.register_blueprint(flow_blueprint)
    app.register_blueprint(agent_blueprint)
    app.add_url_rule("/future-write", "future_write", token_required(lambda: ("ok", 200)), methods=["POST"])
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **k: {"user_id": 1, "company_id": 999})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: {
        "id": 1, "company_id": 42, "role": "member", "status": "active"})
    return app.test_client()


@pytest.mark.parametrize("company_status,expected", [("active", 200), ("suspended", 403)])
@pytest.mark.parametrize("action", ["draft", "publish"])
def test_flow_mutation_obeys_company_guard(client, monkeypatch, company_status, expected, action):
    lookup = Mock(return_value={"id": 42, "status": company_status})
    monkeypatch.setattr(company_status_service, "get_company_status_by_id", lookup)
    with patch("app.routes.flow_routes.verify_chatbot_access", return_value={"id": 7, "company_id": 42}), \
         patch("app.services.flow_service.upsert_flow", return_value={"id": 8}) as write:
        response = client.post("/api/dashboard/flows?action=" + action, headers={"Authorization": "Bearer test"},
                               json={"chatbot_id": 7, "company_id": 999, "flow_data": {}})
    assert response.status_code == expected
    lookup.assert_called_with(42)
    assert write.call_count == (1 if expected == 200 else 0)
    if expected == 403:
        assert response.json["code"] == "company_suspended"


@pytest.mark.parametrize("company_status,expected", [("active", 200), ("suspended", 403)])
def test_manual_reply_obeys_company_guard(client, monkeypatch, company_status, expected):
    monkeypatch.setattr(company_status_service, "get_company_status_by_id", lambda _: {"status": company_status})
    with patch("app.routes.agent_routes.verify_chatbot_access"), \
         patch("app.routes.agent_routes.get_conversation_by_id_and_chatbot", return_value={
             "source_channel": "telegram", "platform_user_id": "synthetic"}), \
         patch("app.services.channel_delivery_service.get_bound_channel", return_value={"bot_token": "synthetic"}), \
         patch("app.services.channel_delivery_service.delivery_accepted", return_value=True), patch("app.routes.agent_routes.send_telegram_message") as send, \
         patch("app.routes.agent_routes.save_message") as save:
        response = client.post("/api/conversations/8/agent-reply", headers={"Authorization": "Bearer test"},
                               json={"chatbot_id": 7, "text": "synthetic", "company_id": 999})
    assert response.status_code == expected
    assert send.call_count == save.call_count == (1 if expected == 200 else 0)
    if expected == 403:
        assert response.json["code"] == "company_suspended"


def test_new_authenticated_mutation_defaults_to_guard_and_restore_is_immediate(client, monkeypatch):
    lookup = Mock(side_effect=[{"status": "suspended"}, {"status": "active"}])
    monkeypatch.setattr(company_status_service, "get_company_status_by_id", lookup)
    assert client.post("/future-write", headers={"Authorization": "Bearer test"}).status_code == 403
    assert client.post("/future-write", headers={"Authorization": "Bearer test"}).status_code == 200


@pytest.mark.parametrize("endpoint", sorted(company_status_service.NON_OPERATIONAL_ENDPOINTS))
def test_only_explicit_non_operational_writes_are_exempt(endpoint):
    policy = company_status_service.requires_company_operational_state
    assert not policy("POST", endpoint.split(".")[0], endpoint)
    assert policy("POST", endpoint.split(".")[0], endpoint + "_new")


def test_reads_and_platform_authority_remain_separate():
    policy = company_status_service.requires_company_operational_state
    assert not policy("GET", "flows", "get_bot_flow")
    assert not policy("POST", "platform_admin", "platform_admin.restore_company")


@pytest.mark.parametrize("status", ["past_due", "expired", "cancelled", "active"])
@pytest.mark.parametrize("end", [None, "bad", PAST, 20990101])
def test_status_only_activation_cannot_revive_invalid_period(status, end):
    with patch.object(lifecycle, "_get_current_sub", return_value=subscription(status, end)), \
         patch.object(lifecycle, "get_plan_by_id", return_value=PLAN), \
         patch.object(lifecycle, "_update_status_conditional") as write:
        with pytest.raises(ValueError, match="valid entitlement period"):
            lifecycle.transition_subscription_status(42, "active")
    write.assert_not_called()


def test_valid_status_restoration_and_idempotency():
    row = subscription("cancelled", id=9)
    active = {**row, "status": "active"}
    with patch.object(lifecycle, "_get_current_sub", side_effect=[row, active]), \
         patch.object(lifecycle, "get_plan_by_id", return_value=PLAN), \
         patch.object(lifecycle, "_update_status_conditional", return_value=active) as write:
        assert lifecycle.transition_subscription_status(42, "active") == active
        assert lifecycle.transition_subscription_status(42, "active") == active
    write.assert_called_once()


@pytest.mark.parametrize("status", ["past_due", "expired", "cancelled"])
def test_scrape_analyze_denies_inactive_stale_feature_before_discovery(client, monkeypatch, status):
    from app.routes.knowledge_routes import knowledge_blueprint

    client.application.register_blueprint(knowledge_blueprint)
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: {
        "id": 1, "company_id": 42, "role": "admin", "status": "active"})
    with patch.object(billing_guard, "get_current_subscription", return_value=subscription(status)), \
         patch("app.routes.knowledge_routes.verify_chatbot_access", return_value={"id": 7, "company_id": 42}), \
         patch("app.routes.knowledge_routes.get_active_knowledge_file", return_value={
             "file_name": "primary.pdf", "file_type": "pdf", "is_active": True, "is_enabled": True}), \
         patch("app.routes.knowledge_routes.discover_website_links") as discover:
        response = client.post("/api/knowledge/scrape-analyze?chatbot_id=7", headers={"Authorization": "Bearer test"},
                               json={"url": "https://example.test", "company_id": 999})
    assert response.status_code == 403
    discover.assert_not_called()
