"""Regression tests for stale chatbot context and tenant reassignment."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from app import create_app


CURRENT_USER = {
    "id": 31,
    "company_id": 28,
    "email": "tenant-28@example.test",
    "role": "admin",
    "status": "active",
}
AUTH_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def refreshed_tenant():
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": 1, "role": "owner"},
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value=CURRENT_USER,
    ):
        yield


def test_bot_lookup_uses_current_database_company_not_stale_jwt(client, refreshed_tenant):
    with patch("app.routes.bot_routes.get_bot", side_effect=ValueError("Bot not found")) as get_bot:
        response = client.get("/api/bots/29", headers=AUTH_HEADERS)

    assert response.status_code == 404
    get_bot.assert_called_once_with(29, 28)
    assert "company 1" not in response.get_data(as_text=True).lower()


@pytest.mark.parametrize(
    ("url", "verify_patch", "data_patch"),
    [
        ("/api/settings?chatbot_id=29", "app.routes.settings_routes.verify_chatbot_access", "app.routes.settings_routes.get_deployed_settings_summary"),
        ("/api/conversations?chatbot_id=29", "app.routes.conversation_routes.verify_chatbot_access", "app.routes.conversation_routes.get_conversations_by_bot"),
        ("/api/knowledge/files?chatbot_id=29", "app.routes.knowledge_routes.verify_chatbot_access", "app.routes.knowledge_routes.list_uploaded_pdfs"),
        ("/api/telegram/channels?chatbot_id=29", "app.routes.telegram_routes.verify_chatbot_access", "app.routes.telegram_routes.get_telegram_channels_by_chatbot"),
        ("/api/crm/leads?chatbot_id=29", "app.routes.crm_routes.verify_chatbot_access", "app.routes.crm_routes.get_crm_leads_by_chatbot"),
        ("/api/analytics?chatbot_id=29", "app.routes.analytics_routes.verify_chatbot_access", "app.routes.analytics_routes.get_total_users"),
    ],
)
def test_cross_tenant_bot_domains_deny_before_data_access(
    client, refreshed_tenant, url, verify_patch, data_patch
):
    with patch(verify_patch, side_effect=PermissionError("You do not have access to this chatbot.")), patch(data_patch) as read_data:
        response = client.get(url, headers=AUTH_HEADERS)

    assert response.status_code == 403
    read_data.assert_not_called()


def test_billing_ignores_bot_id_and_uses_refreshed_company(client, refreshed_tenant):
    with patch("app.routes.billing_routes.get_current_subscription", return_value=None) as get_subscription:
        response = client.get("/api/billing/subscription?bot_id=29", headers=AUTH_HEADERS)

    assert response.status_code == 200
    get_subscription.assert_called_once_with(28)


def test_token_required_refreshes_role_and_company_from_user_row(refreshed_tenant):
    from flask import Flask, g, jsonify
    from app.decorators.auth_decorator import token_required

    app = Flask(__name__)

    @app.get("/context")
    @token_required
    def context():
        return jsonify({"company_id": g.company_id, "role": g.role, "user_id": g.user_id})

    response = app.test_client().get("/context", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.get_json() == {"company_id": 28, "role": "admin", "user_id": 31}


@pytest.mark.parametrize("database_role", [None, "", "   ", "superadmin"])
def test_token_required_fails_closed_for_missing_blank_or_invalid_database_role(database_role):
    from flask import Flask, jsonify
    from app.decorators.auth_decorator import token_required

    app = Flask(__name__)

    @app.get("/context")
    @token_required
    def context():
        return jsonify({"unexpected": True})

    user = {"id": 31, "company_id": 28, "status": "active"}
    if database_role is not None:
        user["role"] = database_role
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": 28, "role": "admin"},
    ), patch("app.database.user_repository.get_user_by_id", return_value=user):
        response = app.test_client().get("/context", headers=AUTH_HEADERS)

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "error",
        "code": "authorization_context_invalid",
        "message": "Unable to validate account authorization.",
    }


def test_token_required_normalizes_database_role_and_overrides_stale_jwt():
    from flask import Flask, g, jsonify
    from app.decorators.auth_decorator import token_required

    app = Flask(__name__)

    @app.get("/context")
    @token_required
    def context():
        return jsonify({"role": g.role})

    user = {"id": 31, "company_id": 28, "role": " Member ", "status": "active"}
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": 28, "role": "admin"},
    ), patch("app.database.user_repository.get_user_by_id", return_value=user):
        response = app.test_client().get("/context", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.get_json() == {"role": "member"}


@pytest.mark.parametrize(
    "user",
    [
        {"id": True, "company_id": 28, "role": "admin", "status": "active"},
        {"id": 0, "company_id": 28, "role": "admin", "status": "active"},
        {"id": -1, "company_id": 28, "role": "admin", "status": "active"},
        {"id": "31", "company_id": 28, "role": "admin", "status": "active"},
        {"id": 31, "company_id": True, "role": "admin", "status": "active"},
        {"id": 31, "company_id": 0, "role": "admin", "status": "active"},
        {"id": 31, "company_id": -1, "role": "admin", "status": "active"},
        {"id": 31, "company_id": "28", "role": "admin", "status": "active"},
        {"id": 31, "company_id": None, "role": "admin", "status": "active"},
    ],
)
def test_malformed_authoritative_user_context_returns_sanitized_503(client, user):
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": 1, "role": "owner"},
    ), patch("app.database.user_repository.get_user_by_id", return_value=user):
        response = client.get("/api/bots/29", headers=AUTH_HEADERS)

    assert response.status_code == 503
    assert response.get_json()["code"] == "authentication_backend_unavailable"
    assert "company_id" not in response.get_data(as_text=True)


def test_account_session_changes_clear_cached_chatbot_state():
    auth_source = Path("frontend/assets/js/auth.js").read_text(encoding="utf-8")
    login_source = Path("frontend/login.html").read_text(encoding="utf-8")
    register_source = Path("frontend/register.html").read_text(encoding="utf-8")

    assert 'sessionStorage.removeItem("selectedBotId")' in auth_source
    assert 'localStorage.removeItem("guidance_bot_history")' in auth_source
    assert "clearChatbotContext();" in auth_source
    assert login_source.count("establishAuthenticatedSession(result.user, result.token)") == 2
    assert register_source.count("establishAuthenticatedSession(result.user, result.token)") == 1


def test_profile_continues_loading_when_chatbot_navigation_context_is_stale():
    profile_source = Path("frontend/profile.html").read_text(encoding="utf-8")
    refresh = profile_source.index("await refreshProfileChatbotContext(chatbotContext)")
    profile_load = profile_source.index("loadProfile();", refresh)
    team_load = profile_source.index("loadTeamInfo();", refresh)
    billing_load = profile_source.index("loadBillingInfo();", refresh)
    helper_start = profile_source.index("async function refreshProfileChatbotContext")
    helper_end = profile_source.index("/* ===== Subscription Management", helper_start)
    context_helper = profile_source[helper_start:helper_end]

    assert refresh < profile_load < team_load < billing_load
    assert "clearChatbotContext();" in context_helper
    assert "window.location" not in context_helper
    assert "validateChatbotContext(chatbotContext)" not in profile_source


def test_all_chatbot_access_helpers_scope_by_current_company():
    source = Path("app/utils/access_control.py").read_text(encoding="utf-8")
    assert "company_id = get_current_company_id()" in source
    assert '.eq("company_id", company_id)' in source


def test_all_bot_id_route_handlers_have_an_ownership_gate():
    route_files = [Path("app/views.py"), *Path("app/routes").glob("*.py")]
    missing_gates = []

    for path in route_files:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_route = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "route"
                for decorator in node.decorator_list
            )
            function_source = ast.get_source_segment(source, node) or ""
            if not is_route or not (
                "chatbot_id" in function_source or "bot_id" in function_source
            ):
                continue

            has_direct_gate = "verify_chatbot_access(" in function_source
            has_company_scoped_bot_service = any(
                call in function_source
                for call in (
                    "get_bot(",
                    "edit_bot(",
                    "remove_bot(",
                    "restore_archived_bot(",
                    "permanently_delete_archived_bot(",
                )
            )
            # Public website-widget endpoints have no logged-in company to
            # scope against. Their tenancy gate is the unguessable public key:
            # _load_widget_or_error() resolves the widget row (which carries
            # its own chatbot_id and company_id), then enforces that the
            # widget is enabled, the chatbot is active, and the calling
            # origin is on the widget's domain allowlist.
            has_public_widget_gate = "_load_widget_or_error(" in function_source

            if not (
                has_direct_gate
                or has_company_scoped_bot_service
                or has_public_widget_gate
            ):
                missing_gates.append(f"{path}:{node.lineno}:{node.name}")

    assert missing_gates == []
