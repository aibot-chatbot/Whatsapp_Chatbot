"""Real isolated PostgreSQL queue fencing; no production database or provider."""
import json

from tests.test_analysis_postgres import pg  # reuse the bounded scratch-cluster fixture


def test_safe_reclaim_stale_callbacks_backoff_and_type_ownership(pg):
    pg("INSERT INTO automation_events(company_id,chatbot_id,event_type,status,idempotency_key,payload) VALUES "
       "(10,7,'crm_stage_transition','queued','audit-only','{}'),"
       "(10,7,'business_observation','queued','observation-only','{}'),"
       "(10,7,'knowledge_document_follow_up','queued','n8n-only','{}');")
    claim = lambda kind: json.loads(pg(
        f"SELECT coalesce(json_agg(e),'[]') FROM claim_automation_events_v1('{kind}',1,30) e;",
        role="service_role").stdout)
    assert claim("agent_report") == []
    event = claim("n8n")[0]
    assert event["event_type"] == "knowledge_document_follow_up"
    first_token = event["lease_token"]
    event_id = event["id"]
    assert event["attempts"] == 1
    assert claim("n8n") == []
    pg(f"UPDATE automation_events SET lease_expires_at=now()-interval '1 second' WHERE id={event_id};")
    second = claim("n8n")[0]
    assert second["attempts"] == 2 and second["lease_token"] != first_token
    assert pg(f"SELECT count(*) FROM renew_automation_event_lease_v1({event_id},'n8n','{first_token}',30);",role="service_role").stdout.strip() == "0"
    assert pg(f"SELECT count(*) FROM finish_automation_event_v1({event_id},'n8n','{first_token}','completed');",role="service_role").stdout.strip() == "0"
    token = second["lease_token"]
    assert pg(f"SELECT count(*) FROM renew_automation_event_lease_v1({event_id},'business_observation','{token}',30);",role="service_role").stdout.strip() == "0"
    assert pg(f"SELECT count(*) FROM renew_automation_event_lease_v1({event_id},'n8n','{token}',30);",role="service_role").stdout.strip() == "1"
    pg(f"SELECT finish_automation_event_v1({event_id},'n8n','{token}','failed',NULL,'transient',true);",role="service_role")
    assert claim("n8n") == []
    assert pg(f"SELECT status='queued' AND available_at>now() FROM automation_events WHERE id={event_id};").stdout.strip() == "t"
    pg(f"UPDATE automation_events SET available_at=now()-interval '1 second' WHERE id={event_id};")
    third = claim("n8n")[0]
    assert third["attempts"] == 3
    pg(f"SELECT finish_automation_event_v1({event_id},'n8n','{third['lease_token']}','failed',NULL,'transient',true);",role="service_role")
    assert pg(f"SELECT status FROM automation_events WHERE id={event_id};").stdout.strip() == "failed"
    assert claim("n8n") == []
    assert claim("business_observation")[0]["event_type"] == "business_observation"
    assert pg("SELECT status FROM automation_events WHERE event_type='crm_stage_transition';").stdout.strip() == "queued"
    for role in ("anon","authenticated"):
        assert "42501" in pg("SELECT claim_automation_events_v1('n8n');",role=role,check=False).stderr
