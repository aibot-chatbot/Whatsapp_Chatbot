from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from app.services import analysis_worker_service as worker
from app.services.billing_guard import BillingLimitError


@pytest.fixture(autouse=True)
def access_guards():
    with patch.object(worker, "ensure_company_operational", create=True) as company, patch.object(
        worker, "can_use_plan_feature", create=True) as feature:
        yield company, feature


@pytest.fixture
def job():
    return {"id": 8, "company_id": 1, "chatbot_id": 2, "event_type": "agent_report",
            "status": "running", "lease_token": str(uuid4()),
            "lease_expires_at": (datetime.now(timezone.utc)+timedelta(seconds=300)).isoformat(),
            "payload": {"report_id": str(uuid4())}}


def report(job):
    return {"id": job["payload"]["report_id"], "company_id": 1, "chatbot_id": 2,
            "automation_event_id": job["id"], "run_id": str(uuid4()),
            "request_text": "本月业务报告", "request_spec": {}, "snapshot": None}


class Lease:
    def __init__(self, *_args): pass
    def __enter__(self): return self
    def __exit__(self, *_args): pass
    def check(self): pass


def test_internal_step_derives_all_scope_and_requires_current_lease(job):
    row = report(job)
    with patch.object(worker.reports, "get_report_by_run_id", return_value=row), patch.object(
        worker.queue, "get_automation_event_by_id", return_value=job), patch(
        "app.services.analysis_report_service.plan_report_request", return_value={"status": "ready"}) as plan:
        worker.execute_model_step(run_id=row["run_id"], step_id="plan")
    assert plan.call_args.kwargs["company_id"] == 1
    assert plan.call_args.kwargs["chatbot_id"] == 2
    assert plan.call_args.kwargs["command"] == row["request_text"]


def test_plan_downgrade_after_request_prevents_model(job, access_guards):
    row = report(job)
    access_guards[1].side_effect = BillingLimitError("Denied", code="feature_not_available")
    with patch.object(worker.reports,"get_report_by_run_id",return_value=row), patch.object(
        worker.queue,"get_automation_event_by_id",return_value=job), patch(
        "app.services.analysis_report_service.plan_report_request") as model:
        with pytest.raises(BillingLimitError):
            worker.execute_model_step(run_id=row["run_id"],step_id="plan")
    model.assert_not_called()


def test_plan_downgrade_after_model_prevents_export_and_publish(job, access_guards):
    row = {**report(job), "snapshot": {"metrics": {"bookings": 1}}}
    def result(**_kwargs):
        access_guards[1].side_effect = BillingLimitError("Denied", code="feature_not_available")
        return {"status": "complete", "narrative": "Report"}
    with patch.object(worker.reports,"get_report",return_value=row),patch.object(worker,"LeaseHeartbeat",Lease),patch.object(
        worker.reports,"finish_report") as finish,patch(
        "app.services.analysis_export_service.export_report") as export:
        with pytest.raises(BillingLimitError):
            worker.process_report_event(job,step_executor=result)
    export.assert_not_called()
    finish.assert_not_called()


@pytest.mark.parametrize("change", [{"company_id":99}, {"status":"queued"},
    {"lease_expires_at":"2000-01-01T00:00:00+00:00"}, {"event_type":"crm_stage_transition"}])
def test_bad_scope_or_lease_cannot_reach_model(job,change):
    row=report(job)
    with patch.object(worker.reports,"get_report_by_run_id",return_value=row), patch.object(
        worker.queue,"get_automation_event_by_id",return_value={**job,**change}), patch(
        "app.services.analysis_report_service.plan_report_request") as model:
        with pytest.raises(worker.LeaseLost):worker.execute_model_step(run_id=row["run_id"],step_id="plan")
    model.assert_not_called()


def test_analyze_requires_saved_snapshot(job):
    row=report(job)
    with patch.object(worker.reports,"get_report_by_run_id",return_value=row),patch.object(
        worker.queue,"get_automation_event_by_id",return_value=job),patch(
        "app.services.analysis_report_service.generate_report") as model:
        with pytest.raises(worker.reports.AnalysisConflict):worker.execute_model_step(run_id=row["run_id"],step_id="analyze")
    model.assert_not_called()


