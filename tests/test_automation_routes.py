from unittest.mock import patch

import pytest

from app import create_app


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
USER = {
    "id": 31,
    "company_id": 42,
    "email": "automation@example.test",
    "role": "owner",
    "status": "active",
}


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def authenticated():
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": 42, "role": "owner"},
    ), patch(
        "app.database.user_repository.get_user_by_id", return_value=USER
    ):
        yield


def test_event_monitoring_is_company_scoped(client, authenticated):
    with patch(
        "app.routes.automation_routes.verify_chatbot_access",
        return_value={"id": 7, "company_id": 42},
    ), patch(
        "app.routes.automation_routes.list_automation_events",
        return_value=[{"id": 1, "company_id": 42, "chatbot_id": 7}],
    ) as list_events:
        response = client.get(
            "/api/automation/events?chatbot_id=7&status=queued",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["data"]["events"][0]["company_id"] == 42
    list_events.assert_called_once_with(
        company_id=42,
        chatbot_id=7,
        status="queued",
        limit=50,
    )


def test_crm_stage_automation_requires_tenant_verified_chatbot(client, authenticated):
    result = {
        "changed": True,
        "lead": {"id": 5, "status": "qualified"},
        "event": {"id": 9, "status": "completed"},
    }
    with patch(
        "app.routes.automation_routes.verify_chatbot_access",
        return_value={"id": 7, "company_id": 42},
    ) as verify, patch(
        "app.routes.automation_routes.apply_crm_stage_automation",
        return_value=result,
    ) as apply:
        response = client.post(
            "/api/automation/crm-stage",
            json={
                "chatbot_id": 7,
                "lead_id": 5,
                "target_status": "qualified",
                "reason": "follow-up completed",
            },
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    verify.assert_called_once_with(7)
    apply.assert_called_once_with(
        company_id=42,
        chatbot_id=7,
        lead_id=5,
        target_status="qualified",
        reason="follow-up completed",
        idempotency_key=None,
    )


def test_automation_health_reports_degraded_when_event_table_is_unavailable(client):
    with patch(
        "app.routes.automation_routes.automation_events_table_available",
        return_value=False,
    ):
        response = client.get("/api/automation/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "degraded",
        "checks": {"automation_events": False},
    }
