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


# --- claim semantics -------------------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    """Enough of the Supabase query builder to exercise the claim path."""

    def __init__(self, store):
        self.store = store
        self.mode = None
        self.filters = []
        self.patch = None
        self.max_rows = None

    def select(self, *_args):
        self.mode = "select"
        return self

    def update(self, data):
        self.mode = "update"
        self.patch = data
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def lt(self, field, value):
        self.filters.append(("lt", field, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        self.max_rows = count
        return self

    def _matches(self, row):
        for op, field, value in self.filters:
            if op == "eq" and row.get(field) != value:
                return False
            if op == "lt" and not str(row.get(field, "")) < str(value):
                return False
        return True

    def execute(self):
        rows = [row for row in self.store if self._matches(row)]
        if self.mode == "select":
            if self.max_rows is not None:
                rows = rows[: self.max_rows]
            return _Result([dict(row) for row in rows])
        changed = []
        for row in rows:
            row.update(self.patch)
            changed.append(dict(row))
        return _Result(changed)


class _FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, _name):
        return _FakeTable(self.store)


def _event(event_id, status, updated_at=None):
    now = datetime.now(timezone.utc)
    return {
        "id": event_id,
        "company_id": 42,
        "chatbot_id": 7,
        "event_type": "crm_stage_transition",
        "status": status,
        "idempotency_key": "key-" + str(event_id),
        "payload": {},
        "created_at": now.isoformat(),
        "updated_at": (updated_at or now).isoformat(),
    }


def test_claim_flips_queued_events_to_running_and_is_not_repeatable():
    store = [_event(1, "queued"), _event(2, "queued")]
    with patch.object(repo, "supabase", _FakeSupabase(store)):
        first = repo.claim_queued_automation_events(limit=10, lease_seconds=300)
        second = repo.claim_queued_automation_events(limit=10, lease_seconds=300)

    assert sorted(row["id"] for row in first) == [1, 2]
    assert all(row["status"] == "running" for row in first)
    # A second worker polling straight after finds nothing left to claim.
    assert second == []


def test_claim_re_offers_a_running_event_whose_lease_expired():
    stale = datetime.now(timezone.utc) - timedelta(seconds=600)
    store = [_event(1, "running", updated_at=stale)]
    with patch.object(repo, "supabase", _FakeSupabase(store)):
        claimed = repo.claim_queued_automation_events(limit=10, lease_seconds=300)

    assert [row["id"] for row in claimed] == [1]
    assert store[0]["updated_at"] > stale.isoformat()


def test_claim_leaves_a_running_event_inside_its_lease_alone():
    fresh = datetime.now(timezone.utc) - timedelta(seconds=10)
    store = [_event(1, "running", updated_at=fresh)]
    with patch.object(repo, "supabase", _FakeSupabase(store)):
        assert repo.claim_queued_automation_events(limit=10, lease_seconds=300) == []


# --- route guard -----------------------------------------------------------


def test_claim_route_rejects_a_missing_or_wrong_token(client, worker_env):
    assert client.post("/api/automation/worker/events").status_code == 403
    response = client.post(
        "/api/automation/worker/events",
        headers={"Authorization": "Bearer wrong-token-wrong-token-wrong-token"},
    )
    assert response.status_code == 403


def test_worker_routes_fail_closed_when_the_token_is_unset(client, monkeypatch):
    monkeypatch.setenv("N8N_WORKER_ENABLED", "true")
    monkeypatch.delenv("N8N_WORKER_TOKEN", raising=False)

    response = client.post("/api/automation/worker/events", headers=WORKER_HEADERS)
    assert response.status_code == 503


def test_worker_routes_reject_a_token_shorter_than_the_minimum(client, monkeypatch):
    monkeypatch.setenv("N8N_WORKER_ENABLED", "true")
    monkeypatch.setenv("N8N_WORKER_TOKEN", "short")

    response = client.post(
        "/api/automation/worker/events", headers={"Authorization": "Bearer short"}
    )
    assert response.status_code == 503


def test_claim_route_is_disabled_until_the_flag_is_flipped(client, monkeypatch):
    monkeypatch.setenv("N8N_WORKER_TOKEN", TOKEN)
    monkeypatch.setenv("N8N_WORKER_ENABLED", "false")

    response = client.post("/api/automation/worker/events", headers=WORKER_HEADERS)
    assert response.status_code == 503


def test_claim_route_hands_back_leased_events(client, worker_env):
    with patch(
        "app.routes.automation_routes.claim_queued_automation_events",
        return_value=[_event(1, "running")],
    ) as claim:
        response = client.post(
            "/api/automation/worker/events", headers=WORKER_HEADERS, json={"limit": 5}
        )

    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["events"][0]["id"] == 1
    assert body["lease_seconds"] == worker_lease_seconds()
    claim.assert_called_once_with(limit=5, lease_seconds=worker_lease_seconds())


def test_claim_route_rejects_a_non_integer_limit(client, worker_env):
    response = client.post(
        "/api/automation/worker/events", headers=WORKER_HEADERS, json={"limit": "all"}
    )
    assert response.status_code == 400


# --- status callback -------------------------------------------------------


def test_status_callback_takes_tenancy_from_the_stored_row(client, worker_env):
    stored = _event(9, "running")
    with patch(
        "app.routes.automation_routes.get_automation_event_by_id", return_value=stored
    ), patch(
        "app.routes.automation_routes.update_automation_event_status",
        return_value=dict(stored, status="completed"),
    ) as update:
        response = client.post(
            "/api/automation/worker/events/9/status",
            headers=WORKER_HEADERS,
            json={"status": "completed", "company_id": 999, "chatbot_id": 999},
        )

    assert response.status_code == 200
    update.assert_called_once_with(
        company_id=42,
        chatbot_id=7,
        event_id=9,
        status="completed",
        result=None,
        error_message=None,
    )


def test_status_callback_is_idempotent_on_an_already_finished_event(client, worker_env):
    stored = _event(9, "completed")
    with patch(
        "app.routes.automation_routes.get_automation_event_by_id", return_value=stored
    ), patch(
        "app.routes.automation_routes.update_automation_event_status"
    ) as update:
        response = client.post(
            "/api/automation/worker/events/9/status",
            headers=WORKER_HEADERS,
            json={"status": "failed"},
        )

    assert response.status_code == 200
    assert response.get_json()["data"]["changed"] is False
    update.assert_not_called()


def test_status_callback_refuses_an_unclaimed_event(client, worker_env):
    with patch(
        "app.routes.automation_routes.get_automation_event_by_id",
        return_value=_event(9, "queued"),
    ):
        response = client.post(
            "/api/automation/worker/events/9/status",
            headers=WORKER_HEADERS,
            json={"status": "completed"},
        )

    assert response.status_code == 409


def test_status_callback_refuses_a_status_the_worker_may_not_set(client, worker_env):
    for status in ("queued", "running", "blocked", ""):
        response = client.post(
            "/api/automation/worker/events/9/status",
            headers=WORKER_HEADERS,
            json={"status": status},
        )
        assert response.status_code == 400, status


def test_status_callback_returns_404_for_an_unknown_event(client, worker_env):
    with patch(
        "app.routes.automation_routes.get_automation_event_by_id", return_value=None
    ):
        response = client.post(
            "/api/automation/worker/events/9/status",
            headers=WORKER_HEADERS,
            json={"status": "completed"},
        )

    assert response.status_code == 404
