"""Publish readiness through the authenticated HTTP and storage boundaries."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, g

from app.routes import testbot_routes as routes
from app.services.billing_guard import BillingLimitError


@pytest.fixture
def lab(monkeypatch):
    from app.services import test_scenario_service as service
    app = Flask(__name__)
    app.secret_key = "test-only-publish-test"
    app.register_blueprint(routes.testbot_blueprint)
    role = {"value": "owner"}
    @app.before_request
    def identity():
        g.company_id, g.user_id, g.role = 3, 8, role["value"]
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **k: {
        "user_id": 8, "role": role["value"], "company_id": 3})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda *_: {
        "id": 8, "company_id": 3, "role": role["value"], "status": "active"})
    access = Mock(return_value={"id": 4, "company_id": 3})
    monkeypatch.setattr(routes, "verify_chatbot_access", access)
    monkeypatch.setenv("PUBLISH_TEST_GATE", "on")
    monkeypatch.setenv("REPLY_CHECK_MODE", "log")
    rows = []
    def latest(bot, company):
        assert (bot, company) == (4, 3)
        return deepcopy(rows[-1]) if rows else None
    def save(**kw):
        assert (kw["chatbot_id"], kw["company_id"]) == (4, 3)
        assert kw.get("conversation_id") is None
        row = {"id": len(rows) + 1, "payload": deepcopy(kw["payload"])}
        rows.append(row)
        return deepcopy(row)
    def replace(bot, company, row_id, revision, run):
        assert (bot, company) == (4, 3)
        row = rows[row_id - 1]
        if row["payload"]["publish_test"]["revision"] != revision:
            return False
        row["payload"] = {"publish_test": deepcopy(run)}
        return True
    monkeypatch.setattr(service.repo, "latest_publish_test", latest)
    monkeypatch.setattr(service.repo, "save_agent_action", save)
    monkeypatch.setattr(service.repo, "replace_publish_test", replace)
    world = {"fingerprint": "v1"}
    monkeypatch.setattr(service, "fingerprint", lambda *_: world["fingerprint"])
    monkeypatch.setattr(service, "build_test_scenarios", lambda _: {"scenarios": [
        {"key": "common", "message": "Question alpha"}, {"key": "fact", "message": "Question beta"}]})
    calls = []
    def generate(message, customer_id, chatbot_id, **kwargs):
        calls.append((message, customer_id, kwargs))
        if world.get("billing"):
            raise BillingLimitError("Existing credit message", code="ai_credit_insufficient")
        if world.get("grade"):
            g.reply_grade = world["grade"]
        else:
            g.reply_grade = {"status": "unchecked", "checks": []}
        return "Private reply"
    monkeypatch.setattr("app.services.ai_router.generate_response", generate)
    client = app.test_client()
    def req(method="GET", suffix="", **body):
        return client.open("/api/testbot/publish-test" + suffix + "?chatbot_id=4",
                           method=method, json=body, headers={"Authorization": "Bearer fake"})
    started = req("POST")
    assert started.status_code == 200, started.get_json()
    data = started.get_json()["data"]
    prefix = "/" + data["run"]["run_id"]
    def answer(key, **extra):
        return req("POST", prefix + "/answer", ticket=data["ticket"], key=key, **extra)
    return SimpleNamespace(**locals())


def test_run_uses_only_server_questions_in_separate_billed_turns(lab):
    assert lab.req("POST", message="Replace questions").status_code == 400
    assert lab.answer("common", message="Fake question").status_code == 400
    assert lab.answer("fact").status_code == 409
    assert lab.req("POST", lab.prefix + "/answer", key="common", ticket="forged").status_code == 400
    assert lab.answer("common").status_code == 200
    assert lab.answer("common").status_code == 200
    assert lab.req().get_json()["data"]["allowed"] is False
    assert lab.answer("fact").get_json()["data"]["state"] == "passed"
    assert [c[0] for c in lab.calls] == ["Question alpha", "Question beta"]
    assert len({c[1] for c in lab.calls}) == 2
    assert all(c[2].get("conversation_id") is None for c in lab.calls)
    assert all(c[1] != routes.TESTBOT_SESSION_ID and c[2]["operation_type"] == routes.OPERATION_TEST_BOT for c in lab.calls)
    assert lab.req().get_json()["data"]["allowed"] is True
    lab.world["fingerprint"] = "v2"
    assert lab.req().get_json()["data"]["state"] == "outdated"
    assert lab.req().get_json()["data"]["allowed"] is False


@pytest.mark.parametrize("role", ["admin", "owner"])
def test_override_requires_every_flag_current_finished_run_and_privilege(lab, role):
    override = lambda keys: lab.req("POST", lab.prefix + "/override", acknowledged_keys=keys)
    assert override([]).status_code == 409
    lab.world["grade"] = {"status": "unchecked", "checks": [{"category": "review", "subtype": "incomplete"}]}
    lab.answer("common")
    lab.world["grade"] = {"status": "attention", "checks": [{"category": "facts", "subtype": "price",
                          "label": "Sensitive label", "value": "Secret matched price"}]}
    state = lab.answer("fact").get_json()["data"]
    assert state["state"] == "needs_review" and not state["allowed"]
    assert state["run"]["flagged_keys"] == ["common", "fact"]
    lab.role["value"] = "member"
    assert override(["common", "fact"]).status_code == 403
    lab.role["value"] = role
    for keys in ([], ["fact"], ["common", "common", "fact"], ["common", "fact", "extra"]):
        assert override(keys).status_code == 400
    assert override(["fact", "common"]).get_json()["data"]["state"] == "overridden"
    audit = lab.rows[-1]["payload"]["publish_test"]["override"]
    assert audit["by_user_id"] == 8 and audit["at"] and sorted(audit["acknowledged_keys"]) == ["common", "fact"]
    for private in ("Question alpha", "Private reply", "Sensitive label", "Secret matched price", lab.data["ticket"]):
        assert private not in str(lab.rows)
    lab.world["fingerprint"] = "changed"
    assert not lab.req().get_json()["data"]["allowed"]
    assert override(["common", "fact"]).status_code == 409


def test_out_of_credits_records_failure_and_existing_message(lab):
    lab.world["billing"] = True
    assert lab.answer("common").get_json()["data"]["reply"] == "Existing credit message"
    lab.world["billing"] = False
    data = lab.answer("fact").get_json()["data"]
    assert not data["allowed"] and data["run"]["flagged_keys"] == ["common"]
    assert "Existing credit message" not in str(lab.rows)


@pytest.mark.parametrize("grade", [
    {"status": "unexpected", "checks": []},
    {"status": "unchecked", "checks": [{"category": "new", "subtype": "unknown"}]},
    {"status": "ok", "checks": [None]},
])
def test_unrecognized_grades_require_review(lab, grade):
    lab.world["grade"] = grade
    assert lab.answer("common").status_code == 200
    data = lab.answer("fact").get_json()["data"]
    assert data["state"] == "needs_review" and not data["allowed"]
    assert data["run"]["flagged_keys"] == ["common", "fact"]


def test_booking_preview_reads_available_slots_without_generating_them(monkeypatch):
    from app.services import availability_service as availability

    monkeypatch.setattr(availability, "_enabled_packages", lambda *_: [{"id": 5, "name": "Tea"}])
    monkeypatch.setattr(availability.repo, "list_closures", lambda *_: [])
    monkeypatch.setattr(availability, "_rows_with_seats", lambda *_: [])
    generate = Mock()
    monkeypatch.setattr(availability, "_top_up", generate)
    with Flask(__name__).test_request_context():
        g.publish_test = True
        assert availability.open_slots(3, 4) == []
        generate.assert_not_called()
        g.publish_test = False
        availability.open_slots(3, 4)
        generate.assert_called_once()


def test_newest_run_supersedes_previous_and_checks_bot_access(lab):
    lab.answer("common")
    lab.answer("fact")
    assert lab.req("POST").get_json()["data"]["allowed"] is False
    assert lab.answer("fact").status_code == 409
    lab.access.side_effect = PermissionError("Denied")
    for method, suffix in [("GET", ""), ("POST", ""), ("POST", lab.prefix + "/answer"), ("POST", lab.prefix + "/override")]:
        assert lab.req(method, suffix).status_code == 403


def test_synthetic_handoff_has_no_customer_history_inbox_or_email(monkeypatch):
    from app.services import chat_pipeline_service as pipeline
    never = Mock(side_effect=AssertionError("Customer state consulted during a publish test"))
    for name in ("get_recent_chat_history", "get_or_create_conversation", "_record_agent_action",
                 "create_crm_lead_from_agent_signal", "_after_reply"):
        monkeypatch.setattr(pipeline, name, never)
    with Flask(__name__).test_request_context():
        result = pipeline.prepare_chat_prompt("I want to speak to a human", "scenario", 4, "web",
                                              conversation={"id": None, "publish_test": True})
        assert g.reply_grade == {"status": "unchecked", "checks": []}
    assert result["intent"] == "handoff_request" and result["direct_reply"]
    never.assert_not_called()


def test_lost_concurrent_claim_never_starts_second_billed_turn(lab, monkeypatch):
    monkeypatch.setattr(lab.service.repo, "replace_publish_test", lambda *_: False)
    assert lab.answer("common").status_code == 409 and lab.calls == []


def test_publish_request_limits_streamed_bodies(lab, monkeypatch):
    from flask import request

    observed = []
    def status(*_):
        observed.append(request.max_content_length)
        return {"allowed": False}
    monkeypatch.setattr(lab.service, "status", status)
    assert lab.req().status_code == 200
    assert observed == [20000]


def test_members_cannot_read_run_or_override_like_test_lab_chat(lab):
    lab.role["value"] = "member"
    assert lab.req().status_code == 403
    assert lab.req("POST").status_code == 403
    assert lab.req("POST", lab.prefix + "/answer", ticket="t", key="common").status_code == 403
    assert lab.req("POST", lab.prefix + "/override", acknowledged_keys=[]).status_code == 403


def test_start_limit_is_per_authenticated_user(monkeypatch):
    from app import create_app
    monkeypatch.setenv("RATELIMIT_ENABLED", "true")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode",
                        lambda token, *a, **kw: {"user_id": int(token)})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id",
                        lambda n: {"id": n, "company_id": 3, "role": "owner", "status": "active"})
    monkeypatch.setattr(routes, "verify_chatbot_access", lambda _: {"company_id": 3})
    start = Mock(return_value={"allowed": False})
    monkeypatch.setattr(routes.publish_test_service, "start", start)
    client = create_app().test_client()
    url = "/api/testbot/publish-test?chatbot_id=4"
    assert client.post(url).status_code == 401
    for user_id in (11, 12):
        headers = {"Authorization": f"Bearer {user_id}"}
        for _ in range(6):
            assert client.post(url, headers=headers, json={}).status_code == 200
        assert client.post(url, headers=headers, json={}).status_code == 429
    assert start.call_count == 12


@pytest.mark.parametrize("switch", ["REPLY_CHECK_MODE", "PUBLISH_TEST_GATE"])
def test_disabled_gate_never_needs_storage(lab, monkeypatch, switch):
    monkeypatch.setenv(switch, "off")
    monkeypatch.setattr(lab.service.repo, "latest_publish_test", Mock(side_effect=AssertionError))
    assert lab.req().get_json()["data"]["allowed"] is True
    from app.utils.access_control import publish_test_block
    assert publish_test_block(4, 3) is None