def test_clarification_stops_before_snapshot_or_analyze(job):
    row=report(job);step=Mock(return_value={"status":"needs_input","question":"Which period?"})
    with patch.object(worker.reports,"get_report",return_value=row),patch.object(worker,"LeaseHeartbeat",Lease),patch.object(
        worker.reports,"finish_report",return_value={"status":"needs_input"}) as finish,patch(
        "app.services.analysis_report_service.build_report_snapshot") as build:
        assert worker.process_report_event(job,step_executor=step)["status"]=="needs_input"
    step.assert_called_once_with(run_id=row["run_id"],step_id="plan")
    build.assert_not_called()
    assert finish.call_args.kwargs["status"]=="needs_input"


def test_existing_snapshot_is_reused_and_not_replanned(job):
    row={**report(job),"snapshot":{"metrics":{"bookings":1}}}
    step=Mock(return_value={"status":"complete","snapshot":{"metrics":{"bookings":999}},"narrative":"Summary"})
    with patch.object(worker.reports,"get_report",return_value=row),patch.object(worker,"LeaseHeartbeat",Lease),patch.object(
        worker.reports,"finish_report",return_value={"status":"complete"}) as finish,patch.object(
        worker.reports,"save_snapshot_fenced") as save,patch(
        "app.services.analysis_report_service.build_report_snapshot") as build,patch(
        "app.services.analysis_export_service.export_report",return_value={"content":b"test"}) as export,patch(
        "app.services.analysis_storage_service.store_export",return_value={"version":job["lease_token"]}) as store:
        worker.process_report_event(job,step_executor=step)
    step.assert_called_once_with(run_id=row["run_id"],step_id="analyze")
    build.assert_not_called();save.assert_not_called()
    assert finish.call_args.kwargs["result"]["snapshot"]==row["snapshot"]
    assert set(finish.call_args.kwargs["manifest"])=={"pdf","xlsx","json"}
    assert all(call.kwargs["lease_token"]==job["lease_token"] for call in store.call_args_list)
    assert all(call.args[0]["snapshot"]==row["snapshot"] for call in export.call_args_list)


@pytest.mark.parametrize("step_state",["started","uncertain"])
def test_uncertain_analysis_publishes_only_saved_facts_for_review(job,step_state):
    row={**report(job),"snapshot":{"metrics":{"bookings":1}}}
    step=Mock(side_effect=TimeoutError("provider result unknown"))
    with patch.object(worker.reports,"get_report",return_value=row),patch.object(worker,"LeaseHeartbeat",Lease),patch.object(
        worker.reports,"get_model_step",return_value={"state":step_state},create=True),patch.object(
        worker.reports,"finish_report",return_value={"status":"partial"}) as finish,patch(
        "app.services.analysis_export_service.export_report",return_value={"content":b"facts"}) as export,patch(
        "app.services.analysis_storage_service.store_export",return_value={"version":job["lease_token"]}):
        assert worker.process_report_event(job,step_executor=step)["status"]=="partial"
    step.assert_called_once_with(run_id=row["run_id"],step_id="analyze")
    result=finish.call_args.kwargs["result"]
    assert result["snapshot"]==row["snapshot"]
    assert result["analysis_status"]=="needs_review" and result["narrative"]=="" and result["sections"]==[]
    assert "billing needs review" in result["limitations"][0]
    assert all(call.args[0]==result for call in export.call_args_list)


@pytest.mark.parametrize("step",[None,{"state":"succeeded","output":{"narrative":"Persisted result"}}])
def test_absent_or_successful_analysis_does_not_fabricate_uncertain_state(job,step):
    row={**report(job),"snapshot":{"metrics":{"bookings":1}}}
    with patch.object(worker.reports,"get_report",return_value=row),patch.object(worker,"LeaseHeartbeat",Lease),patch.object(
        worker.reports,"get_model_step",return_value=step,create=True),patch.object(worker.reports,"finish_report") as finish:
        with pytest.raises(TimeoutError):
            worker.process_report_event(job,step_executor=Mock(side_effect=TimeoutError("Transport failed")))
    finish.assert_not_called()


def test_stale_worker_failure_cannot_close_winners_job(job):
    with patch.object(worker.queue,"claim_queued_automation_events",return_value=[job]) as claim,patch.object(
        worker,"process_report_event",side_effect=worker.LeaseLost()),patch.object(worker.queue,"finish_automation_event") as finish:
        assert worker.run_once()==1
    claim.assert_called_once_with(limit=1,lease_seconds=300,worker_kind="agent_report")
    finish.assert_not_called()


