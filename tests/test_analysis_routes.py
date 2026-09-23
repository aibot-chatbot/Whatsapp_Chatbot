"""Merchant permissions, request authority and private download boundary."""
from unittest.mock import patch
from uuid import uuid4

import pytest
from app import create_app
from app.services.billing_guard import BillingLimitError

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
    denied = BillingLimitError("Not on this plan", code="feature_not_available")
    with patch("app.routes.analysis_routes.can_use_plan_feature", side_effect=denied), \
         patch("app.routes.analysis_routes.read_export") as read:
        response = client.get(BASE + f"/reports/{REPORT_ID}/download", headers=HEADERS)
        assert response.status_code == 403 and response.json["code"] == "feature_not_available"
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


# --- automation_workflows (Pro-only automatic working flows) ----------------

GATE = "app.routes.analysis_routes.can_use_plan_feature"
INTERNAL = {"Authorization": "Bearer " + "x" * 40}


def _deny(feature):
    def gate(_company_id, key):
        if key == feature:
            raise BillingLimitError("Not on this plan", code="feature_not_available")
        return True
    return gate


def test_enabling_a_schedule_requires_automation_workflows(client, auth):
    with patch(GATE, side_effect=_deny("automation_workflows")), \
         patch("app.routes.analysis_routes.repo.upsert_schedule") as upsert:
        response = client.post(BASE + "/schedules", json={"frequency": "weekly", "enabled": True}, headers=HEADERS)
    assert response.status_code == 403 and response.json["code"] == "feature_not_available"
    upsert.assert_not_called()


def test_disabling_a_schedule_never_needs_automation_workflows(client, auth):
    with patch(GATE, side_effect=_deny("automation_workflows")), \
         patch("app.routes.analysis_routes.repo.upsert_schedule", return_value={"enabled": False}) as upsert:
        response = client.post(BASE + "/schedules", json={"frequency": "weekly", "enabled": False}, headers=HEADERS)
    assert response.status_code == 200
    upsert.assert_called_once()


def test_enabling_recording_requires_automation_workflows(client, auth):
    with patch(GATE, side_effect=_deny("automation_workflows")), \
         patch("app.database.business_observation_repository.set_recording_enabled") as update:
        response = client.post(BASE + "/recording", json={"enabled": True}, headers=HEADERS)
    assert response.status_code == 403
    update.assert_not_called()


def test_disabling_recording_never_needs_automation_workflows(client, auth):
    with patch(GATE, side_effect=_deny("automation_workflows")), \
         patch("app.database.business_observation_repository.set_recording_enabled", return_value=False) as update:
        response = client.post(BASE + "/recording", json={"enabled": False}, headers=HEADERS)
    assert response.status_code == 200
    update.assert_called_once_with(42, 7, False)


def test_manual_report_needs_only_ai_generated_reports(client, auth):
    with patch(GATE, side_effect=_deny("automation_workflows")) as gate, \
         patch("app.routes.analysis_routes.repo.create_report_request", return_value={"id": REPORT_ID, "status": "queued"}):
        response = client.post(BASE + "/messages", headers=HEADERS, json={"text": "Bookings", "client_message_id": "one"})
    assert response.status_code == 202
    assert [call.args[1] for call in gate.call_args_list] == ["ai_generated_reports"]


def test_manual_request_cannot_borrow_the_scheduled_key_space(client, auth):
    with patch("app.routes.analysis_routes.repo.create_report_request") as create:
        response = client.post(BASE + "/messages", headers=HEADERS,
                               json={"text": "Bookings", "client_message_id": "schedule:abc:weekly"})
    assert response.status_code == 400
    create.assert_not_called()


def _schedule(index, company_id):
    return {"id": f"00000000-0000-4000-8000-{index:012d}", "company_id": company_id, "chatbot_id": 7,
            "actor_user_id": 31, "frequency": "weekly", "enabled": True}


class DueQueue:
    """list_due_schedules over a mutable due set, honouring limit/offset."""

    def __init__(self, rows):
        self.rows = rows
        self.due = {row["id"] for row in rows}

    def list(self, *, limit=100, offset=0, now=None):
        return [row for row in self.rows if row["id"] in self.due][offset:offset + limit]

    def leave(self, schedule_id):
        self.due.discard(schedule_id)


def _tick(client, monkeypatch):
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "x" * 40)
    return client.post("/internal/analysis/schedules/tick", headers=INTERNAL, json={})


def test_plan_denied_schedules_cannot_starve_pro_tenants(client, monkeypatch):
    # 250 downgraded schedules sit ahead of one Pro schedule and none of them
    # can even be moved (their actor left): the tick must still reach Pro.
    rows = [_schedule(i, company_id=100 + i) for i in range(250)] + [_schedule(999, company_id=42)]
    queue = DueQueue(rows)

    def gate(company_id, _key):
        if company_id != 42:
            raise BillingLimitError("Not on this plan", code="feature_not_available")
        return True

    def enqueue(company_id, _chatbot_id, schedule_id, **_period):
        queue.leave(schedule_id)
        return {"enqueued": True}

    with patch(GATE, side_effect=gate), \
         patch("app.routes.analysis_routes.repo.list_due_schedules", side_effect=queue.list), \
         patch("app.routes.analysis_routes.repo.skip_schedule_period", side_effect=PermissionError()), \
         patch("app.routes.analysis_routes.repo.enqueue_schedule_report", side_effect=enqueue) as enqueued:
        response = _tick(client, monkeypatch)

    assert response.status_code == 200
    assert response.json["data"]["enqueued"] == 1
    assert [call.args[0] for call in enqueued.call_args_list] == [42]


