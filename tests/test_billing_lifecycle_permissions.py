"""Company subscription lifecycle mutations require an owner or administrator.

All persistence sinks are mocked; actual JWT and route decorators execute.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import dotenv
from flask import Flask
import jwt
import pytest


COMPANY_ID = 42
USER_ID = 101
JWT_SECRET = "synthetic-lifecycle-signing-key-at-least-32-bytes"
ENDPOINTS = (
    ("POST", "/subscription/downgrade", "_schedule_downgrade"),
    ("DELETE", "/subscription/downgrade", "_clear_scheduled_downgrade"),
    ("POST", "/subscription/cancel", "_schedule_cancellation"),
    ("POST", "/subscription/undo-cancel", "_undo_subscription_cancellation"),
)


@pytest.fixture
def lifecycle(monkeypatch):
    # Keep provider configuration synthetic even when run independently.
    for name in (
        "SUPABASE_SERVICE_ROLE_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY", "GEMINI_API_KEY",
    ):
        monkeypatch.setenv(name, "synthetic-test-key")
    monkeypatch.setenv("SUPABASE_URL", "https://lifecycle.example.test")
    monkeypatch.setenv("SECRET_KEY", JWT_SECRET)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    network = Mock(side_effect=AssertionError("Network is forbidden in this test"))
    monkeypatch.setattr("socket.socket.connect", network)
    monkeypatch.setattr("socket.create_connection", network)

    from app.database import db, user_repository
    from app.routes import billing_routes
    from app.services import company_status_service

    monkeypatch.setattr(db, "supabase", MagicMock())
    user = {"id": USER_ID, "company_id": COMPANY_ID, "role": "member", "status": "active"}
    monkeypatch.setattr(user_repository, "get_user_by_id", Mock(return_value=user))
    monkeypatch.setattr(
        company_status_service, "get_company_status_by_id",
        Mock(return_value={"id": COMPANY_ID, "status": "active"}),
    )
    monkeypatch.setattr(
        billing_routes, "_get_plan_by_code",
        Mock(return_value={"id": 1, "is_active": True}),
    )
    mutations = {}
    for _, _, name in ENDPOINTS:
        mutations[name] = Mock(return_value={})
        monkeypatch.setattr(billing_routes, name, mutations[name])

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY=JWT_SECRET, RATELIMIT_ENABLED=False)
    app.register_blueprint(billing_routes.billing_bp)
    client = app.test_client()

    def request(endpoint, *, role=None, token_company=COMPANY_ID, authenticated=True, override=False):
        method, path, _ = endpoint
        headers = {}
        if authenticated:
            token = jwt.encode(
                {"user_id": USER_ID, "company_id": token_company, "role": role or user["role"]},
                JWT_SECRET, algorithm="HS256",
            )
            headers["Authorization"] = "Bearer " + token
        body = {"target_plan_code": "essential"}
        if override:
            body["company_id"] = 999
            path += "?company_id=999"
        return client.open("/api/billing" + path, method=method, json=body, headers=headers)

    yield SimpleNamespace(user=user, mutations=mutations, request=request)
    network.assert_not_called()


def assert_no_mutation(lifecycle):
    for mutation in lifecycle.mutations.values():
        mutation.assert_not_called()


def assert_only_expected_mutation(lifecycle, endpoint):
    expected = {"company_id": COMPANY_ID}
    if endpoint[2] == "_schedule_downgrade":
        expected["target_plan_id"] = 1
    lifecycle.mutations[endpoint[2]].assert_called_once_with(**expected)
    for name, mutation in lifecycle.mutations.items():
        if name != endpoint[2]:
            mutation.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_member_cannot_mutate_subscription(lifecycle, endpoint):
    response = lifecycle.request(endpoint)
    assert response.status_code == 403
    assert_no_mutation(lifecycle)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("role", ("admin", "owner"))
def test_company_admin_and_owner_can_mutate_subscription(lifecycle, endpoint, role):
    lifecycle.user["role"] = role
    response = lifecycle.request(endpoint)
    assert response.status_code == 200
    assert_only_expected_mutation(lifecycle, endpoint)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_database_demotion_overrides_stale_owner_token(lifecycle, endpoint):
    response = lifecycle.request(endpoint, role="owner")
    assert response.status_code == 403
    assert_no_mutation(lifecycle)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_anonymous_cannot_mutate_subscription(lifecycle, endpoint):
    response = lifecycle.request(endpoint, authenticated=False)
    assert response.status_code == 401
    assert_no_mutation(lifecycle)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_tenant_override_never_redirects_subscription_mutation(lifecycle, endpoint):
    lifecycle.user["role"] = "admin"
    response = lifecycle.request(endpoint, token_company=999, override=True)
    assert response.status_code == 200
    assert_only_expected_mutation(lifecycle, endpoint)
