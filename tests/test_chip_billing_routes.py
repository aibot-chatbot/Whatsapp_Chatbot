"""Authenticated CHIP checkout/status contracts used by the existing frontend."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import httpx
import requests
from flask import Flask

import app.routes.billing_routes as routes
import app.decorators.auth_decorator as auth
import app.database.user_repository as users
from app.rate_limit import limiter

REFERENCE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ATTEMPT = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
AUTH = {"Authorization": "Bearer synthetic-token"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network call in mocked payment tests")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(httpx.Client, "request", blocked)


@pytest.fixture
def billing(monkeypatch):
    user = {"id": 1, "company_id": 42, "full_name": "Test User", "email": "test@example.test",
            "role": "admin", "status": "active"}
    # Deliberately stale JWT tenant: database identity must win.
    monkeypatch.setattr(auth.jwt, "decode", lambda *args, **kwargs: {"user_id": 1, "company_id": 999, "role": "admin"})
    monkeypatch.setattr(users, "get_user_by_id", lambda *args: user)
    monkeypatch.setattr(routes, "get_user_by_id", lambda *args: user)
    monkeypatch.setattr(routes, "get_current_subscription", lambda company: {"id": 8})
    policy = SimpleNamespace(top_up_allowed=True, denial_reason=None)
    monkeypatch.setattr(routes, "resolve_ai_access", lambda company: policy)
    create = Mock(return_value={"order_reference": REFERENCE, "checkout_url": "https://gate.chip-in.asia/b/test/",
                                "amount_micro_myr": 2_000_000, "is_test": True})
    monkeypatch.setattr(routes, "create_chip_topup_checkout", create)
    lookup = Mock(return_value={
        "order_reference": REFERENCE, "company_id": 42, "created_by_user_id": 1, "id": 5,
        "status": "pending", "amount_micro_myr": 2_000_000, "currency": "MYR",
        "payment_gateway": "chip", "gateway_environment": "test",
        "idempotency_key": "private-attempt-secret", "checkout_claim_token": "private-token",
        "gateway_brand_id": "private-brand", "credit_transaction_id": 7,
    })
    monkeypatch.setattr(routes, "get_topup_order_by_reference_and_company", lookup)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="synthetic-secret", RATELIMIT_ENABLED=False)
    limiter.init_app(app)
    app.register_blueprint(routes.billing_bp)
    return app.test_client(), create, lookup, policy


def test_checkout_uses_authenticated_tenant_and_uuid_attempt(billing):
    client, create, _, _ = billing
    response = client.post("/api/billing/chip/checkout", headers={**AUTH, "Idempotency-Key": ATTEMPT}, json={
        "amount_micro_myr": 2_000_000, "company_id": 999, "user_id": 123,
        "customer_email": "attacker@example.test", "payment_gateway": "hitpay", "amount_sen": 1,
    })
    assert response.status_code == 201
    assert response.json["data"]["order_reference"] == REFERENCE
    kwargs = create.call_args.kwargs
    assert kwargs["company_id"] == 42 and kwargs["created_by_user_id"] == 1 and kwargs["subscription_id"] == 8
    assert kwargs["customer_email"] == "test@example.test"
    assert kwargs["amount_micro_myr"] == 2_000_000
    assert kwargs["idempotency_key"] == f"chip-topup:42:1:{ATTEMPT}"


@pytest.mark.parametrize("attempt", [None, "", "bad-attempt", "../some-path"])
def test_missing_or_invalid_idempotency_header_never_starts_checkout(billing, attempt):
    client, create, _, _ = billing
    headers = dict(AUTH)
    if attempt is not None:
        headers["Idempotency-Key"] = attempt
    response = client.post("/api/billing/chip/checkout", headers=headers, json={"amount_micro_myr": 2_000_000})
    assert response.status_code == 400
    create.assert_not_called()


@pytest.mark.parametrize("amount", [True, 2_000_000.0, "2000000", None, -1, 0, 1_000_000, 2_000_001])
def test_invalid_money_never_starts_checkout(billing, amount):
    client, create, _, _ = billing
    response = client.post("/api/billing/chip/checkout", headers={**AUTH, "Idempotency-Key": ATTEMPT},
                           json={"amount_micro_myr": amount})
    assert response.status_code == 400
    create.assert_not_called()


def test_plan_denial_never_starts_checkout(billing):
    client, create, _, policy = billing
    policy.top_up_allowed = False
    policy.denial_reason = "An active paid subscription is required."
    response = client.post("/api/billing/chip/checkout", headers={**AUTH, "Idempotency-Key": ATTEMPT},
                           json={"amount_micro_myr": 2_000_000})
    assert response.status_code == 403
    assert response.json["message"] == policy.denial_reason
    create.assert_not_called()


@pytest.mark.parametrize("path,method", [("/checkout", "post"), ("/orders/" + REFERENCE, "get")])
def test_payment_endpoints_require_authentication(billing, path, method):
    client, create, lookup, _ = billing
    response = getattr(client, method)("/api/billing/chip" + path)
    assert response.status_code == 401
    create.assert_not_called()
    lookup.assert_not_called()


def test_status_uses_database_tenant_and_excludes_internal_fields(billing):
    client, _, lookup, _ = billing
    response = client.get("/api/billing/chip/orders/" + REFERENCE, headers=AUTH)
    assert response.status_code == 200
    lookup.assert_called_once_with(order_reference=REFERENCE, company_id=42)
    data = response.json["data"]
    assert data["order_reference"] == REFERENCE and data["is_test"] is True
    assert data["credited"] is False and data["test_paid"] is False
    assert not {"company_id", "created_by_user_id", "id", "idempotency_key", "checkout_claim_token",
                "gateway_brand_id", "credit_transaction_id"}.intersection(data)
    assert "private-" not in response.get_data(as_text=True)


def test_foreign_or_unknown_order_is_not_found(billing):
    client, _, lookup, _ = billing
    lookup.return_value = None
    response = client.get("/api/billing/chip/orders/" + REFERENCE, headers=AUTH)
    assert response.status_code == 404
    lookup.assert_called_once_with(order_reference=REFERENCE, company_id=42)


def test_bad_order_reference_never_queries_storage(billing):
    client, _, lookup, _ = billing
    assert client.get("/api/billing/chip/orders/not-a-uuid", headers=AUTH).status_code == 400
    lookup.assert_not_called()


def test_test_paid_is_visible_without_claiming_credit(billing):
    client, _, lookup, _ = billing
    lookup.return_value.update(status="cancelled", failure_reason="chip_test_paid")
    response = client.get("/api/billing/chip/orders/" + REFERENCE, headers=AUTH)
    assert response.json["data"]["test_paid"] is True
    assert response.json["data"]["credited"] is False


def test_checkout_error_response_hides_provider_and_database_details(billing):
    client, create, _, _ = billing
    create.side_effect = RuntimeError("private-provider-api-key")
    response = client.post("/api/billing/chip/checkout", headers={**AUTH, "Idempotency-Key": ATTEMPT},
                           json={"amount_micro_myr": 2_000_000})
    assert response.status_code == 500
    assert "private-" not in response.get_data(as_text=True)


def test_definitively_closed_checkout_returns_explicit_safe_restart_code(billing):
    client, create, _, _ = billing
    create.side_effect = routes.CheckoutRestartRequired("private-internal-details")
    response = client.post("/api/billing/chip/checkout", headers={**AUTH, "Idempotency-Key": ATTEMPT},
                           json={"amount_micro_myr": 2_000_000})
    assert response.status_code == 409
    assert response.json["code"] == "checkout_restart_required"
    assert "private-" not in response.get_data(as_text=True)


def test_subscription_configuration_failure_is_503_through_real_service(billing, monkeypatch):
    from app.services.chip_service import ChipConfig, ChipConfigError
    from app.services.subscription_checkout_service import create_subscription_checkout

    client, _, _, _ = billing
    monkeypatch.setattr(routes, "create_subscription_checkout", create_subscription_checkout)
    monkeypatch.setattr(ChipConfig, "from_env", Mock(side_effect=ChipConfigError("private-configuration-details")))
    response = client.post("/api/billing/subscription/checkout", headers=AUTH, json={"plan_code": "essential"})
    assert response.status_code == 503
    assert "private-" not in response.get_data(as_text=True)


def test_subscription_response_uses_server_test_mode(billing, monkeypatch):
    client, _, _, _ = billing
    monkeypatch.setattr(routes, "create_subscription_checkout", Mock(return_value={
        "order_reference": REFERENCE, "checkout_url": "https://gate.chip-in.asia/b/test/",
        "amount_sen": 3900, "payment_gateway": "chip", "is_test": True,
    }))
    response = client.post("/api/billing/subscription/checkout", headers=AUTH,
                           json={"plan_code": "essential", "is_test": False})
    assert response.status_code == 200
    assert response.json["data"]["is_test"] is True


@pytest.mark.parametrize("error,status", [(RuntimeError("private-provider-details"), 502), (Exception("private-backend-details"), 500)])
def test_subscription_failures_return_safe_errors(billing, monkeypatch, error, status):
    client, _, _, _ = billing
    monkeypatch.setattr(routes, "create_subscription_checkout", Mock(side_effect=error))
    response = client.post("/api/billing/subscription/checkout", headers=AUTH, json={"plan_code": "essential"})
    assert response.status_code == status
    assert "private-" not in response.get_data(as_text=True)
