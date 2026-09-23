"""PUT /api/bots/<id> may only write the fields the bot editor owns.

Before the allowlist the raw request body reached ``update_bot``, so an admin
could move their bot into another tenant (``company_id``) or switch on
Pro-only customer-request recording (``analysis_recording_enabled``).
"""

from unittest.mock import patch

from flask import Flask
import pytest


def _put(json_body):
    from app.routes.bot_routes import bot_blueprint

    app = Flask(__name__)
    app.register_blueprint(bot_blueprint)
    with (
        patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 31}),
        patch("app.database.user_repository.get_user_by_id", return_value={
            "id": 31, "company_id": 28, "role": "admin", "status": "active",
        }),
        patch("app.services.bot_service.get_bot_by_id", return_value={"id": 7, "company_id": 28}),
        patch("app.services.bot_service.update_bot", return_value={"id": 7}) as update,
    ):
        response = app.test_client().put(
            "/api/bots/7", headers={"Authorization": "Bearer test-token"}, json=json_body,
        )
    return response, update


@pytest.mark.parametrize("field,value", [
    ("company_id", 99),
    ("analysis_recording_enabled", True),
    ("id", 8),
    ("status", "archived"),
    ("deleted_at", "2026-09-23T00:00:00Z"),
    ("created_at", "2020-01-01T00:00:00Z"),
    ("deployed_profile_name", "other"),
])
def test_bot_put_rejects_fields_outside_the_editor(field, value):
    response, update = _put({"bot_name": "Support", field: value})

    assert response.status_code == 400
    assert field in response.get_json()["message"]
    update.assert_not_called()


def test_bot_put_rejects_non_object_body():
    response, update = _put(["bot_name"])

    assert response.status_code == 400
    update.assert_not_called()


def test_bot_put_passes_only_editor_fields_through():
    body = {
        "bot_name": "Support",
        "bot_description": "Helps customers",
        "language": "English",
        "temperature": 0.4,
        "telegram_buttons_enabled": True,
        "whatsapp_buttons_enabled": True,
        "telegram_markdown_enabled": False,
        "whatsapp_markdown_enabled": False,
        "welcome_menu_labels": ["Prices"],
    }
    response, update = _put(body)

    assert response.status_code == 200
    update.assert_called_once()
    written = update.call_args.args[1]
    assert set(written) <= set(body)
    assert "company_id" not in written
