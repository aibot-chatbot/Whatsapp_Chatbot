"""Opt-in PostgreSQL integration, always a new local throwaway cluster.

No connection string or project credentials are accepted. The cluster binds
only loopback and is stopped even when a test fails.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from threading import Barrier
from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def pg():
    if os.getenv("RUN_LOCAL_POSTGRES_TESTS") != "1":
        pytest.skip("isolated PostgreSQL drill is opt-in")
    binaries = Path(os.environ.get("POSTGRES_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
    if not (binaries / "postgres.exe").is_file():
        pytest.skip("PostgreSQL binaries unavailable")
    scratch = Path(tempfile.mkdtemp(prefix="analysis-sql-qa-"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    def run(binary, args, **kwargs):
        # initdb and pg_ctl both spawn descendants on Windows. File handles
        # avoid communicate() waiting forever on inherited pipe handles.
        prefix = scratch / (binary + "-" + uuid4().hex)
        out_path, err_path, in_path = (Path(str(prefix) + suffix) for suffix in (".out", ".err", ".in"))
        in_path.write_text(kwargs.pop("input", ""), encoding="utf-8")
        with out_path.open("w", encoding="utf-8") as output, err_path.open("w", encoding="utf-8") as error, in_path.open("r", encoding="utf-8") as stdin:
            result = subprocess.run([str(binaries / binary), *args], stdout=output, stderr=error,
                stdin=stdin, timeout=60, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs)
        result.stdout = out_path.read_text(encoding="utf-8")
        result.stderr = err_path.read_text(encoding="utf-8")
        return result

    init = run("initdb.exe", ["-D", str(scratch / "cluster"), "-U", "postgres", "-A", "trust", "--no-locale", "-E", "UTF8"])
    assert init.returncode == 0, init.stderr
    started = run("pg_ctl.exe", ["-D", str(scratch / "cluster"), "-l", str(scratch / "server.log"),
        "-o", f"-h 127.0.0.1 -p {port} -c shared_buffers=16MB -c max_connections=12", "-w", "start"])
    assert started.returncode == 0, started.stderr

    def sql(statement, *, role=None, check=True):
        if role:
            assert role in {"service_role", "anon", "authenticated"}
            statement = f"SET ROLE {role};\n" + statement
        result = run("psql.exe", ["-XAtq", "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose",
            "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres", "-f", "-"], input=statement)
        if check:
            assert result.returncode == 0, result.stderr
        return result

    try:
        sql("""
        CREATE ROLE anon;
        CREATE ROLE authenticated;
        CREATE ROLE service_role BYPASSRLS;
        CREATE TABLE companies(id bigint PRIMARY KEY);
        CREATE TABLE users(id bigint PRIMARY KEY,company_id bigint,status text,role text);
        CREATE TABLE chatbots(id bigint PRIMARY KEY,company_id bigint,deleted_at timestamptz,status text,
          industry_template_published jsonb DEFAULT '{}');
        CREATE TABLE conversations(id bigint PRIMARY KEY,chatbot_id bigint,source_channel text DEFAULT 'web',
          platform_user_id text DEFAULT 'server-generated-session',customer_phone text,source_channel_id bigint,
          source_provider_id text,conversation_status text DEFAULT 'open');
        CREATE TABLE messages(id bigint PRIMARY KEY,conversation_id bigint,message_text text,
          message_type text DEFAULT 'text',ai_generated boolean DEFAULT false,sender_type text DEFAULT 'customer');
        INSERT INTO companies VALUES(10),(20);
        INSERT INTO users VALUES(3,10,'active','owner'),(4,20,'active','admin'),(5,10,'active','staff');
        INSERT INTO chatbots(id,company_id,deleted_at,status) VALUES(7,10,NULL,'active'),(8,20,NULL,'active'),(9,10,NULL,'active');
        INSERT INTO conversations(id,chatbot_id) VALUES(11,7),(12,8),(13,9);
        INSERT INTO messages(id,conversation_id) VALUES(21,11),(22,12),(23,13);
        """)
        root = Path(__file__).parents[1]
        for migration in ("049_automation_events.sql", "063_agent_analysis.sql", "064_automation_worker_leases.sql"):
            sql((root / "data" / migration).read_text(encoding="utf-8"))
        yield sql
    finally:
        stopped = run("pg_ctl.exe", ["-D", str(scratch / "cluster"), "-m", "fast", "-w", "stop"])
        assert stopped.returncode == 0, stopped.stderr


def literal(value):
    return "'" + json.dumps(value).replace("'", "''") + "'::jsonb"


def request(pg, key):
    return json.loads(pg(f"SELECT analysis_create_report_request(10,7,3,'{key}','Report','{{}}');", role="service_role").stdout)


def claim(pg):
    rows = pg("SELECT row_to_json(e) FROM claim_automation_events_v1('agent_report',1,300) e;", role="service_role").stdout.strip()
    return json.loads(rows) if rows else None


def apply(pg, report, event, operation, payload, *, check=True, token=None):
    return pg(f"SELECT analysis_apply_run(10,7,'{report['id']}',{event['id']},"
        f"'{token or event['lease_token']}','{operation}',{literal(payload)});", role="service_role", check=check)


def race(call):
    barrier = Barrier(2)
    def once(_):
        barrier.wait(timeout=5)
        return call()
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(once, range(2)))


def test_atomic_creation_provider_fencing_snapshot_and_publication(pg):
    reports = race(lambda: request(pg, "same-request"))
    assert reports[0]["id"] == reports[1]["id"]
    assert pg("SELECT count(*) FROM analysis_reports").stdout.strip() == "1"
    assert pg("SELECT count(*) FROM automation_events").stdout.strip() == "1"
    events = [event for event in race(lambda: claim(pg)) if event]
    assert len(events) == 1
    report, event = reports[0], events[0]
    stale = apply(pg, report, event, "snapshot", {}, token="00000000-0000-4000-8000-000000000001", check=False)
    assert "40001" in stale.stderr
    starts = race(lambda: json.loads(apply(pg, report, event, "begin_step", {"step_id": "plan"}).stdout))
    assert sum(row["started"] for row in starts) == 1
    assert pg("SELECT external_effect_started FROM automation_events").stdout.strip() == "t"
    apply(pg, report, event, "finish_step", {"step_id": "plan", "state": "succeeded", "output": {"kind": "business"}})
    assert pg("SELECT external_effect_started FROM automation_events").stdout.strip() == "f"
    snapshot = {"scope": {"company_id": 10, "chatbot_id": 7}, "snapshot_sha256": "b" * 64}
    apply(pg, report, event, "snapshot", snapshot)
    assert "22023" in apply(pg, report, event, "snapshot", {"changed": True}, check=False).stderr
    apply(pg, report, event, "begin_step", {"step_id": "analyze"})
    apply(pg, report, event, "finish_step", {"step_id": "analyze", "state": "succeeded", "output": {"snapshot_sha256": "b" * 64, "narrative": {"text": "Bounded"}}})
    manifest = {"pdf": {"format": "pdf", "version": event["lease_token"], "sha256": "a" * 64, "size": 20}}
    bad_manifest = {"pdf": {**manifest["pdf"], "url": "https://attacker.invalid"}}
    result = {"snapshot": snapshot, "narrative": {"text": "Bounded"}}
    assert "22023" in apply(pg, report, event, "finish", {"status": "complete", "result": result, "manifest": bad_manifest}, check=False).stderr
    assert "22023" in apply(pg, report, event, "finish", {"status": "complete", "result": {**result, "narrative": {"text": "Unverified"}}, "manifest": manifest}, check=False).stderr
    apply(pg, report, event, "finish", {"status": "complete", "result": result, "manifest": manifest})
    assert pg("SELECT r.status||':'||e.status FROM analysis_reports r JOIN automation_events e ON e.id=r.automation_event_id").stdout.strip() == "complete:completed"
    assert "42501" in pg("UPDATE analysis_reports SET snapshot='{}';", role="service_role", check=False).stderr


def test_access_and_actorless_business_scope(pg):
    for company, bot, actor in ((20, 7, 4), (10, 7, 4), (10, 7, 5)):
        result = pg(f"SELECT analysis_create_report_request({company},{bot},{actor},'denied','Report','{{}}');", role="service_role", check=False)
        assert "42501" in result.stderr
    sql = "SELECT analysis_record_business_event(10,7,{conversation},NULL,'e1','booking','intent','observation',NULL,ARRAY[{message}]::bigint[],'{{}}');"
    for conversation, message in ((12, 22), (13, 23), (11, 22)):
        assert "42501" in pg(sql.format(conversation=conversation, message=message), role="service_role", check=False).stderr
    first = json.loads(pg(sql.format(conversation=11, message=21), role="service_role").stdout)
    again = json.loads(pg(sql.format(conversation=11, message=21), role="service_role").stdout)
    assert first["id"] == again["id"]
    assert "23514" in pg("SELECT analysis_record_business_event(10,7,11,NULL,'e2','booking','confirmed','observation',NULL,'{}','{}');", role="service_role", check=False).stderr
    for role in ("anon", "authenticated"):
        assert "42501" in pg("SELECT analysis_create_report_request(10,7,3,'private','Report','{}');", role=role, check=False).stderr
        assert "42501" in pg("SELECT * FROM analysis_reports;", role=role, check=False).stderr


def test_expired_provider_call_becomes_review_without_second_call(pg):
    report = request(pg, "uncertain")
    event = claim(pg)
    apply(pg, report, event, "begin_step", {"step_id": "plan"})
    pg(f"UPDATE automation_events SET lease_expires_at=now()-interval '1 second' WHERE id={event['id']};")
    assert claim(pg) is None
    assert pg(f"SELECT status FROM analysis_reports WHERE id='{report['id']}'").stdout.strip() == "needs_review"
    assert "40001" in apply(pg, report, event, "finish_step", {"step_id": "plan", "state": "succeeded"}, check=False).stderr
    assert pg(f"SELECT count(*) FROM analysis_model_steps WHERE report_id='{report['id']}'").stdout.strip() == "1"


def test_schedule_due_period_atomic_dedupe(pg):
    schedule = json.loads(pg("SELECT analysis_upsert_schedule(10,7,3,'weekly','Asia/Kuala_Lumpur',true,now()-interval '1 day');", role="service_role").stdout)
    results = race(lambda: json.loads(pg(f"SELECT analysis_enqueue_schedule(10,7,'{schedule['id']}','2026-W39','{{}}',now()+interval '7 days');", role="service_role").stdout))
    assert sum(row["enqueued"] for row in results) == 1
    assert pg("SELECT count(*) FROM analysis_reports WHERE client_message_id LIKE 'schedule:%'").stdout.strip() == "1"


def test_pending_cap_is_company_scoped_and_idempotent(pg):
    pg("TRUNCATE analysis_reports, automation_events CASCADE;")
    first = request(pg, "cap-first")
    for index in range(9):
        request(pg, f"cap-{index}")
    assert request(pg, "cap-first")["id"] == first["id"]
    blocked = pg("SELECT analysis_create_report_request(10,9,3,'overflow','Report','{}');", role="service_role", check=False)
    assert "54000" in blocked.stderr
    assert pg("SELECT count(*) FROM analysis_reports WHERE company_id=10").stdout.strip() == "10"


def test_uncertain_analysis_publishes_only_explicit_facts_and_never_requeues(pg):
    pg("TRUNCATE analysis_reports, automation_events CASCADE;")
    report = request(pg, "facts-only")
    event = claim(pg)
    snapshot = {"scope": {"company_id": 10, "chatbot_id": 7}, "snapshot_sha256": "b" * 64}
    apply(pg, report, event, "snapshot", snapshot)
    apply(pg, report, event, "begin_step", {"step_id": "analyze"})
    result = {"snapshot": snapshot, "analysis_status": "needs_review", "narrative": "", "sections": []}
    for missing in ("analysis_status", "narrative", "sections"):
        incomplete = {key: value for key, value in result.items() if key != missing}
        assert "22023" in apply(pg, report, event, "finish", {"status": "partial", "result": incomplete}, check=False).stderr
    assert "22023" in apply(pg, report, event, "finish", {"status": "partial", "result": {**result, "narrative": "Unverified"}}, check=False).stderr
    apply(pg, report, event, "finish", {"status": "partial", "result": result})
    assert pg("SELECT r.status||':'||e.status||':'||e.external_effect_started FROM analysis_reports r JOIN automation_events e ON e.id=r.automation_event_id").stdout.strip() == "partial:needs_review:true"
    assert claim(pg) is None
