"""One leased report at a time; Flask remains the only model/business writer."""
from datetime import datetime, timezone
import json
import os
import re
from threading import Event, Thread
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.database import analysis_repository as reports
from app.database import automation_event_repository as queue
from app.services.analysis_request_service import is_scheduled_report
from app.services.billing_guard import BillingLimitError, can_use_plan_feature
from app.services.company_status_service import CompanyOperationalStatusError, ensure_company_operational


LEASE_SECONDS = 300


class LeaseLost(RuntimeError):
    pass


def _authorize_report(report):
    """Re-check entitlement at execution time; the plan may change after enqueue.

    Every report needs ai_generated_reports. A scheduled report is also an
    automatic working flow, so it needs automation_workflows (Pro-only); a
    manual, on-demand report does not.
    """
    company_id = report["company_id"]
    ensure_company_operational(company_id)
    can_use_plan_feature(company_id, "ai_generated_reports")
    if is_scheduled_report(report):
        can_use_plan_feature(company_id, "automation_workflows")


def _scope(report, event):
    if (event.get("event_type") != "agent_report"
            or report.get("automation_event_id") != event.get("id")
            or report.get("company_id") != event.get("company_id")
            or report.get("chatbot_id") != event.get("chatbot_id")):
        raise LeaseLost("Report scope changed")
    if event.get("status") != "running" or not event.get("lease_token"):
        raise LeaseLost("Report lease is not active")
    expiry = datetime.fromisoformat(str(event.get("lease_expires_at", "")).replace("Z", "+00:00"))
    if expiry <= datetime.now(timezone.utc):
        raise LeaseLost("Report lease expired")
    return {"company_id": report["company_id"], "chatbot_id": report["chatbot_id"],
            "report_id": report["id"], "event_id": event["id"], "lease_token": event["lease_token"]}


def execute_model_step(*, run_id, step_id):
    """Internal authenticated endpoint only: IDs select persisted scope and input.

    No caller-supplied prompts, company, model, budget or arbitrary tool names.
    The durable RPC authorizes the actor again before either paid model step.
    """
    from app.services import analysis_report_service as engine

    run_id = str(UUID(str(run_id)))
    if step_id not in {"plan", "analyze"}:
        raise ValueError("Invalid model step")
    report = reports.get_report_by_run_id(run_id)
    if not report:
        raise reports.AnalysisScopeDenied("Report not found")
    event = queue.get_automation_event_by_id(report["automation_event_id"])
    if not event:
        raise LeaseLost("Report job not found")
    scope = _scope(report, event)
    _authorize_report(report)
    callbacks = {
        "begin_model_step": lambda **kwargs: reports.begin_model_step(**scope, **kwargs),
        "finish_model_step": lambda **kwargs: reports.finish_model_step(**scope, **kwargs),
    }
    if step_id == "plan":
        return engine.plan_report_request(company_id=report["company_id"],
            chatbot_id=report["chatbot_id"], command=report["request_text"],
            request_spec=report.get("request_spec"), **callbacks)
    if not report.get("snapshot"):
        raise reports.AnalysisConflict("Snapshot must be saved before analysis")
    return engine.generate_report(report["snapshot"], command=report["request_text"], **callbacks)


