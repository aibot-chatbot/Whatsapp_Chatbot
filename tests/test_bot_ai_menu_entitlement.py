import os
import sys
import types
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

if "google" not in sys.modules:
    google_mod = types.ModuleType("google")
    google_mod.genai = types.ModuleType("google.genai")
    google_mod.genai.Client = MagicMock()
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = google_mod.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "_tools" not in sys.modules:
    sys.modules["_tools"] = types.ModuleType("_tools")

from app import create_app
from app.services.billing_guard import BillingLimitError


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
CURRENT_COMPANY_ID = 28
FOREIGN_COMPANY_ID = 99
USER_ID = 31
BOT_ID = 29
CURRENT_USER = {
    "id": USER_ID,
    "company_id": CURRENT_COMPANY_ID,
    "email": "tenant-28@example.test",
    "role": "admin",
    "status": "active",
}
BOT = {"id": BOT_ID, "company_id": CURRENT_COMPANY_ID, "bot_name": "Menu Bot"}


def _client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _auth_context():
    return patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={
            "user_id": USER_ID,
            "company_id": FOREIGN_COMPANY_ID,
            "role": "owner",
        },
    )


def _current_user():
    return patch("app.database.user_repository.get_user_by_id", return_value=CURRENT_USER)


def test_disabled_plan_cannot_generate_ai_menu():
    client = _client()
    denial = BillingLimitError(
        'The feature "ai_assisted_menu_generation" is not available on your current subscription plan.',
        code="feature_not_available",
        details={"feature_key": "ai_assisted_menu_generation"},
    )

    with _auth_context(), _current_user(), patch(
        "app.routes.bot_routes.get_bot", return_value=BOT
    ) as get_bot, patch(
        "app.routes.bot_routes.can_use_plan_feature", side_effect=denial
    ) as feature_gate, patch(
        "app.services.ai_router.generate_welcome_menu_suggestions"
    ) as generate:
        response = client.post(
            f"/api/bots/{BOT_ID}/generate-welcome-menu",
            json={"company_id": FOREIGN_COMPANY_ID},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    body = response.get_json()
    assert body["code"] == "feature_not_available"
    assert body["details"]["feature_key"] == "ai_assisted_menu_generation"
    get_bot.assert_called_once_with(BOT_ID, CURRENT_COMPANY_ID)
    feature_gate.assert_called_once_with(
        CURRENT_COMPANY_ID, "ai_assisted_menu_generation"
    )
    generate.assert_not_called()


def test_enabled_plan_can_generate_ai_menu_with_existing_response_shape():
    client = _client()

    with _auth_context(), _current_user(), patch(
        "app.routes.bot_routes.get_bot", return_value=BOT
    ), patch(
        "app.routes.bot_routes.can_use_plan_feature", return_value=True
    ) as feature_gate, patch(
        "app.services.ai_router.generate_welcome_menu_suggestions",
        return_value=(
            [{"label": "Pricing", "description": "View packages"}],
            "primary.pdf",
        ),
    ) as generate:
        response = client.post(
            f"/api/bots/{BOT_ID}/generate-welcome-menu",
            json={},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"] == [{"label": "Pricing", "description": "View packages"}]
    assert body["source_document"] == "primary.pdf"
    feature_gate.assert_called_once_with(
        CURRENT_COMPANY_ID, "ai_assisted_menu_generation"
    )
    generate.assert_called_once_with(BOT_ID, CURRENT_COMPANY_ID)


def test_direct_api_call_cannot_bypass_ai_menu_restriction():
    client = _client()
    denial = BillingLimitError(
        "Upgrade required.",
        code="feature_not_available",
        details={"feature_key": "ai_assisted_menu_generation"},
    )

    with _auth_context(), _current_user(), patch(
        "app.routes.bot_routes.get_bot", return_value=BOT
    ), patch(
        "app.routes.bot_routes.can_use_plan_feature", side_effect=denial
    ), patch(
        "app.services.ai_router.generate_welcome_menu_suggestions"
    ) as generate:
        response = client.post(
            f"/api/bots/{BOT_ID}/generate-welcome-menu",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    generate.assert_not_called()


def test_client_supplied_foreign_company_id_cannot_grant_ai_menu_access():
    client = _client()

    def gate(company_id, feature_key):
        assert feature_key == "ai_assisted_menu_generation"
        if company_id == FOREIGN_COMPANY_ID:
            return True
        raise BillingLimitError(
            "Upgrade required.",
            code="feature_not_available",
            details={"feature_key": feature_key},
        )

    with _auth_context(), _current_user(), patch(
        "app.routes.bot_routes.get_bot", return_value=BOT
    ) as get_bot, patch(
        "app.routes.bot_routes.can_use_plan_feature", side_effect=gate
    ) as feature_gate, patch(
        "app.services.ai_router.generate_welcome_menu_suggestions"
    ) as generate:
        response = client.post(
            f"/api/bots/{BOT_ID}/generate-welcome-menu",
            json={"company_id": FOREIGN_COMPANY_ID},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    get_bot.assert_called_once_with(BOT_ID, CURRENT_COMPANY_ID)
    feature_gate.assert_called_once_with(
        CURRENT_COMPANY_ID, "ai_assisted_menu_generation"
    )
    generate.assert_not_called()


def test_allowed_plan_still_surfaces_empty_suggestions_as_existing_400():
    client = _client()

    with _auth_context(), _current_user(), patch(
        "app.routes.bot_routes.get_bot", return_value=BOT
    ), patch(
        "app.routes.bot_routes.can_use_plan_feature", return_value=True
    ), patch(
        "app.services.ai_router.generate_welcome_menu_suggestions",
        return_value=([], "primary.pdf"),
    ) as generate:
        response = client.post(
            f"/api/bots/{BOT_ID}/generate-welcome-menu",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    generate.assert_called_once_with(BOT_ID, CURRENT_COMPANY_ID)
