"""Actual reminder SQL transitions in a fresh loopback-only PostgreSQL cluster."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from uuid import uuid4

import pytest

from tests.test_analysis_postgres import pg,literal,race  # noqa: F401
from tests.test_tuition_postgres import tuition,session,participant,prepare,confirm  # noqa: F401


@pytest.fixture(scope="module")
def reminder_db(tuition):
    tuition("""CREATE TABLE telegram_channels(id bigint PRIMARY KEY,company_id bigint,chatbot_id bigint,
      is_active boolean,connection_status text,verified_at timestamptz,telegram_bot_id text);
      INSERT INTO telegram_channels VALUES(20,10,7,true,'connected',now(),'1234');
      UPDATE conversations SET source_channel='telegram',source_channel_id=20,source_provider_id='1234',platform_user_id='5678' WHERE id=11;
      ALTER TABLE conversation_handoff_controls ADD COLUMN automation_epoch bigint DEFAULT 0;
      ALTER TABLE messages ADD COLUMN platform_message_id text,ADD COLUMN delivery_status text;
      CREATE SEQUENCE reminder_message_id_seq START 1000;
      ALTER TABLE messages ALTER COLUMN id SET DEFAULT nextval('reminder_message_id_seq');
    """)
    sql=(Path(__file__).parents[1]/"data/067_tuition_reminders.sql").read_text(encoding="utf-8")
    tuition(sql)
    tuition(sql)
    return tuition


def booking(pg,key):
    slot=session(pg,key,capacity=4,trials=4)
    person=participant(pg,11,key)
    result=confirm(pg,11,prepare(pg,11,person,slot))["booking"]
    assert result["reminder_enabled"] is True
    pg(f"UPDATE tuition_bookings SET reminder_at=now()-interval '10 seconds' WHERE id='{result['id']}';")
    return result


def claim(pg):
    result=pg("SELECT row_to_json(e) FROM claim_automation_events_v1('tuition_reminder',1,300) e;",role="service_role").stdout.strip()
    return json.loads(result) if result else None


def apply(pg,event,operation,output=None,check=True):
    return pg(f"SELECT tuition_apply_reminder({event['id']},'{event['lease_token']}','{operation}',{literal(output)});",role="service_role",check=check)


def test_duplicate_tick_single_admission_and_atomic_transcript_receipt(reminder_db):
    pg=reminder_db
    booking(pg,"delivery")
    outputs=race(lambda:json.loads(pg("SELECT tuition_enqueue_reminders();",role="service_role").stdout))
    assert sum(row["enqueued"] for row in outputs)==1
    event=claim(pg)
    assert json.loads(apply(pg,event,"inspect").stdout)["status"]=="ready"
    assert json.loads(apply(pg,event,"begin").stdout)["started"] is True
    assert json.loads(apply(pg,event,"begin").stdout)["status"]=="needs_review"
    assert "22023" in apply(pg,event,"finish",{"text":"Reminder"},check=False).stderr
    receipt={"provider_message_id":"987","text":"Reminder"}
    first=json.loads(apply(pg,event,"finish",receipt).stdout)
    again=json.loads(apply(pg,event,"finish",receipt).stdout)
    assert first==again
    assert pg("SELECT count(*) FROM messages WHERE platform_message_id='987'").stdout.strip()=="1"
    assert pg("SELECT count(*) FROM business_events WHERE action_type='trial_reminder' AND status='completed' AND details->>'delivery_status'='accepted'").stdout.strip()=="1"
    assert pg(f"SELECT external_effect_started FROM automation_events WHERE id={event['id']}").stdout.strip()=="f"
    for role in ("anon","authenticated"):
        assert "42501" in pg("SELECT tuition_enqueue_reminders();",role=role,check=False).stderr


@pytest.mark.parametrize("change",["consent","cancel","handoff","epoch","channel"])
def test_state_changed_after_enqueue_never_starts_delivery(reminder_db,change):
    pg=reminder_db
    booked=booking(pg,change)
    pg("SELECT tuition_enqueue_reminders();",role="service_role")
    event=claim(pg)
    if change=="consent":pg(f"UPDATE tuition_bookings SET reminder_consent=false WHERE id='{booked['id']}';")
    elif change=="cancel":pg(f"UPDATE tuition_bookings SET status='cancelled',version=version+1 WHERE id='{booked['id']}';")
    elif change=="channel":pg("UPDATE telegram_channels SET is_active=false WHERE id=20;")
    else:pg(f"INSERT INTO conversation_handoff_controls(conversation_id,company_id,chatbot_id,handling_mode,automation_epoch) VALUES(11,10,7,'{'human_active' if change=='handoff' else 'ai_active'}',1) ON CONFLICT(conversation_id) DO UPDATE SET handling_mode=EXCLUDED.handling_mode,automation_epoch=EXCLUDED.automation_epoch;")
    result=json.loads(apply(pg,event,"begin").stdout)
    assert result["status"]=="completed" and result["result"]["delivery_status"]=="skipped"
    assert pg(f"SELECT external_effect_started FROM automation_events WHERE id={event['id']}").stdout.strip()=="f"
    pg("UPDATE telegram_channels SET is_active=true WHERE id=20; DELETE FROM conversation_handoff_controls;")


def test_expired_delivery_requires_review_and_overdue_never_catches_up(reminder_db):
    pg=reminder_db
    booked=booking(pg,"uncertain")
    pg("SELECT tuition_enqueue_reminders();",role="service_role")
    event=claim(pg)
    apply(pg,event,"begin")
    pg(f"UPDATE automation_events SET lease_expires_at=now()-interval '1 second' WHERE id={event['id']};")
    assert claim(pg) is None
    assert pg(f"SELECT reminder_status FROM tuition_bookings WHERE id='{booked['id']}'").stdout.strip()=="needs_review"
    overdue=booking(pg,"overdue")
    pg(f"UPDATE tuition_bookings SET reminder_at=now()-interval '10 minutes' WHERE id='{overdue['id']}';")
    assert json.loads(pg("SELECT tuition_enqueue_reminders();",role="service_role").stdout)["skipped_overdue"]==1
    assert claim(pg) is None


def test_overdue_scan_cannot_overwrite_a_concurrent_reschedule(reminder_db):
    pg=reminder_db
    booked=booking(pg,"overdue-reschedule-cas")
    pg(f"UPDATE tuition_bookings SET reminder_at=now()-interval '10 minutes' WHERE id='{booked['id']}';")
    writer_name="reminder-reschedule-"+uuid4().hex
    reader_name="reminder-scan-"+uuid4().hex
    def wait_for_session(name,event_type,event):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            waiting=pg(f"SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name='{name}' "
                       f"AND wait_event_type='{event_type}' AND wait_event='{event}');").stdout.strip()
            if waiting=="t":return
            time.sleep(0.1)
        raise AssertionError("The PostgreSQL race did not reach its required interleaving")
    # The uncommitted reschedule owns the booking row. The enqueue SELECT sees
    # the previous overdue version, then its UPDATE must wait for the writer.
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer=pool.submit(pg,f"SET application_name='{writer_name}'; BEGIN; "
            f"UPDATE tuition_bookings SET version=version+1,reminder_at=now()+interval '1 day',"
            f"reminder_status='pending',reminder_unavailable_reason=NULL WHERE id='{booked['id']}'; "
            "SELECT pg_sleep(7); COMMIT;")
        wait_for_session(writer_name,"Timeout","PgSleep")
        scan=pool.submit(pg,f"SET application_name='{reader_name}'; SELECT tuition_enqueue_reminders();",role="service_role")
        wait_for_session(reader_name,"Lock","transactionid")
        writer.result(timeout=10)
        result=json.loads(scan.result(timeout=10).stdout)
    assert result["skipped_overdue"]==0
    assert pg(f"SELECT version||':'||reminder_status||':'||(reminder_at>now())::text FROM tuition_bookings WHERE id='{booked['id']}';").stdout.strip()=="2:pending:true"