def run_langflow_step(*, run_id, step_id):
    """Run a pinned bridge flow, which posts only these IDs back to Flask."""
    run_id = str(UUID(str(run_id)))
    if step_id not in {"plan", "analyze"}:
        raise ValueError("Invalid model step")
    base = os.getenv("ANALYSIS_LANGFLOW_URL", "").strip().rstrip("/")
    parsed = urlparse(base)
    private = parsed.scheme == "http" and bool(parsed.hostname) and parsed.hostname.endswith(".internal")
    if not (parsed.scheme == "https" or private) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Analysis Langflow requires HTTPS or Fly private networking")
    flow = os.getenv("ANALYSIS_LANGFLOW_FLOW_ID", "").strip()
    token = os.getenv("LANGFLOW_API_KEY", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", flow) or len(token) < 16:
        raise ValueError("Analysis Langflow bridge is not configured")
    payload = {"input_value": json.dumps({"run_id": run_id, "step_id": step_id}),
               "input_type": "chat", "output_type": "chat", "session_id": run_id}
    with httpx.Client(timeout=120, follow_redirects=False) as client:
        with client.stream("POST", base+"/api/v1/run/"+flow,
                           headers={"x-api-key": token}, json=payload) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024:
                    raise RuntimeError("Analysis bridge response too large")
    data = json.loads(body)
    # ChatOutput's documented v1 run envelope. Reject other shapes, never guess.
    try:
        text = data["outputs"][0]["outputs"][0]["results"]["message"]["text"]
        result = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("Analysis bridge returned no structured result") from None
    if not isinstance(result, dict):
        raise RuntimeError("Analysis bridge returned an invalid result")
    return result


class LeaseHeartbeat:
    def __init__(self, event):
        self.event = event
        self.worker_kind = event["event_type"]
        self.stop = Event()
        self.lost = Event()
        self.thread = Thread(target=self._run, name="analysis-lease", daemon=True)

    def _run(self):
        while not self.stop.wait(30):
            try:
                renewed = queue.renew_automation_event_lease(event_id=self.event["id"],
                    lease_token=self.event["lease_token"], worker_kind=self.worker_kind, lease_seconds=LEASE_SECONDS)
                if not renewed:
                    self.lost.set()
                    return
            except Exception:
                self.lost.set()
                return

    def check(self):
        if self.lost.is_set():
            raise LeaseLost("Worker no longer owns report")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join(timeout=1)


def process_report_event(event, *, step_executor=run_langflow_step):
    from app.services import analysis_report_service as engine
    from app.services.analysis_export_service import export_report
    from app.services.analysis_storage_service import store_export

    report_id = (event.get("payload") or {}).get("report_id")
    report = reports.get_report(event["company_id"], event["chatbot_id"], report_id)
    if not report:
        raise reports.AnalysisScopeDenied("Report not found")
    scope = _scope(report, event)
    _authorize_report(report)
    with LeaseHeartbeat(event) as lease:
        if report.get("snapshot"):
            snapshot = report["snapshot"]
        else:
            plan = step_executor(run_id=report["run_id"], step_id="plan")
            lease.check()
            if plan.get("status") == "needs_input":
                return reports.finish_report(**scope, status="needs_input", result=plan)
            if plan.get("status") != "ready" or not isinstance(plan.get("request_spec"), dict):
                raise ValueError("Invalid report plan")
            snapshot = engine.build_report_snapshot(company_id=report["company_id"],
                chatbot_id=report["chatbot_id"], request_spec=plan["request_spec"])
            lease.check()
            reports.save_snapshot_fenced(**scope, snapshot=snapshot)
        try:
            result = step_executor(run_id=report["run_id"], step_id="analyze")
        except Exception:
            # Numeric facts were already frozen before model dispatch. Only the
            # durable started/uncertain state permits this reviewed fallback.
            step = reports.get_model_step(company_id=report["company_id"], chatbot_id=report["chatbot_id"],
                report_id=report["id"], step_id="analyze")
            if not step or step.get("state") not in {"started", "uncertain"}:
                raise
            result = {"status": "partial", "snapshot": snapshot, "narrative": "", "sections": [],
                "analysis_status": "needs_review",
                "limitations": ["AI analysis could not be confirmed. Facts are available; billing needs review."]}
        lease.check()
        _authorize_report(report)
        if result.get("status") not in {"complete", "partial"}:
            raise ValueError("Invalid analysis result")
        # The model/bridge cannot replace numeric facts already frozen in the DB.
        result = {**result, "snapshot": snapshot}
        export_input = {**result, "snapshot": snapshot}
        manifest = {}
        for format in ("pdf", "xlsx", "json"):
            lease.check()
            artifact = export_report(export_input, format)
            manifest[format] = store_export(company_id=report["company_id"], chatbot_id=report["chatbot_id"],
                report_id=report["id"], lease_token=event["lease_token"], format=format, content=artifact["content"])
        lease.check()
        _authorize_report(report)
        # One transaction publishes files + result and settles the owned queue lease.
        return reports.finish_report(**scope, status=result["status"], result=result, manifest=manifest)


def run_once(*, step_executor=run_langflow_step, worker_kind="agent_report"):
    if worker_kind not in {"agent_report", "business_observation", "tuition_reminder"}:
        raise ValueError("Invalid analysis worker kind")
    events = queue.claim_queued_automation_events(limit=1, lease_seconds=LEASE_SECONDS, worker_kind=worker_kind)
    for event in events:
        try:
            if worker_kind == "agent_report":
                process_report_event(event, step_executor=step_executor)
            elif worker_kind == "business_observation":
                from app.services.business_observation_service import process_business_observation
                with LeaseHeartbeat(event) as lease:
                    lease.check()
                    process_business_observation(event)
            else:
                from app.services.tuition_reminder_service import process_tuition_reminder
                with LeaseHeartbeat(event) as lease:
                    lease.check()
                    process_tuition_reminder(event)
        except (LeaseLost, reports.AnalysisConflict):
            # A stale worker must never change the winner's result, even on failure.
            continue
        except Exception as exc:
            # SQL inspects external_effect_started under the same lock: uncertain
            # provider outcomes become needs_review, safe failures get bounded backoff.
            code = getattr(exc, "code", "worker_step_failed")
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                code = "worker_step_failed"
            queue.finish_automation_event(event_id=event["id"], lease_token=event["lease_token"],
                worker_kind=worker_kind, status="failed", error_message=code,
                retryable=not isinstance(exc, (ValueError, reports.AnalysisScopeDenied,
                    BillingLimitError, CompanyOperationalStatusError)))
    return len(events)
