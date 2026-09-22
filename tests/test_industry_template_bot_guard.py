"""General bot editing must not bypass the industry confirmation workflow."""

from unittest.mock import patch

from flask import Flask
import pytest


@pytest.mark.parametrize("field", ["industry_template_draft", "industry_template_published"])
def test_bot_put_rejects_internal_industry_state(field):
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
            "/api/bots/7", headers={"Authorization": "Bearer test-token"},
            json={field: {"template_id": "clinic", "template_version": "1.0.0", "confirmed_by": 999}},
        )
    assert response.status_code == 400
    update.assert_not_called()


@pytest.mark.parametrize("custom_prompt", ["", "Reply as our course adviser: {message}"])
def test_confirmed_tuition_prompt_explains_real_booking_entrypoints(monkeypatch, custom_prompt):
    from app.services import rag_service
    from app.services.industry_template_catalog import TEMPLATE_VERSION

    monkeypatch.setenv("TUITION_TRIALS_ENABLED", "true")
    settings = {"custom_prompt": custom_prompt, "industry_template_published": {
        "template_id": "tuition_center", "template_version": TEMPLATE_VERSION, "confirmed_at": "2026-09-22"}}
    with patch.object(rag_service, "get_deployed_settings", return_value=settings) as load:
        prompt = rag_service.build_prompt([], "预约星期六数学试听", [], 7)
    load.assert_called_once_with(7)
    assert "Trial booking guidance:" in prompt
    assert "web chat's trial booking button" in prompt
    assert "/trial <participant name>" in prompt
    assert "Never claim that you reserved, confirmed, cancelled or rescheduled" in prompt
    assert "Never invent booking or appointment numbers" in prompt
    assert "booking service's explicit confirmation" in prompt
    if custom_prompt:
        assert "Reply as our course adviser: 预约星期六数学试听" in prompt


@pytest.mark.parametrize("flag,industry,confirmed,version", [
    ("false", "tuition_center", True, "current"),
    (None, "tuition_center", True, "current"),
    ("true", "clinic", True, "current"),
    ("true", "restaurant", True, "current"),
    ("true", "tuition_center", False, "current"),
    ("true", "tuition_center", True, "unknown"),
])
def test_unavailable_trial_feature_does_not_advertise_booking_entrypoints(monkeypatch, flag, industry, confirmed, version):
    from app.services import rag_service
    from app.services.industry_template_catalog import TEMPLATE_VERSION

    if flag is None:
        monkeypatch.delenv("TUITION_TRIALS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TUITION_TRIALS_ENABLED", flag)
    settings = {"industry_template_published": {"template_id": industry,
        "template_version": TEMPLATE_VERSION if version == "current" else version,
        "confirmed_at": "2026-09-22" if confirmed else None}}
    with patch.object(rag_service, "get_deployed_settings", return_value=settings):
        prompt = rag_service.build_prompt([], "Book a trial", [], 7)
    assert "Trial booking guidance:" not in prompt
    assert "/trial" not in prompt
