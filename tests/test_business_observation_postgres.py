"""Real PostgreSQL checks in a fresh local-only cluster; no project credentials."""
import json
from pathlib import Path

import pytest

from tests.test_analysis_postgres import pg, literal, race


@pytest.fixture(scope="module", autouse=True)
def observation_schema(pg):
    migration = (Path(__file__).parents[1] / "data" / "065_business_observations.sql").read_text(encoding="utf-8")
    pg(migration)
    pg(migration)  # Additive migration must be safely repeatable.
    pg("GRANT SELECT ON chatbots,conversations TO service_role; GRANT INSERT ON messages TO service_role;")


def claims(pg):
    text = pg("SELECT row_to_json(e) FROM claim_automation_events_v1('business_observation',50,300) e;", role="service_role").stdout.strip()
    return [json.loads(line) for line in text.splitlines()] if text else []


def insert(pg, message_id, conversation_id=11, *, sender="customer", ai=False, message_type="text", text="Please book a table"):
    escaped = text.replace("'", "''")
    pg(f"INSERT INTO messages(id,conversation_id,message_text,sender_type,ai_generated,message_type) "
       f"VALUES({message_id},{conversation_id},'{escaped}','{sender}',{str(ai).lower()},'{message_type}');", role="service_role")


def queued(pg, message_id, conversation_id=11):
    pg("UPDATE chatbots SET analysis_recording_enabled=true WHERE id=7;")
    insert(pg, message_id, conversation_id)
    return next(row for row in claims(pg) if row["payload"]["message_id"] == message_id)


def apply(pg, event, operation, output=None, *, check=True, token=None):
    return pg(f"SELECT analysis_apply_business_observation({event['id']},'{token or event['lease_token']}',"
              f"'{operation}',{literal(output or {})});", role="service_role", check=check)


def result(pg, event, operation, output=None):
    return json.loads(apply(pg, event, operation, output).stdout)


OUTPUT = {"action_type": "booking", "status": "requested", "industry_id": "restaurant", "context_truncated": False}


def test_default_off_then_only_real_customer_text_is_enqueued_with_derived_scope(pg):
    assert pg("SELECT bool_or(analysis_recording_enabled) FROM chatbots").stdout.strip() == "f"
    insert(pg, 100)
    assert pg("SELECT count(*) FROM automation_events").stdout.strip() == "0"
    pg("UPDATE chatbots SET analysis_recording_enabled=true WHERE id=7;")
    insert(pg, 101)
    insert(pg, 102, sender="bot")
    insert(pg, 103, sender="human")
    insert(pg, 104, ai=True)
    insert(pg, 105, message_type="image")
    insert(pg, 106, text="   ")
    insert(pg, 107, conversation_id=12)  # Other company's Bot has not opted in.
    rows = claims(pg)
    assert len(rows) == 1
    event = rows[0]
    assert event["company_id"] == 10 and event["chatbot_id"] == 7
    assert event["payload"] == {"message_id": 101}
    assert event["worker_kind"] == "business_observation"
    assert result(pg, event, "inspect")["message"]["text"] == "Please book a table"
    result(pg, event, "skip")


def test_one_concurrent_start_and_atomic_evidence_only_observation(pg):
    event = queued(pg, 110)
    starts = race(lambda: result(pg, event, "start"))
    assert sum(row["started"] for row in starts) == 1
    assert result(pg, event, "inspect")["model_started"] is True
    assert "40001" in apply(pg, event, "skip", check=False).stderr
    settled = result(pg, event, "finish", OUTPUT)
    assert settled["status"] == "completed"
    replay = result(pg, event, "finish", OUTPUT)
    assert replay == settled
    record = json.loads(pg("SELECT row_to_json(e) FROM business_events e WHERE event_key='customer-message:110'").stdout)
    assert record["status"] == "requested" and record["source"] == "observation"
    assert record["record_id"] is None and record["evidence_message_ids"] == [110]
    assert record["conversation_id"] == 11 and record["company_id"] == 10 and record["chatbot_id"] == 7
    assert "Please book" not in json.dumps(record)
    assert pg("SELECT count(*) FROM business_events WHERE event_key='customer-message:110'").stdout.strip() == "1"
    assert pg(f"SELECT external_effect_started FROM automation_events WHERE id={event['id']}").stdout.strip() == "f"


