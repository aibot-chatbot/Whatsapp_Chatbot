from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask


CHANNEL = {"id": 5, "chatbot_id": 3, "company_id": 2, "whatsapp_business_account_id": "222",
           "connection_status": "connected", "is_active": True, "access_token": "fake-graph-token"}
URL = "/api/meta-templates?chatbot_id=3"
HEADERS = {"Authorization": "Bearer fake-user-token"}


@pytest.fixture
def client(monkeypatch):
    from app.routes import meta_template_routes as routes

    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **kw: {"user_id": 1})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id",
                        lambda _: {"id": 1, "company_id": 2, "role": "owner", "status": "active"})
    monkeypatch.setattr(routes, "verify_chatbot_access", lambda _: {"id": 3, "company_id": 2})
    monkeypatch.setattr(routes, "get_whatsapp_channels_by_chatbot", lambda _: [CHANNEL])
    app = Flask(__name__)
    app.register_blueprint(routes.meta_template_blueprint)
    return app.test_client()


def test_whatsapp_template_migration_and_rollback_contract():
    data = Path(__file__).resolve().parents[1] / "data"
    sql = " ".join((data / "091_whatsapp_templates.sql").read_text().lower().split())
    rollback = " ".join((data / "091_whatsapp_templates_rollback.sql").read_text().lower().split())
    for required in (
        "begin; set local lock_timeout = '3s'; set local statement_timeout = '30s';",
        "create table public.whatsapp_templates",
        "references public.companies(id) on delete cascade",
        "references public.whatsapp_channels(id)",
        "unique (waba_id, name, language)",
        "enable row level security",
        "revoke all on public.whatsapp_templates from public, anon, authenticated",
        "on public.whatsapp_templates to service_role",
        "on sequence public.whatsapp_templates_id_seq to service_role",
        "add column followup_template_id bigint references public.whatsapp_templates(id) on delete set null",
    ):
        assert required in sql
    assert rollback.index("drop column followup_template_id") < rollback.index("drop table public.whatsapp_templates")
    assert sql.endswith("commit;") and rollback.endswith("commit;")


