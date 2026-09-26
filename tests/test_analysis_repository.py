"""Analysis persistence boundaries; all network access is mocked."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import analysis_repository as repo


@pytest.fixture
def db(monkeypatch):
    fake = Mock()
    fake.rpc.return_value.execute.return_value = SimpleNamespace(data={"id": "report"})
    monkeypatch.setattr(repo, "supabase", fake)
    return fake


def test_request_is_one_atomic_rpc(db):
    repo.create_report_request(10, 7, 3, "request-1", "Weekly report")
    db.table.assert_not_called()
    name, args = db.rpc.call_args.args
    assert name == "analysis_create_report_request"
    assert args["p_company_id"] == 10 and args["p_actor_user_id"] == 3


@pytest.mark.parametrize("bad", [None, 0, -1, True, "10"])
def test_bad_scope_never_reaches_database(db, bad):
    with pytest.raises(ValueError):
        repo.create_report_request(bad, 7, 3, "a", "Report")
    db.rpc.assert_not_called()


def test_empty_rpc_result_is_not_success(db):
    db.rpc.return_value.execute.return_value.data = None
    with pytest.raises(repo.AnalysisUnavailable):
        repo.create_report_request(10, 7, 3, "a", "Report")


def test_model_step_only_two_names(db):
    with pytest.raises(ValueError):
        repo.begin_model_step(company_id=10, chatbot_id=7,
            report_id="00000000-0000-4000-8000-000000000001", event_id=1,
            lease_token="00000000-0000-4000-8000-000000000002", step_id="retry")
    db.rpc.assert_not_called()


def test_backend_failure_is_sanitized(db):
    db.rpc.return_value.execute.side_effect = RuntimeError("password and private customer text")
    with pytest.raises(repo.AnalysisUnavailable) as error:
        repo.create_report_request(10, 7, 3, "a", "Report")
    assert "private" not in str(error.value)


def test_snapshot_write_always_includes_lease_scope(db):
    rid = "00000000-0000-4000-8000-000000000001"
    lease = "00000000-0000-4000-8000-000000000002"
    repo.save_snapshot_fenced(company_id=10, chatbot_id=7, report_id=rid,
        event_id=15, lease_token=lease, snapshot={"metrics": {"count": 2}})
    name, args = db.rpc.call_args.args
    assert name == "analysis_apply_run"
    assert (args["p_company_id"], args["p_chatbot_id"], args["p_report_id"],
            args["p_event_id"], args["p_lease_token"]) == (10, 7, rid, 15, lease)
    assert args["p_operation"] == "snapshot"
    db.table.assert_not_called()


def test_source_pagination_follows_short_pages_and_marks_cap(monkeypatch):
    pages = [[{"id": 1}], [{"id": 2}, {"id": 3}], [{"id": 4}]]
    query = Mock()
    query.gt.return_value.order.return_value.limit.return_value = query
    query.execute.side_effect = [SimpleNamespace(data=page) for page in pages]
    source = repo._page_source(lambda: query, maximum=3)
    assert source["available"] is True and source["truncated"] is True
    assert [row["id"] for row in source["rows"]] == [1, 2, 3]
    assert query.gt.call_args_list[-1].args == ("id", 3)


def test_source_failure_never_becomes_empty_success():
    query = Mock()
    query.gt.return_value.order.return_value.limit.return_value = query
    query.execute.side_effect = RuntimeError("offline")
    assert repo._page_source(lambda: query) == {
        "rows": [], "available": False, "truncated": False, "error_code": "source_unavailable"}


def test_selected_document_ids_are_checked_against_this_bot(monkeypatch):
    monkeypatch.setattr(repo, "get_report_context", lambda *a: {})
    monkeypatch.setattr(repo, "_page_source", lambda *a, **k: {"rows": [], "available": True})
    monkeypatch.setattr(repo, "list_report_documents", lambda *a: [{"id": 10}])
    with pytest.raises(repo.AnalysisScopeDenied):
        repo.load_report_sources(10, 7, None, None, "2026-09-22T00:00:00+00:00", [99])


def test_customer_activity_is_newest_first_and_pages_below_the_cursor(monkeypatch):
    from unittest.mock import MagicMock, call
    query = MagicMock()
    for method in ("table", "select", "eq", "gt", "lt", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"id": 9}, {"id": 8}])
    monkeypatch.setattr(repo, "supabase", query)

    assert [row["id"] for row in repo.list_business_events(10, 7)] == [9, 8]
    assert query.order.call_args_list == [call("id", desc=True)]
    query.lt.assert_not_called()
    query.gt.assert_not_called()

    query.reset_mock()
    repo.list_business_events(10, 7, after_id=8)
    assert query.lt.call_args_list == [call("id", 8)]
    query.gt.assert_not_called()
    assert query.order.call_args_list == [call("id", desc=True)]


def test_timestamp_only_pagination_rejected(db):
    with pytest.raises(ValueError, match="tie breaker"):
        repo.list_reports(10, 7, before_created_at="2026-09-22T00:00:00+00:00")


def test_schedule_atomic_enqueue_carries_period_key(db):
    repo.enqueue_schedule_report(10, 7, "00000000-0000-4000-8000-000000000001",
        period_key="2026-W39", request_spec={"kind": "business"}, next_due_at="2026-09-29T00:00:00+00:00")
    assert db.rpc.call_args.args[0] == "analysis_enqueue_schedule"
    assert db.rpc.call_args.args[1]["p_period_key"] == "2026-W39"
    db.table.assert_not_called()


def test_customer_text_requires_explicit_bounded_source_request(monkeypatch):
    from unittest.mock import MagicMock, call
    query = MagicMock()
    for method in ("table", "select", "eq", "is_", "gte", "lt", "lte"):
        getattr(query, method).return_value = query
    monkeypatch.setattr(repo, "supabase", query)
    monkeypatch.setattr(repo, "get_report_context", lambda *a: {})
    monkeypatch.setattr(repo, "list_report_documents", lambda *a: [])
    limits = []
    def read(factory, maximum=5000):
        limits.append(maximum)
        factory()
        return {"rows": [], "available": True, "truncated": False, "error_code": None}
    monkeypatch.setattr(repo, "_page_source", read)
    result = repo.load_report_sources(10, 7, None, None, "2026-09-22T00:00:00Z")
    assert "customer_questions" not in result
    assert not any("message_text" in args.args[0] for args in query.select.call_args_list)
    query.reset_mock()
    result = repo.load_report_sources(10, 7, None, None, "2026-09-22T00:00:00Z", include_customer_questions=True)
    assert result["customer_questions"]["available"] is True and 100 in limits
    assert call("conversations.chatbot_id", 7) in query.eq.call_args_list
    assert call("sender_type", "customer") in query.eq.call_args_list
    assert call("actor_user_id", "null") in query.is_.call_args_list


# --- owner-chosen schedule slot (data/070) ----------------------------------

STORED_SCHEDULE = {"id": "00000000-0000-4000-8000-000000000001", "company_id": 10, "chatbot_id": 7,
                   "actor_user_id": 3, "frequency": "monthly", "enabled": True,
                   "run_weekday": None, "run_day": 0, "run_time": "18:15:00",
                   "next_due_at": "2026-10-31T10:15:00+00:00"}


def _query(monkeypatch, rows):
    query = Mock()
    for method in ("table", "select", "eq", "lte", "order", "range", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)
    monkeypatch.setattr(repo, "supabase", query)
    return query


def test_slot_is_stored_in_database_form_and_returned_in_api_form(db):
    db.rpc.return_value.execute.return_value = SimpleNamespace(data=STORED_SCHEDULE)
    row = repo.upsert_schedule(10, 7, 3, frequency="monthly", enabled=True,
                               next_due_at="2026-10-31T10:15:00+00:00", run_day="last", run_time="18:15")
    name, params = db.rpc.call_args.args
    assert name == "analysis_upsert_schedule"
    assert params["p_run_day"] == 0 and params["p_run_time"] == "18:15"
    assert "p_run_weekday" not in params
    assert (row["run_day"], row["run_time"], row["run_weekday"]) == ("last", "18:15", None)


def test_numbered_day_and_weekday_pass_through(db):
    repo.upsert_schedule(10, 7, 3, frequency="weekly", enabled=True, run_weekday=0, run_time="09:00")
    assert db.rpc.call_args.args[1]["p_run_weekday"] == 0
    repo.upsert_schedule(10, 7, 3, frequency="monthly", enabled=True, run_day=15, run_time="09:00")
    assert db.rpc.call_args.args[1]["p_run_day"] == 15


@pytest.mark.parametrize("action", [
    lambda: repo.skip_schedule_period(STORED_SCHEDULE, next_due_at="2026-11-30T10:15:00+00:00"),
    lambda: repo.disable_schedule(STORED_SCHEDULE),
    lambda: repo.upsert_schedule(10, 7, 3, frequency="monthly", enabled=False),
])
def test_skip_and_disable_never_send_a_slot_so_the_stored_choice_survives(db, action):
    # The RPC keeps the stored value for every argument not sent; sending only
    # the 7 pre-070 arguments also keeps these calls working on either schema.
    action()
    params = db.rpc.call_args.args[1]
    assert not {"p_run_weekday", "p_run_day", "p_run_time"} & set(params)


def test_schedule_reads_return_the_api_form(monkeypatch):
    _query(monkeypatch, [dict(STORED_SCHEDULE)])
    assert repo.list_schedules(10, 7)[0]["run_day"] == "last"
    due = repo.list_due_schedules()[0]
    assert (due["run_day"], due["run_time"]) == ("last", "18:15")
    assert repo.list_enabled_company_schedules(10)[0]["run_time"] == "18:15"


def test_rows_without_a_slot_read_as_null(monkeypatch):
    _query(monkeypatch, [{**STORED_SCHEDULE, "enabled": False, "run_day": None, "run_time": None}])
    row = repo.list_schedules(10, 7)[0]
    assert (row["run_weekday"], row["run_day"], row["run_time"]) == (None, None, None)