def test_cannot_record_completed_or_forged_evidence_or_unstarted_outcome(pg):
    event = queued(pg, 120)
    assert "40001" in apply(pg, event, "finish", OUTPUT, check=False).stderr
    assert "40001" in apply(pg, event, "uncertain", check=False).stderr
    result(pg, event, "start")
    for output in (OUTPUT | {"status": "confirmed"}, OUTPUT | {"status": "completed"},
                   OUTPUT | {"evidence_message_ids": [22]}, OUTPUT | {"company_id": 20},
                   OUTPUT | {"industry_id": "private details"}, OUTPUT | {"context_truncated": "false"}):
        assert "22023" in apply(pg, event, "finish", output, check=False).stderr
    result(pg, event, "finish", OUTPUT | {"action_type": "none", "status": "none"})
    assert pg("SELECT count(*) FROM business_events WHERE event_key='customer-message:120'").stdout.strip() == "0"


def test_expired_provider_attempt_cannot_be_retried_or_finished(pg):
    event = queued(pg, 130)
    result(pg, event, "start")
    pg(f"UPDATE automation_events SET lease_expires_at=now()-interval '1 second' WHERE id={event['id']};")
    assert "40001" in apply(pg, event, "finish", OUTPUT, check=False).stderr
    assert not any(row["id"] == event["id"] for row in claims(pg))
    assert pg(f"SELECT status FROM automation_events WHERE id={event['id']}").stdout.strip() == "needs_review"
    assert result(pg, event, "inspect")["status"] == "needs_review"
    assert pg("SELECT count(*) FROM business_events WHERE event_key='customer-message:130'").stdout.strip() == "0"


@pytest.mark.parametrize("operation,message_id,started", [("inspect", 140, False), ("start", 141, False), ("finish", 142, True)])
def test_disable_prevents_recording_at_each_boundary(pg, operation, message_id, started):
    event = queued(pg, message_id)
    if started:
        result(pg, event, "start")
    pg("UPDATE chatbots SET analysis_recording_enabled=false WHERE id=7;")
    outcome = result(pg, event, operation, OUTPUT if operation == "finish" else None)
    assert outcome["status"] == "completed" and outcome["result"]["reason"] == "recording_disabled"
    assert pg(f"SELECT count(*) FROM business_events WHERE event_key='customer-message:{message_id}'").stdout.strip() == "0"


def test_disable_cannot_make_unknown_provider_outcome_retryable(pg):
    event = queued(pg, 143)
    result(pg, event, "start")
    pg("UPDATE chatbots SET analysis_recording_enabled=false WHERE id=7;")
    assert result(pg, event, "inspect")["status"] == "needs_review"
    assert pg(f"SELECT external_effect_started FROM automation_events WHERE id={event['id']}").stdout.strip() == "t"


def test_lease_scope_and_public_permissions_are_fail_closed(pg):
    event = queued(pg, 150)
    assert "40001" in apply(pg, event, "inspect", token="00000000-0000-4000-8000-000000000099", check=False).stderr
    pg(f"UPDATE automation_events SET payload='{{\"message_id\":22}}' WHERE id={event['id']};")
    assert "42501" in apply(pg, event, "inspect", check=False).stderr
    pg(f"UPDATE automation_events SET payload='{{\"message_id\":150}}' WHERE id={event['id']};")
    pg("UPDATE messages SET sender_type=NULL WHERE id=150;")
    assert "42501" in apply(pg, event, "inspect", check=False).stderr
    for role in ("anon", "authenticated"):
        sql = f"SELECT analysis_apply_business_observation({event['id']},'{event['lease_token']}','start','{{}}');"
        assert "42501" in pg(sql, role=role, check=False).stderr
