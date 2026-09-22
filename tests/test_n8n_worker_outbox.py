"""The n8n outbox drain: token guard, lease reclaim, and idempotent callbacks.

These cover the properties that make n8n safe to add beside Langflow - it can
only advance work Flask already queued, it cannot aim an update at a row it was
not handed, and a retried callback never reopens settled work.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app import create_app
from app.database import automation_event_repository as repo
from app.services.n8n_adapter import (
    DEFAULT_LEASE_SECONDS,
    MAX_LEASE_SECONDS,
    MIN_LEASE_SECONDS,
    n8n_automation_health,
    n8n_worker_enabled,
    worker_lease_seconds,
)


TOKEN = "t" * 48
WORKER_HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def worker_env(monkeypatch):
    monkeypatch.setenv("N8N_WORKER_ENABLED", "true")
    monkeypatch.setenv("N8N_WORKER_TOKEN", TOKEN)
    monkeypatch.setenv("N8N_BASE_URL", "http://127.0.0.1:5678")
    monkeypatch.setenv("N8N_ALLOW_INSECURE_LOCAL", "true")
    yield


# --- adapter ---------------------------------------------------------------


def test_worker_is_disabled_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv("N8N_WORKER_ENABLED", raising=False)
    assert n8n_worker_enabled() is False
    assert n8n_automation_health() == {"status": "disabled"}


def test_health_reports_not_configured_for_non_https_remote_host(monkeypatch):
    monkeypatch.setenv("N8N_WORKER_ENABLED", "true")
    monkeypatch.setenv("N8N_BASE_URL", "http://n8n.internal")
    monkeypatch.setenv("N8N_WORKER_TOKEN", TOKEN)
    monkeypatch.delenv("N8N_ALLOW_INSECURE_LOCAL", raising=False)

    assert n8n_automation_health() == {"status": "not_configured"}


def test_lease_is_clamped_and_falls_back_on_garbage(monkeypatch):
    monkeypatch.setenv("N8N_WORKER_LEASE_SECONDS", "1")
    assert worker_lease_seconds() == MIN_LEASE_SECONDS
    monkeypatch.setenv("N8N_WORKER_LEASE_SECONDS", "999999")
    assert worker_lease_seconds() == MAX_LEASE_SECONDS
    monkeypatch.setenv("N8N_WORKER_LEASE_SECONDS", "not-a-number")
    assert worker_lease_seconds() == DEFAULT_LEASE_SECONDS


# RPC contracts are unit checks, not database concurrency evidence.
LEASE = "ea818f88-f346-42cb-b710-d4be5f96c61d"


def _event(event_id=9, status="running", kind="knowledge_document_follow_up"):
    return {"id":event_id,"company_id":42,"chatbot_id":7,"event_type":kind,
            "status":status,"lease_token":LEASE}


def test_claim_uses_atomic_rpc_and_server_kind():
    with patch.object(repo, "supabase") as db:
        db.rpc.return_value.execute.return_value.data = [_event()]
        assert repo.claim_queued_automation_events(limit=1, worker_kind="agent_report") == [_event()]
    db.rpc.assert_called_once_with("claim_automation_events_v1", {
        "p_worker_kind":"agent_report","p_limit":1,"p_lease_seconds":300})


@pytest.mark.parametrize("kwargs", [{"worker_kind":"crm"},{"limit":True},{"limit":0}])
def test_claim_rejects_invalid_contract(kwargs):
    with pytest.raises(ValueError): repo.claim_queued_automation_events(**kwargs)


def test_no_fallback_when_migration_rpc_missing():
    with patch.object(repo, "supabase") as db:
        db.rpc.side_effect=RuntimeError("missing RPC")
        with pytest.raises(RuntimeError): repo.claim_queued_automation_events()
        db.table.assert_not_called()


def test_worker_routes_require_configured_token(client, monkeypatch):
    monkeypatch.setenv("N8N_WORKER_ENABLED","true")
    for token in ("", "short"):
        monkeypatch.setenv("N8N_WORKER_TOKEN",token)
        assert client.post("/api/automation/worker/events",headers=WORKER_HEADERS).status_code==503


def test_worker_rejects_wrong_token(client,worker_env):
    assert client.post("/api/automation/worker/events").status_code==403


def test_worker_disabled(client,worker_env,monkeypatch):
    monkeypatch.setenv("N8N_WORKER_ENABLED","false")
    assert client.post("/api/automation/worker/events",headers=WORKER_HEADERS).status_code==503


def test_claim_route_owns_kind(client,worker_env):
    with patch("app.routes.automation_routes.claim_queued_automation_events",return_value=[_event()]) as claim:
        response=client.post("/api/automation/worker/events",headers=WORKER_HEADERS,json={"limit":5,"worker_kind":"agent_report"})
    assert response.status_code==200
    claim.assert_called_once_with(limit=5,lease_seconds=worker_lease_seconds(),worker_kind="n8n")


@pytest.mark.parametrize("body", [[1], {"limit":"all"},{"limit":True}])
def test_claim_bad_body(client,worker_env,body):
    assert client.post("/api/automation/worker/events",headers=WORKER_HEADERS,json=body).status_code==400


def test_callback_uses_lease_not_caller_tenant(client,worker_env):
    with patch("app.routes.automation_routes.get_automation_event_by_id",return_value=_event()), patch(
        "app.routes.automation_routes.finish_automation_event",return_value=_event(status="completed")) as finish:
        response=client.post("/api/automation/worker/events/9/status",headers=WORKER_HEADERS,
            json={"status":"completed","lease_token":LEASE,"company_id":999,"chatbot_id":999})
    assert response.status_code==200
    finish.assert_called_once_with(event_id=9,lease_token=LEASE,worker_kind="n8n",status="completed",result=None,error_message=None,retryable=False)


@pytest.mark.parametrize("kind", ["crm_stage_transition","agent_report"])
def test_n8n_cannot_finish_other_kinds(client,worker_env,kind):
    with patch("app.routes.automation_routes.get_automation_event_by_id",return_value=_event(kind=kind)), patch(
        "app.routes.automation_routes.finish_automation_event") as finish:
        response=client.post("/api/automation/worker/events/9/status",headers=WORKER_HEADERS,json={"status":"completed","lease_token":LEASE})
    assert response.status_code==404
    finish.assert_not_called()


def test_expired_or_replaced_lease_is_conflict(client,worker_env):
    with patch("app.routes.automation_routes.get_automation_event_by_id",return_value=_event()), patch(
        "app.routes.automation_routes.finish_automation_event",return_value=None):
        response=client.post("/api/automation/worker/events/9/status",headers=WORKER_HEADERS,json={"status":"completed","lease_token":LEASE})
    assert response.status_code==409


def test_missing_lease_is_bad_request(client,worker_env):
    with patch("app.routes.automation_routes.get_automation_event_by_id",return_value=_event()):
        response=client.post("/api/automation/worker/events/9/status",headers=WORKER_HEADERS,json={"status":"completed"})
    assert response.status_code==400


def test_finished_callback_still_checks_token_in_rpc(client,worker_env):
    with patch("app.routes.automation_routes.get_automation_event_by_id",return_value=_event(status="completed")), patch(
        "app.routes.automation_routes.finish_automation_event",return_value=None) as finish:
        response=client.post("/api/automation/worker/events/9/status",headers=WORKER_HEADERS,json={"status":"completed","lease_token":LEASE})
    assert response.status_code==409
    finish.assert_called_once()


def test_heartbeat_fenced_and_kind_owned(client,worker_env):
    with patch("app.routes.automation_routes.renew_automation_event_lease",return_value=None) as renew:
        response=client.post("/api/automation/worker/events/9/renew",headers=WORKER_HEADERS,json={"lease_token":LEASE,"worker_kind":"agent_report"})
    assert response.status_code==409
    renew.assert_called_once_with(event_id=9,lease_token=LEASE,worker_kind="n8n",lease_seconds=worker_lease_seconds())


def test_finish_validates_outcome_before_rpc():
    with patch.object(repo,"supabase") as db:
        for kwargs in ({"status":[]},{"status":"running"},{"status":"failed","retryable":"true"},{"status":"completed","result":[]}):
            with pytest.raises(ValueError):repo.finish_automation_event(event_id=9,lease_token=LEASE,worker_kind="n8n",**kwargs)
        db.rpc.assert_not_called()


@pytest.mark.parametrize("path,body",[("/api/automation/worker/events",[]),("/api/automation/worker/events/9/status",{"status":[]})])
def test_worker_rejects_non_scalar_outcome_and_empty_array_body(client,worker_env,path,body):
    response=client.post(path,headers=WORKER_HEADERS,json=body)
    assert response.status_code==400