@pytest.mark.parametrize(("components", "body_variables", "extra_parameters"), [
    ([{"type": "BODY", "text": "Hello again"}], False, False),
    ([{"type": "BODY", "text": "Hi {{first_name}}"}], True, False),
    ([{"type": "BODY", "add_security_recommendation": True}], False, False),
    ([{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Hello"}], False, True),
    ([{"type": "BODY", "text": "Hello"},
      {"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://example.invalid/{{1}}"}]}], False, True),
])
def test_create_whatsapp_template_tracks_meta_result(client, monkeypatch, components, body_variables, extra_parameters):
    from app.database import db
    from app.services import meta_template_service as service

    graph = Mock(return_value=Mock(status_code=201, json=lambda: {"id": "777", "status": "PENDING",
                                                                "category": "UTILITY"}))
    monkeypatch.setattr(service.requests, "post", graph)
    table = Mock()
    monkeypatch.setattr(db, "supabase", SimpleNamespace(table=lambda name: table if name == "whatsapp_templates" else None))
    response = client.post(URL, headers=HEADERS, json={"name": "Friendly Reminder", "language": "en_US",
                                                      "category": "MARKETING", "components": components})
    assert response.status_code == 201
    assert graph.call_args.kwargs["json"]["name"] == "friendly_reminder"
    table.insert.assert_called_once_with({
        "company_id": 2, "channel_id": 5, "waba_id": "222", "meta_template_id": "777",
        "name": "friendly_reminder", "language": "en_US", "category": "UTILITY", "status": "PENDING",
        "body_has_variables": body_variables, "requires_component_parameters": extra_parameters,
    })


class MemoryQuery:
    """Select/update only; count attempted writes as well as affected rows."""
    def __init__(self, rows, writes):
        self.rows = list(rows)
        self.writes = writes
        self.changes = None

    def select(self, fields):
        return self

    def eq(self, field, value):
        self.rows = [row for row in self.rows if row.get(field) == value]
        return self

    def is_(self, field, value):
        assert value == "null"
        return self.eq(field, None)

    def in_(self, field, choices):
        self.rows = [row for row in self.rows if row.get(field) in choices]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def order(self, field):
        self.rows.sort(key=lambda row: row[field])
        return self

    def update(self, values):
        self.changes = values
        return self

    def execute(self):
        if self.changes is not None:
            self.writes.append(self.changes)
            for row in self.rows:
                row.update(self.changes)
        return SimpleNamespace(data=self.rows)


@pytest.fixture
def store(monkeypatch):
    from app.database import db

    base = {"id": 11, "waba_id": "222", "meta_template_id": "777", "name": "follow_up", "language": "en",
            "status": "PENDING", "category": "UTILITY", "company_id": 2, "body_has_variables": False,
            "requires_component_parameters": False, "status_event_time": None}
    rows = [base, {**base, "id": 12, "company_id": 9, "waba_id": "999"}]
    writes = []
    monkeypatch.setattr(db, "supabase", SimpleNamespace(table=lambda _: MemoryQuery(rows, writes)))
    return rows, writes


def webhook(template_id, status, when=123):
    from app.views import handle_message

    value = {"event": status, "message_template_id": template_id, "message_template_category": "MARKETING",
             "reason": "BAD_FORMAT" if status == "REJECTED" else None}
    body = {"object": "whatsapp_business_account", "entry": [{"id": "222", "time": when, "changes": [
        {"field": "message_template_status_update", "value": value}]}]}
    with Flask(__name__).test_request_context(json=body):
        return handle_message()[1]


def test_template_status_webhook_scopes_waba_and_acknowledges_unknown_without_write(store):
    rows, writes = store
    assert webhook(777, "REJECTED") == 200
    assert (rows[0]["status"], rows[0]["rejected_reason"], rows[0]["category"]) == ("REJECTED", "BAD_FORMAT", "MARKETING")
    assert rows[1]["status"] == "PENDING"
    assert webhook("missing", "APPROVED") == 200
    assert webhook(777, "APPROVED", when=122) == 200
    assert len(writes) == 1
    assert webhook(777, "APPROVED", when=124) == 200
    assert rows[0]["status"] == "APPROVED" and rows[0]["rejected_reason"] is None


@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_template_routes_refuse_disconnected_channel_without_graph(client, monkeypatch, method):
    from app.routes import meta_template_routes as routes
    from app.services import meta_template_service as service

    monkeypatch.setattr(routes, "get_whatsapp_channels_by_chatbot",
                        lambda _: [{**CHANNEL, "connection_status": "pending"}])
    graph = Mock()
    monkeypatch.setattr(service.requests, method, graph)
    path = URL.replace("templates?", "templates/reminder?") if method == "delete" else URL
    response = getattr(client, method)(path, headers=HEADERS, json={"name": "reminder"})
    assert response.status_code == 400
    graph.assert_not_called()


@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_template_provider_error_is_private(client, monkeypatch, caplog, method):
    from app.services import meta_template_service as service

    monkeypatch.setattr(service.requests, method, Mock(side_effect=RuntimeError("private-provider-detail")))
    path = URL.replace("templates?", "templates/reminder?") if method == "delete" else URL
    response = getattr(client, method)(path, headers=HEADERS, json={"name": "reminder"})
    assert response.status_code == 500
    assert "private-provider-detail" not in response.get_data(as_text=True) + caplog.text
    assert "RuntimeError" in caplog.text


def test_delete_template_clears_local_selection_for_this_company_and_waba(client, monkeypatch):
    from app.database import db
    from app.services import meta_template_service as service

    graph = Mock()
    monkeypatch.setattr(service.requests, "delete", graph)
    table = Mock()
    query = table.delete.return_value
    query.eq.return_value = query
    monkeypatch.setattr(db, "supabase", SimpleNamespace(table=lambda _: table))
    response = client.delete("/api/meta-templates/reminder?chatbot_id=3", headers=HEADERS)
    assert response.status_code == 200
    graph.assert_called_once()
    assert sorted(c.args for c in query.eq.call_args_list) == [
        ("company_id", 2), ("name", "reminder"), ("waba_id", "222")]
    query.execute.assert_called_once()


def test_template_listing_requires_operational_company(client, monkeypatch):
    from app.services import meta_template_service as service

    monkeypatch.setattr("app.services.company_status_service.get_company_status_by_id",
                        lambda _: {"status": "suspended"})
    graph = Mock()
    monkeypatch.setattr(service.requests, "get", graph)
    assert client.get(URL, headers=HEADERS).status_code == 403
    graph.assert_not_called()


def test_followup_template_options_and_lookup_use_the_same_eligibility(store):
    from app.database import whatsapp_template_repository as repo

    rows, _ = store
    rows[0].update(status="APPROVED", category="MARKETING")
    for index, overrides in enumerate((
        {"status": "PAUSED"}, {"category": "UTILITY"}, {"body_has_variables": True},
        {"requires_component_parameters": True}, {"company_id": 9}, {"waba_id": "999"},
    ), 20):
        rows.append({**rows[0], **overrides, "id": index})
    assert [t["id"] for t in repo.list_eligible(2, ["222"])] == [11]
    assert repo.get_eligible(2, 11, "222")["name"] == "follow_up"
    assert all(repo.get_eligible(2, index, "222") is None for index in range(20, 26))


def test_template_receipts_count_accepted_official_whatsapp_and_restore_087_on_rollback():
    data = Path(__file__).resolve().parents[1] / "data"
    def view(filename):
        text = (data / filename).read_text()
        return text[text.index("CREATE OR REPLACE VIEW"):text.index("COMMIT;", text.index("CREATE OR REPLACE VIEW"))].strip()

    original = view("087_followup_controls.sql")
    updated = view("091_whatsapp_templates.sql")
    assert view("091_whatsapp_templates_rollback.sql") == original
    assert updated[updated.index("UNION ALL"):] == original[original.index("UNION ALL"):]
    assert "c.source_channel = 'whatsapp'" in updated
    assert "m.delivery_status IN ('sent', 'delivered', 'read')" in updated and "m.message_type = 'template'" in updated
    assert "m.follow_up_sent_at IS NOT NULL" in updated and "m.sender_type = 'bot'" in updated