def test_error_goes_through_database_retry_and_uncertainty_fence(job):
    with patch.object(worker.queue,"claim_queued_automation_events",return_value=[job]),patch.object(
        worker,"process_report_event",side_effect=RuntimeError("secret request details")),patch.object(worker.queue,"finish_automation_event") as finish:
        worker.run_once()
    assert finish.call_args.kwargs["lease_token"]==job["lease_token"]
    assert finish.call_args.kwargs["retryable"] is True
    assert finish.call_args.kwargs["error_message"]=="worker_step_failed"


def test_bridge_fails_closed_without_configuration(monkeypatch):
    monkeypatch.delenv("ANALYSIS_LANGFLOW_URL",raising=False)
    with pytest.raises(ValueError):worker.run_langflow_step(run_id=str(uuid4()),step_id="plan")


def test_observation_dispatch_uses_its_own_lease_kind(job):
    observation = {**job, "event_type": "business_observation", "worker_kind": "business_observation"}
    with patch.object(worker.queue,"claim_queued_automation_events",return_value=[observation]) as claim,patch.object(
        worker,"LeaseHeartbeat",Lease),patch("app.services.business_observation_service.process_business_observation") as process,patch.object(
        worker,"process_report_event") as report_process:
        worker.run_once(worker_kind="business_observation")
    claim.assert_called_once_with(limit=1,lease_seconds=300,worker_kind="business_observation")
    process.assert_called_once_with(observation)
    report_process.assert_not_called()


def test_observation_heartbeat_never_renews_a_report_lease(job):
    heartbeat = worker.LeaseHeartbeat({**job, "event_type": "business_observation"})
    heartbeat.stop = Mock()
    heartbeat.stop.wait.side_effect = [False, True]
    with patch.object(worker.queue,"renew_automation_event_lease",return_value=job) as renew:
        heartbeat._run()
    assert renew.call_args.kwargs["worker_kind"] == "business_observation"


def test_langflow_transport_sends_only_persisted_ids(monkeypatch):
    import json
    monkeypatch.setenv("ANALYSIS_LANGFLOW_URL", "http://approved-bridge.internal:7860")
    monkeypatch.setenv("ANALYSIS_LANGFLOW_FLOW_ID", "analysis-model-bridge")
    monkeypatch.setenv("LANGFLOW_API_KEY", "synthetic-test-token-123456789")
    response = Mock()
    response.iter_bytes.return_value = [json.dumps({"outputs":[{"outputs":[{"results":{"message":{"text":'{"status":"ready"}'}}}]}]}).encode()]
    client = Mock()
    client.stream.return_value.__enter__ = Mock(return_value=response)
    client.stream.return_value.__exit__ = Mock(return_value=False)
    run_id = str(uuid4())
    with patch.object(worker.httpx,"Client") as client_type:
        client_type.return_value.__enter__.return_value = client
        assert worker.run_langflow_step(run_id=run_id,step_id="plan") == {"status":"ready"}
    request = client.stream.call_args.kwargs
    assert json.loads(request["json"]["input_value"]) == {"run_id":run_id,"step_id":"plan"}
    assert client_type.call_args.kwargs["follow_redirects"] is False


@pytest.mark.parametrize("url",["http://example.com", "https://user:pass@example.com", "https://example.com?token=x"])
def test_bridge_rejects_insecure_or_credential_bearing_url(monkeypatch,url):
    monkeypatch.setenv("ANALYSIS_LANGFLOW_URL",url)
    with patch.object(worker.httpx,"Client") as transport,pytest.raises(ValueError):
        worker.run_langflow_step(run_id=str(uuid4()),step_id="plan")
    transport.assert_not_called()


def test_entrypoint_never_boots_wsgi_or_flask_app():
    from pathlib import Path
    import ast
    tree=ast.parse((Path(__file__).parents[1]/"analysis_worker.py").read_text())
    calls=[node.func.id for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)]
    assert "create_app" not in calls
    imports=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    assert "wsgi" not in imports


