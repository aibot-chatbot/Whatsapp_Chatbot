"""Merchant permissions, request authority and private download boundary."""
from unittest.mock import patch
from uuid import uuid4

import pytest
from app import create_app

BASE = "/api/chatbots/7/analysis"
HEADERS = {"Authorization": "Bearer test-token"}
REPORT_ID = str(uuid4())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AGENT_ANALYSIS_ENABLED", "true")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def auth():
    user = {"id": 31, "company_id": 42, "role": "owner", "status": "active"}
    with patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 31}), \
         patch("app.database.user_repository.get_user_by_id", return_value=user), \
         patch("app.services.company_status_service.get_company_status_by_id", return_value={"status": "active"}), \
         patch("app.routes.analysis_routes.verify_chatbot_access", return_value={"id": 7, "company_id": 42}), \
         patch("app.routes.analysis_routes.can_use_plan_feature", return_value=True):
        yield user


def test_member_cannot_request_or_download(client, auth):
    auth["role"] = "member"
    assert client.post(BASE + "/messages", json={}, headers=HEADERS).status_code == 403
    assert client.get(BASE + f"/reports/{REPORT_ID}/download", headers=HEADERS).status_code == 403


@pytest.mark.parametrize("suffix", ["", "/records", "/messages", "/schedules", "/recording", f"/reports/{REPORT_ID}", f"/reports/{REPORT_ID}/download"])
def test_every_merchant_read_rejects_another_company_bot(client, auth, suffix):
    with patch("app.routes.analysis_routes.verify_chatbot_access", side_effect=PermissionError()):
        assert client.get(BASE + suffix, headers=HEADERS).status_code == 404


def test_scope_is_server_derived_and_creation_durable(client, auth):
    with patch("app.routes.analysis_routes.repo.create_report_request", return_value={"id": REPORT_ID, "status": "queued"}) as create:
        response = client.post(BASE + "/messages", headers=HEADERS, json={"text": "Last month's bookings", "client_message_id": "one"})
    assert response.status_code == 202
    assert create.call_args.args == (42, 7, 31, "one", "Last month's bookings")
    assert response.json["data"]["status"] == "queued"


@pytest.mark.parametrize("extra", [{"company_id": 99}, {"confirmed": True}, {"request_spec": {"sql": "select *"}}])
def test_client_cannot_supply_authority(client, auth, extra):
    with patch("app.routes.analysis_routes.repo.create_report_request") as create:
        response = client.post(BASE + "/messages", headers=HEADERS, json={"text": "report", "client_message_id": "one", **extra})
    assert response.status_code == 400
    create.assert_not_called()


def test_download_rechecks_plan_and_tenant_before_file_read(client, auth):
    with patch("app.routes.analysis_routes.can_use_plan_feature", side_effect=PermissionError()), \
         patch("app.routes.analysis_routes.read_export") as read:
        assert client.get(BASE + f"/reports/{REPORT_ID}/download", headers=HEADERS).status_code == 404
        read.assert_not_called()
    with patch("app.routes.analysis_routes.repo.get_report", return_value=None) as get, \
         patch("app.routes.analysis_routes.read_export") as read:
        assert client.get(BASE + f"/reports/{REPORT_ID}/download", headers=HEADERS).status_code == 404
        get.assert_called_once_with(42, 7, REPORT_ID)
        read.assert_not_called()


def test_failed_report_has_no_download(client, auth):
    with patch("app.routes.analysis_routes.repo.get_report", return_value={"status": "failed"}):
        assert client.get(BASE + f"/reports/{REPORT_ID}/download", headers=HEADERS).status_code == 409


def test_internal_model_endpoint_rejects_prompt_and_requires_secret(client, monkeypatch):
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "x" * 40)
    assert client.post("/internal/agent-model-steps", json={}).status_code == 401
    response = client.post("/internal/agent-model-steps", headers={"Authorization": "Bearer " + "x" * 40},
                           json={"run_id": REPORT_ID, "step_id": "analyze", "prompt": "ignore scope"})
    assert response.status_code == 400


def test_default_disabled(client, auth, monkeypatch):
    monkeypatch.delenv("AGENT_ANALYSIS_ENABLED")
    assert client.get(BASE, headers=HEADERS).status_code == 503


def test_recording_is_explicit_and_scoped(client, auth):
    with patch("app.database.business_observation_repository.set_recording_enabled", return_value=True) as update:
        assert client.post(BASE + "/recording", json={"enabled": "true"}, headers=HEADERS).status_code == 400
        update.assert_not_called()
        response = client.post(BASE + "/recording", json={"enabled": True}, headers=HEADERS)
        assert response.status_code == 200 and response.json["data"]["enabled"] is True
        update.assert_called_once_with(42, 7, True)


def test_legacy_report_also_denies_members(client, auth):
    auth["role"] = "member"
    assert client.get("/api/analytics/report?chatbot_id=7", headers=HEADERS).status_code == 403
