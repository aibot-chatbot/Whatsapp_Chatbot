"""Real PostgreSQL proof; fixture can only create its own empty local cluster."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from tests.test_analysis_postgres import pg, literal, race  # noqa: F401


@pytest.fixture(scope="module")
def tuition(pg):
    pg("""UPDATE chatbots SET industry_template_published='{"template_id":"tuition_center","confirmed_at":"2026-09-22"}' WHERE id=7;
      INSERT INTO conversations(id,chatbot_id,platform_user_id) VALUES(14,7,'other-session'),(15,7,'third-session');
      CREATE TABLE agent_actions(id bigint GENERATED ALWAYS AS IDENTITY,chatbot_id bigint,conversation_id bigint,status text,intent text);
      CREATE TABLE conversation_handoff_controls(conversation_id bigint PRIMARY KEY,company_id bigint,chatbot_id bigint,handling_mode text);
    """)
    pg((Path(__file__).parents[1] / "data/066_tuition_trials.sql").read_text(encoding="utf-8"))
    return pg


def catalog(pg, operation, data, *, actor=3, check=True):
    result = pg(f"SELECT tuition_catalog_write(10,7,{actor},'{operation}',{literal(data)});", role="service_role", check=check)
    return json.loads(result.stdout) if check else result


def session(pg, name, *, capacity=1, enrolled=0, trials=1):
    course = catalog(pg, "course", {"name": name})
    cls = catalog(pg, "class", {"course_id": course["id"], "name": name})
    start = datetime.now(timezone.utc) + timedelta(days=3)
    return catalog(pg, "session", {"class_id": cls["id"], "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(), "total_capacity": capacity,
        "enrolled_seats": enrolled, "trial_limit": trials})


def participant(pg, conversation, key):
    return json.loads(pg(f"SELECT tuition_create_participant(10,7,{conversation},NULL,'{key}','Same name');", role="service_role").stdout)


def prepare(pg, conversation, person, slot, *, booking=None, check=True):
    booking_arg = f"'{booking['id']}'" if booking else "NULL"
    result = pg(f"SELECT tuition_prepare_trial(10,7,{conversation},NULL,'{person['id']}','{slot['id']}',{booking_arg},true,NULL);", role="service_role", check=check)
    return json.loads(result.stdout) if check else result


def confirm(pg, conversation, prepared, *, check=True):
    result = pg(f"SELECT tuition_confirm_trial(10,7,{conversation},NULL,'{prepared['confirmation_token']}');", role="service_role", check=check)
    return json.loads(result.stdout) if check else result


def test_last_place_concurrency_and_confirmation_idempotence(tuition):
    pg = tuition
    slot = session(pg, "One place", capacity=4, enrolled=3, trials=2)
    first, second = participant(pg, 11, "first"), participant(pg, 14, "second")
    assert first["id"] != second["id"]  # same label never merges customers
    prepared = [prepare(pg, 11, first, slot), prepare(pg, 14, second, slot)]
    assert all(row["reserved"] is False and row["reminder_supported"] is False for row in prepared)
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    def reserve(index):
        barrier.wait(timeout=5)
        return confirm(pg, (11, 14)[index], prepared[index], check=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sum(row.returncode == 0 for row in results) == 1
    winner = next(index for index, row in enumerate(results) if row.returncode == 0)
    assert "23514" in results[1-winner].stderr
    booking = json.loads(results[winner].stdout)["booking"]
    again = confirm(pg, (11, 14)[winner], prepared[winner])["booking"]
    assert booking["id"] == again["id"]
    assert booking["reminder_enabled"] is False and booking["reminder_unavailable_reason"] == "channel_unsupported"
    assert pg(f"SELECT count(*) FROM business_events WHERE record_id='{booking['id']}' AND status='confirmed'").stdout.strip() == "1"
    assert pg(f"SELECT count(*) FROM tuition_bookings WHERE session_id='{slot['id']}' AND status='confirmed'").stdout.strip() == "1"


def test_tokens_expiry_scope_identity_version_and_handoff(tuition):
    pg = tuition
    slot = session(pg, "Guarded", capacity=5, trials=5)
    person = participant(pg, 11, "guarded")
    token = prepare(pg, 11, person, slot)
    assert "42501" in confirm(pg, 14, token, check=False).stderr
    pg("UPDATE conversations SET platform_user_id='changed' WHERE id=11;")
    assert "42501" in confirm(pg, 11, token, check=False).stderr
    pg("UPDATE conversations SET platform_user_id='server-generated-session' WHERE id=11;")
    pg("UPDATE tuition_confirmations SET expires_at=now()-interval '1 second' WHERE consumed_at IS NULL;")
    assert "22023" in confirm(pg, 11, token, check=False).stderr
    token = prepare(pg, 11, person, slot)
    catalog(pg, "capacity", {"session_id": slot["id"], "expected_version": 1, "total_capacity": 6, "enrolled_seats": 0, "trial_limit": 5})
    assert "40001" in confirm(pg, 11, token, check=False).stderr
    token = prepare(pg, 11, person, slot)
    pg("INSERT INTO agent_actions(chatbot_id,conversation_id,status,intent) VALUES(7,11,'detected','handoff_request');")
    assert "55000" in confirm(pg, 11, token, check=False).stderr
    pg("UPDATE agent_actions SET status='resolved';")
    pg("INSERT INTO conversation_handoff_controls VALUES(11,10,7,'human_active');")
    assert "55000" in prepare(pg, 11, person, slot, check=False).stderr
    pg("UPDATE conversation_handoff_controls SET handling_mode='ai_active';")
    pg(f"SELECT tuition_update_participant(10,7,11,3,'{person['id']}',1,'Corrected label');", role="service_role")
    assert "40001" in confirm(pg, 11, token, check=False).stderr
    assert "42501" in catalog(pg, "course", {"name": "Unauthorized"}, actor=5, check=False).stderr


def test_failed_reschedule_keeps_original_then_cancel_releases_place(tuition):
    pg = tuition
    original, target = session(pg, "Original"), session(pg, "No trial places", capacity=2, enrolled=0, trials=0)
    person = participant(pg, 15, "reschedule")
    booked = confirm(pg, 15, prepare(pg, 15, person, original))["booking"]
    moving = prepare(pg, 15, person, target, booking=booked)
    assert "23514" in confirm(pg, 15, moving, check=False).stderr
    assert pg(f"SELECT session_id FROM tuition_bookings WHERE id='{booked['id']}'").stdout.strip() == original["id"]
    assert "22023" in catalog(pg, "capacity", {"session_id": original["id"], "expected_version": 1,
        "total_capacity": 1, "enrolled_seats": 1, "trial_limit": 0}, check=False).stderr
    available = session(pg, "Available")
    moved = confirm(pg, 15, prepare(pg, 15, person, available, booking=booked))["booking"]
    assert moved["id"] == booked["id"] and moved["session_id"] == available["id"]
    assert pg(f"SELECT status FROM business_events WHERE record_id='{booked['id']}' ORDER BY id DESC LIMIT 1").stdout.strip() == "confirmed"
    assert "40001" in pg(f"SELECT tuition_cancel_trial(10,7,15,NULL,'{booked['id']}','stale-cancel',{booked['version']});", role="service_role", check=False).stderr
    assert pg(f"SELECT status FROM tuition_bookings WHERE id='{booked['id']}'").stdout.strip() == "confirmed"
    for _ in range(2):
        pg(f"SELECT tuition_cancel_trial(10,7,15,NULL,'{booked['id']}','cancel-once',{moved['version']});", role="service_role")
    assert pg(f"SELECT count(*) FROM business_events WHERE record_id='{booked['id']}' AND status='cancelled'").stdout.strip() == "1"
    assert pg(f"SELECT count(*) FROM tuition_bookings WHERE session_id='{available['id']}' AND status='confirmed'").stdout.strip() == "0"
    assert "42501" in pg("SELECT * FROM tuition_confirmations;", role="service_role", check=False).stderr
    for role in ("anon", "authenticated"):
        assert "42501" in pg("SELECT tuition_confirm_trial(10,7,11,NULL,'fake');", role=role, check=False).stderr