def test_deployment_exports_keep_private_network_and_reviewed_component():
    import ast
    import importlib.util
    import json
    from pathlib import Path
    import tomllib
    root = Path(__file__).parents[1]
    deploy = root / "deploy/agent-automation"
    for name in ("worker", "langflow", "n8n"):
        config = tomllib.loads((deploy / (name + ".fly.toml")).read_text())
        assert config["primary_region"] == "sin"
        assert "services" not in config
        assert config["restart"] == [{"policy":"always"}]
        if name != "n8n":
            assert "http_service" not in config  # worker and Langflow stay private
    # Owner decision 2026-09-24: the n8n editor is public, but only over HTTPS,
    # never auto-stopped, and without n8n's public API.
    n8n = tomllib.loads((deploy / "n8n.fly.toml").read_text())
    assert n8n["http_service"]["force_https"] is True
    assert n8n["http_service"]["auto_stop_machines"] == "off"
    assert n8n["http_service"]["min_machines_running"] == 1
    assert n8n["env"]["N8N_PUBLIC_API_DISABLED"] == "true"
    flow_path = deploy / "langflow/analysis-model-bridge.langflow.json"
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
    nodes = flow["data"]["nodes"]
    assert [node["data"]["type"] for node in nodes] == ["ChatInput","AnalysisModelStep","ChatOutput"]
    for index in (0,2):
        assert nodes[index]["data"]["node"]["template"]["should_store_message"]["value"] is False
    bridge_code = (deploy / "langflow/components/agent_analysis/model_step.py").read_text(encoding="utf-8")
    assert nodes[1]["data"]["node"]["template"]["code"]["value"] == bridge_code
    ast.parse(bridge_code)
    builder_spec = importlib.util.spec_from_file_location("analysis_flow_builder",deploy / "langflow/build_flow.py")
    builder = importlib.util.module_from_spec(builder_spec)
    builder_spec.loader.exec_module(builder)
    assert builder.build_flow() == flow
    for filename, endpoint in (("n8n-schedule-tick.json","schedules/tick"),("n8n-tuition-reminders.json","tuition-reminders/tick")):
        workflow = json.loads((deploy / filename).read_text(encoding="utf-8"))
        assert workflow["active"] is False
        assert [node["type"] for node in workflow["nodes"]] == ["n8n-nodes-base.scheduleTrigger","n8n-nodes-base.httpRequest"]
        assert endpoint in workflow["nodes"][1]["parameters"]["url"]


def _deny_automation(_company_id, key):
    if key == "automation_workflows":
        raise BillingLimitError("Not on this plan", code="feature_not_available")
    return True


def test_scheduled_report_needs_automation_workflows_before_any_model(job, access_guards):
    row = {**report(job), "client_message_id": "schedule:00000000-0000-4000-8000-000000000001:weekly:2026-09-14"}
    access_guards[1].side_effect = _deny_automation
    with patch.object(worker.reports, "get_report", return_value=row), patch.object(worker, "LeaseHeartbeat", Lease), \
            patch.object(worker.reports, "finish_report") as finish:
        step = Mock()
        with pytest.raises(BillingLimitError):
            worker.process_report_event(job, step_executor=step)
    step.assert_not_called()
    finish.assert_not_called()


def test_scheduled_model_step_rechecks_automation_workflows(job, access_guards):
    row = {**report(job), "client_message_id": "schedule:00000000-0000-4000-8000-000000000001:weekly:2026-09-14"}
    access_guards[1].side_effect = _deny_automation
    with patch.object(worker.reports, "get_report_by_run_id", return_value=row), patch.object(
            worker.queue, "get_automation_event_by_id", return_value=job), patch(
            "app.services.analysis_report_service.plan_report_request") as model:
        with pytest.raises(BillingLimitError):
            worker.execute_model_step(run_id=row["run_id"], step_id="plan")
    model.assert_not_called()


def test_manual_report_is_not_gated_on_automation_workflows(job, access_guards):
    row = {**report(job), "client_message_id": "browser-request-1"}
    with patch.object(worker.reports, "get_report_by_run_id", return_value=row), patch.object(
            worker.queue, "get_automation_event_by_id", return_value=job), patch(
            "app.services.analysis_report_service.plan_report_request", return_value={"status": "ready"}):
        worker.execute_model_step(run_id=row["run_id"], step_id="plan")
    assert {call.args[1] for call in access_guards[1].call_args_list} == {"ai_generated_reports"}


def test_plan_denied_worker_failure_is_not_retried(job, access_guards):
    access_guards[1].side_effect = _deny_automation
    row = {**report(job), "client_message_id": "schedule:x:weekly:2026-09-14"}
    with patch.object(worker.queue, "claim_queued_automation_events", return_value=[job]), patch.object(
            worker.reports, "get_report", return_value=row), patch.object(worker, "LeaseHeartbeat", Lease), patch.object(
            worker.queue, "finish_automation_event") as finish:
        worker.run_once(step_executor=Mock())
    assert finish.call_args.kwargs["retryable"] is False
    assert finish.call_args.kwargs["status"] == "failed"