def test_plan_denied_schedule_skips_its_period_instead_of_blocking(client, monkeypatch):
    rows = [_schedule(1, company_id=100)]
    queue = DueQueue(rows)

    def skip(schedule, *, next_due_at):
        queue.leave(schedule["id"])
        return {**schedule, "next_due_at": next_due_at}

    with patch(GATE, side_effect=_deny("automation_workflows")), \
         patch("app.routes.analysis_routes.repo.list_due_schedules", side_effect=queue.list), \
         patch("app.routes.analysis_routes.repo.skip_schedule_period", side_effect=skip) as skipped, \
         patch("app.routes.analysis_routes.repo.enqueue_schedule_report") as enqueued:
        response = _tick(client, monkeypatch)

    assert response.status_code == 200
    assert response.json["data"] == {"enqueued": 0, "skipped": 1}
    enqueued.assert_not_called()
    assert skipped.call_args.args[0]["id"] == rows[0]["id"]
    assert skipped.call_args.kwargs["next_due_at"]


def test_transient_billing_failure_never_skips_a_pro_period(client, monkeypatch):
    rows = [_schedule(1, company_id=42)]
    unknown = BillingLimitError("No active subscription plan.", code="no_subscription")
    with patch(GATE, side_effect=unknown), \
         patch("app.routes.analysis_routes.schedule_owner_durably_unentitled", return_value=False), \
         patch("app.routes.analysis_routes.repo.list_due_schedules", side_effect=DueQueue(rows).list), \
         patch("app.routes.analysis_routes.repo.skip_schedule_period") as skipped, \
         patch("app.routes.analysis_routes.repo.enqueue_schedule_report") as enqueued:
        response = _tick(client, monkeypatch)
    assert response.status_code == 200
    skipped.assert_not_called()
    enqueued.assert_not_called()


def test_churned_subscription_skips_its_period_instead_of_piling_up(client, monkeypatch):
    # Cancelled/expired Pro rows sort first by next_due_at; left "still due"
    # they would fill the page ceiling and starve live Pro schedules.
    rows = [_schedule(1, company_id=42)]
    churned = BillingLimitError("No active subscription plan.", code="no_subscription")
    with patch(GATE, side_effect=churned), \
         patch("app.routes.analysis_routes.schedule_owner_durably_unentitled", return_value=True), \
         patch("app.routes.analysis_routes.repo.list_due_schedules", side_effect=DueQueue(rows).list), \
         patch("app.routes.analysis_routes.repo.skip_schedule_period") as skipped, \
         patch("app.routes.analysis_routes.repo.enqueue_schedule_report") as enqueued:
        response = _tick(client, monkeypatch)
    assert response.status_code == 200
    assert response.get_json()["data"]["skipped"] == 1
    skipped.assert_called_once()
    enqueued.assert_not_called()


def test_one_tenants_enqueue_failure_does_not_abort_the_tick(client, monkeypatch):
    from app.database.analysis_repository import AnalysisRateLimited

    rows = [_schedule(1, company_id=41), _schedule(2, company_id=42)]
    queue = DueQueue(rows)

    def enqueue(company_id, _chatbot_id, schedule_id, **_period):
        if company_id == 41:
            raise AnalysisRateLimited("10 pending reports")
        queue.leave(schedule_id)
        return {"enqueued": True}

    with patch(GATE, return_value=True) as gate, \
         patch("app.routes.analysis_routes.repo.list_due_schedules", side_effect=queue.list), \
         patch("app.routes.analysis_routes.repo.enqueue_schedule_report", side_effect=enqueue):
        response = _tick(client, monkeypatch)

    assert response.status_code == 200
    assert response.json["data"]["enqueued"] == 1
    assert {call.args[1] for call in gate.call_args_list} == {"ai_generated_reports", "automation_workflows"}


def test_due_schedules_page_with_a_stable_order_and_offset(monkeypatch):
    from unittest.mock import MagicMock
    from app.database import analysis_repository as repository

    query = MagicMock()
    for method in ("table", "select", "eq", "lte", "order", "range"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = []
    monkeypatch.setattr(repository, "supabase", query)

    assert repository.list_due_schedules(limit=100, offset=200) == []
    query.range.assert_called_once_with(200, 299)
    assert [call.args[0] for call in query.order.call_args_list] == ["next_due_at", "id"]
    with pytest.raises(ValueError):
        repository.list_due_schedules(offset=-1)


def test_skipping_a_period_goes_through_the_schedule_rpc(monkeypatch):
    from unittest.mock import MagicMock
    from app.database import analysis_repository as repository

    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = {"id": "s"}
    monkeypatch.setattr(repository, "supabase", db)

    repository.skip_schedule_period(_schedule(1, company_id=42), next_due_at="2099-01-05T01:00:00+00:00")
    name, params = db.rpc.call_args.args
    assert name == "analysis_upsert_schedule"
    assert params["p_enabled"] is True and params["p_next_due_at"] == "2099-01-05T01:00:00+00:00"
    assert params["p_company_id"] == 42 and params["p_actor_user_id"] == 31
    db.table.assert_not_called()


def test_disabling_a_schedule_goes_through_the_schedule_rpc(monkeypatch):
    from unittest.mock import MagicMock
    from app.database import analysis_repository as repository

    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = {"id": "s"}
    monkeypatch.setattr(repository, "supabase", db)

    repository.disable_schedule(_schedule(1, company_id=42))
    name, params = db.rpc.call_args.args
    assert name == "analysis_upsert_schedule"
    assert params["p_enabled"] is False and params["p_frequency"] == "weekly"
