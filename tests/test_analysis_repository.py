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
