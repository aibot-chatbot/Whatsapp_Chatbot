from concurrent.futures import ThreadPoolExecutor
from threading import Event
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
    ), patch(
        "app.routes.automation_routes.langflow_automation_health",
        return_value={"status": "disabled"},
    ), patch(
        "app.routes.automation_routes.n8n_automation_health",
        return_value={"status": "disabled"},
    ):
        response = client.get("/api/automation/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "degraded",
        "checks": {
            "automation_events": False,
            "langflow": {"status": "disabled"},
            "n8n": {"status": "disabled"},
        },
    }


def test_automation_health_reports_degraded_when_langflow_is_unavailable(client):
    with patch(
        "app.routes.automation_routes.automation_events_table_available",
        return_value=True,
    ), patch(
        "app.routes.automation_routes.langflow_automation_health",
        return_value={"status": "unavailable"},
    ), patch(
        "app.routes.automation_routes.n8n_automation_health",
        return_value={"status": "disabled"},
    ):
        response = client.get("/api/automation/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "degraded",
        "checks": {
            "automation_events": True,
            "langflow": {"status": "unavailable"},
            "n8n": {"status": "disabled"},
        },
    }


def test_automation_health_reports_degraded_when_n8n_is_unavailable(client):
    with patch(
        "app.routes.automation_routes.automation_events_table_available",
        return_value=True,
    ), patch(
        "app.routes.automation_routes.langflow_automation_health",
        return_value={"status": "ok"},
    ), patch(
        "app.routes.automation_routes.n8n_automation_health",
        return_value={"status": "unavailable"},
    ):
        response = client.get("/api/automation/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "degraded",
        "checks": {
            "automation_events": True,
            "langflow": {"status": "ok"},
            "n8n": {"status": "unavailable"},
        },
    }


@pytest.mark.parametrize("langflow_status", ["ok", "unavailable"])
def test_health_caches_success_and_failure_until_expiry(client, langflow_status):
    with patch("app.routes.automation_routes.monotonic", return_value=100) as clock, patch(
        "app.routes.automation_routes.automation_events_table_available", return_value=True
    ) as database, patch(
        "app.routes.automation_routes.langflow_automation_health",
        return_value={"status": langflow_status},
    ) as langflow:
        first = client.get("/api/automation/health").get_json()
        clock.return_value = 109
        assert client.get("/api/automation/health").get_json() == first
        database.assert_called_once()
        langflow.assert_called_once()
        clock.return_value = 110
        client.get("/api/automation/health")
        assert database.call_count == langflow.call_count == 2


@pytest.mark.parametrize("warm_cache", [False, True])
def test_health_never_waits_for_probe_or_returns_stale_ok(client, warm_cache):
    entered = Event()
    release = Event()

    def slow_probe():
        entered.set()
        assert release.wait(5), "test did not release the health probe"
        return {"status": "ok"}

    with patch("app.routes.automation_routes.monotonic", return_value=100) as clock, patch(
        "app.routes.automation_routes.automation_events_table_available", return_value=True
    ) as database, patch(
        "app.routes.automation_routes.langflow_automation_health", return_value={"status": "ok"}
    ) as langflow:
        if warm_cache:
            assert client.get("/api/automation/health").get_json()["status"] == "ok"
        clock.return_value = 110
        langflow.side_effect = slow_probe
        with ThreadPoolExecutor(max_workers=1) as pool:
            refresh = pool.submit(client.application.test_client().get, "/api/automation/health")
            try:
                assert entered.wait(2)
                for _ in range(8):
                    response = client.get("/api/automation/health")
                    assert response.status_code == 200
                    assert response.get_json()["status"] == "degraded"
                    assert response.get_json()["checks"]["langflow"]["status"] == "checking"
                assert database.call_count == langflow.call_count == 1 + int(warm_cache)
            finally:
                release.set()
            assert refresh.result(timeout=2).get_json()["status"] == "ok"


def test_health_releases_singleflight_lock_after_unexpected_exception(client):
    with patch(
        "app.routes.automation_routes.automation_events_table_available",
        side_effect=[RuntimeError("synthetic failure"), True],
    ), patch(
        "app.routes.automation_routes.langflow_automation_health", return_value={"status": "ok"}
    ):
        with pytest.raises(RuntimeError, match="synthetic failure"):
            client.get("/api/automation/health")
        assert client.get("/api/automation/health").get_json()["status"] == "ok"
