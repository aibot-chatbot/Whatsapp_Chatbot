"""Tenant scoping of report source reads (tuition trials); all database access is mocked."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.database import analysis_repository as repo


S1 = "11111111-1111-4111-8111-111111111111"
S2 = "22222222-2222-4222-8222-222222222222"


class FakeTable:
    """Records every filter per table and replays one page of rows, then an empty page."""

    def __init__(self, name, rows, log):
        self.name, self.rows, self.log, self.calls = name, rows, log, []

    def __getattr__(self, method):
        def record(*args, **kwargs):
            self.calls.append((method, args))
            return self
        return record

    def execute(self):
        self.log.append((self.name, list(self.calls)))
        page = [] if any(method == "gt" for method, _ in self.calls) else self.rows
        self.calls = []
        return SimpleNamespace(data=page)


@pytest.fixture
def db(monkeypatch):
    log, rows = [], {"tuition_sessions": [{"id": S1}, {"id": S2}],
                     "tuition_bookings": [{"id": "b1", "session_id": S1}]}
    fake = MagicMock()
    fake.table.side_effect = lambda name: FakeTable(name, rows.get(name, []), log)
    monkeypatch.setattr(repo, "supabase", fake)
    monkeypatch.setattr(repo, "get_report_context", lambda *a: {})
    monkeypatch.setattr(repo, "list_report_documents", lambda *a: [])
    return SimpleNamespace(log=log, rows=rows, fake=fake)


def reads(db, table):
    return [calls for name, calls in db.log if name == table]


def load(**kwargs):
    return repo.load_report_sources(28, 7, "2026-08-31T16:00:00+00:00", "2026-09-06T16:00:00+00:00",
                                    "2026-09-08T00:00:00+00:00", **kwargs)


def test_tuition_tables_are_not_read_unless_requested(db):
    result = load()
    assert "tuition_sessions" not in result and "tuition_bookings" not in result
    assert not reads(db, "tuition_sessions") and not reads(db, "tuition_bookings")


def test_trial_sessions_are_scoped_to_company_bot_period_and_capture(db):
    result = load(include_tuition=True)
    assert result["tuition_sessions"]["available"] is True
    assert [row["id"] for row in result["tuition_sessions"]["rows"]] == [S1, S2]
    first = reads(db, "tuition_sessions")[0]
    for expected in (("eq", ("company_id", 28)), ("eq", ("chatbot_id", 7)),
                     ("gte", ("starts_at", "2026-08-31T16:00:00+00:00")), ("lt", ("starts_at", "2026-09-06T16:00:00+00:00")),
                     ("lte", ("created_at", "2026-09-08T00:00:00+00:00"))):
        assert expected in first
    columns = next(args[0] for method, args in first if method == "select")
    assert "contact" not in columns and "participant" not in columns


def test_trial_bookings_are_scoped_to_company_bot_and_loaded_sessions_without_contacts(db):
    result = load(include_tuition=True)
    assert result["tuition_bookings"]["rows"] == [{"id": "b1", "session_id": S1}]
    first = reads(db, "tuition_bookings")[0]
    assert ("eq", ("company_id", 28)) in first and ("eq", ("chatbot_id", 7)) in first
    assert ("in_", ("session_id", [S1, S2])) in first
    columns = next(args[0] for method, args in first if method == "select")
    assert "contact_key" not in columns and "participant" not in columns and "conversation_id" not in columns


def test_uuid_keyset_pagination_starts_without_integer_cursor(db):
    load(include_tuition=True)
    first_page = reads(db, "tuition_sessions")[0]
    assert not any(method == "gt" for method, _ in first_page)
    assert ("gt", ("id", S2)) in reads(db, "tuition_sessions")[1]


def test_booking_session_filters_are_chunked(db):
    db.rows["tuition_sessions"] = [{"id": f"00000000-0000-4000-8000-{index:012d}"} for index in range(150)]
    db.rows["tuition_bookings"] = []
    load(include_tuition=True)
    chunks = [args[1] for calls in reads(db, "tuition_bookings") for method, args in calls if method == "in_"]
    assert [len(chunk) for chunk in chunks] == [100, 50]


def test_unreadable_sessions_make_bookings_unknown_not_empty(db, monkeypatch):
    def broken(name):
        table = FakeTable(name, [], db.log)
        if name == "tuition_sessions":
            table.execute = lambda: (_ for _ in ()).throw(RuntimeError("private backend detail"))
        return table
    db.fake.table.side_effect = broken
    result = load(include_tuition=True)
    assert result["tuition_sessions"]["available"] is False
    assert result["tuition_bookings"]["available"] is False
    assert not reads(db, "tuition_bookings")


def test_existing_integer_id_sources_still_use_integer_keyset(db):
    load(include_customer_questions=True)
    assert ("gt", ("id", 0)) in reads(db, "business_events")[0]
    assert ("gt", ("id", 0)) in reads(db, "messages")[0]
