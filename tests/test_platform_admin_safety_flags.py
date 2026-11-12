"""Offline contracts for the platform safety-flags read surface."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from flask import Flask

from app.database import agent_action_repository as repository
from app.database import platform_admin_repository
from app.routes.platform_admin_routes import platform_admin_bp
from app.services import platform_admin_service as service


URL = "/api/platform-admin/safety-flags"
HEADERS = {"Authorization": "Bearer test-token"}
NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
FLAG_FIELDS = {
    "created_at", "company_id", "company_name", "chatbot_id", "conversation_id",
    "filter", "mode", "category", "rule", "source",
}


def flag_row(company_id=100, category="threat", mode=None, **extra):
    return {
        "created_at": NOW.isoformat(), "company_id": company_id,
        "chatbot_id": 20, "conversation_id": 30, "filter": 1,
        "mode": mode, "category": category, "rule": "threat.kill",
        "source": "customer", **extra,
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.decorators.auth_decorator.get_jwt_secret", lambda: "test-secret")
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *args, **kwargs: {
        "user_id": 7, "company_id": 100, "role": "member", "is_platform_admin": False,
    })
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda *_args: {
        "id": 7, "company_id": 100, "email": "internal@example.test",
        "status": "active", "role": "member",
    })
    mapping = MagicMock(return_value={
        "id": 3, "user_id": 7, "is_active": True, "platform_role": "super_admin",
        "modules": {"billing": True, "support": True, "customers": True},
    })
    monkeypatch.setattr(
        "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id", mapping,
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(platform_admin_bp)
    return app.test_client(), mapping


@pytest.fixture
def backend(monkeypatch):
    recent = MagicMock(return_value=[flag_row()])
    counts = MagicMock(return_value=[flag_row()])
    companies = MagicMock(return_value={100: {"company_name": "Example Client"}})

    def audited(*args):
        platform_admin_repository.validate_audit_event(*args)
        return {"id": 1}

    audit = MagicMock(side_effect=audited)
    monkeypatch.setattr(repository, "get_platform_content_flags", recent)
    monkeypatch.setattr(repository, "iter_platform_content_flag_counts", counts)
    monkeypatch.setattr(service.platform_company_repository,
                        "get_companies_by_ids_for_platform_admin", companies)
    monkeypatch.setattr(platform_admin_repository, "insert_platform_admin_audit_event", audit)
    clock = MagicMock(wraps=datetime)
    clock.now.return_value = NOW
    monkeypatch.setattr(service, "datetime", clock)
    return SimpleNamespace(recent=recent, counts=counts, companies=companies, audit=audit)


def test_missing_token_is_denied(client, backend):
    response = client[0].get(URL)
    assert response.status_code == 401
    backend.recent.assert_not_called()
    backend.audit.assert_not_called()


@pytest.mark.parametrize("mapping", [None, {"id": 3, "is_active": False}])
def test_non_admin_is_denied(client, backend, mapping):
    client[1].return_value = mapping
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 403
    backend.recent.assert_not_called()
    backend.audit.assert_not_called()


def test_staff_with_every_module_is_denied(client, backend):
    client[1].return_value = {
        "id": 3, "user_id": 7, "is_active": True, "platform_role": "admin",
        "modules": {"billing": True, "support": True, "customers": True},
    }
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 403
    assert response.json["code"] == "platform_module_access_denied"
    backend.recent.assert_not_called()


def test_happy_path_shape_defaults_and_validated_audit(client, backend):
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["status"] == "success"
    data = response.json["data"]
    assert set(data) == {"flags", "companies", "category_counts", "filters", "limit"}
    assert set(data["flags"][0]) == FLAG_FIELDS
    assert data["flags"][0]["company_name"] == "Example Client"
    assert data["companies"] == [{
        "company_id": 100, "company_name": "Example Client", "counted_flags_7d": 1, "level": "none",
    }]
    assert data["category_counts"] == {"threat": 1}
    assert data["filters"] == {"days": 7, "company_id": None, "category": None}
    assert data["limit"] == 200
    backend.recent.assert_called_once_with(company_id=None, category=None, days=7, limit=200, now=NOW)
    args = backend.audit.call_args.args
    assert args[:4] == (3, "platform_admin.safety_flags.list", "agent_actions", None)
    assert args[4]["endpoint"] == URL
    assert args[4]["returned_count"] == 1


@pytest.mark.parametrize("days,limit", [(1, 1), (30, 200)])
def test_filters_reach_repository_and_summary_window_stays_seven_days(client, backend, days, limit):
    response = client[0].get(URL, query_string={
        "days": days, "limit": limit, "company_id": 100, "category": "threat",
    }, headers=HEADERS)
    assert response.status_code == 200
    backend.recent.assert_called_once_with(company_id=100, category="threat", days=days, limit=limit, now=NOW)
    backend.counts.assert_called_once_with(
        since=(NOW - timedelta(days=7)).isoformat(), until=NOW.isoformat(), company_id=100,
    )
    assert response.json["data"]["filters"] == {"days": days, "company_id": 100, "category": "threat"}
    assert backend.audit.call_args.args[4]["company_filter_applied"] is True
    assert backend.audit.call_args.args[4]["category_filter_applied"] is True


@pytest.mark.parametrize("query,code", [
    ({"days": "0"}, "invalid_days"), ({"days": "31"}, "invalid_days"),
    ({"days": "abc"}, "invalid_days"), ({"days": "1.5"}, "invalid_days"),
    ({"days": ""}, "invalid_days"), ({"limit": "0"}, "invalid_limit"),
    ({"limit": "201"}, "invalid_limit"), ({"limit": "1.1"}, "invalid_limit"),
    ({"limit": "abc"}, "invalid_limit"), ({"company_id": "0"}, "invalid_company_id"),
    ({"company_id": "-1"}, "invalid_company_id"), ({"company_id": "1.5"}, "invalid_company_id"),
    ({"company_id": "abc"}, "invalid_company_id"),
    ({"company_id": "9223372036854775808"}, "invalid_company_id"),
    ({"category": "unknown"}, "invalid_category"),
    ({"category": ""}, "invalid_category"), ({"extra": "value"}, "invalid_query"),
    ([("days", "1"), ("days", "2")], "invalid_query"),
    ([("company_id", "1"), ("company_id", "2")], "invalid_query"),
    ([("category", "threat"), ("category", "self_harm")], "invalid_query"),
])
def test_bad_query_uses_error_envelope_without_reading(client, backend, query, code):
    response = client[0].get(URL, query_string=query, headers=HEADERS)
    assert response.status_code == 400
    assert response.json["status"] == "error"
    assert response.json["code"] == code
    assert isinstance(response.json["message"], str)
    backend.recent.assert_not_called()
    backend.audit.assert_not_called()


@pytest.mark.parametrize("category", sorted(service.CONTENT_FLAG_CATEGORIES))
def test_every_supported_category_is_accepted(client, backend, category):
    response = client[0].get(URL, query_string={"category": category}, headers=HEADERS)
    assert response.status_code == 200
    assert backend.recent.call_args.kwargs["category"] == category


def test_payload_and_extra_customer_fields_never_leak_and_child_rule_is_hidden(client, backend):
    private = {"message_text": "PRIVATE MESSAGE", "customer_phone": "+60123456789", "name": "PRIVATE NAME"}
    backend.recent.return_value = [
        flag_row(payload={"content_flag": {**private}, **private}, reason="PRIVATE REASON", **private),
        flag_row(category="child_sexual", rule="PRIVATE CHILD RULE", payload=private),
    ]
    backend.companies.return_value = {100: {"company_name": "Example Client", **private}}
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 200
    flags = response.json["data"]["flags"]
    assert all(set(flag) == FLAG_FIELDS for flag in flags)
    assert flags[1]["rule"] is None
    for value in [*private.values(), "PRIVATE REASON", "PRIVATE CHILD RULE"]:
        assert value not in response.get_data(as_text=True)
        assert value not in str(backend.audit.call_args)


@pytest.mark.parametrize("count,level", [(4, "none"), (5, "warning"), (9, "warning"), (10, "pause_requested")])
def test_client_level_thresholds_are_seven_day_totals_independent_of_list(client, backend, count, level):
    backend.recent.return_value = [flag_row(category="self_harm")]
    backend.counts.return_value = [flag_row(category="drugs") for _ in range(count)]
    response = client[0].get(URL, query_string={"days": 1, "limit": 1, "category": "self_harm"}, headers=HEADERS)
    assert response.status_code == 200
    summary = response.json["data"]["companies"][0]
    assert summary["counted_flags_7d"] == count
    assert summary["level"] == level
    assert response.json["data"]["category_counts"] == {"self_harm": 1}


def test_self_harm_and_log_mode_are_not_counted_and_companies_are_separate(client, backend):
    backend.counts.return_value = [
        *[flag_row() for _ in range(4)],
        *[flag_row(category="self_harm") for _ in range(10)],
        *[flag_row(mode="log") for _ in range(10)],
        flag_row(company_id=200, mode="log"),
        *[flag_row(company_id=300, mode="block") for _ in range(10)],
    ]
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 200
    summaries = {row["company_id"]: row for row in response.json["data"]["companies"]}
    assert [(summaries[key]["counted_flags_7d"], summaries[key]["level"]) for key in (100, 200, 300)] == [
        (4, "none"), (0, "none"), (10, "pause_requested"),
    ]


def test_empty_result_is_success_and_audited(client, backend):
    backend.recent.return_value = []
    backend.counts.return_value = []
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["data"]["flags"] == []
    assert response.json["data"]["companies"] == []
    assert response.json["data"]["category_counts"] == {}
    assert backend.audit.call_args.args[4]["returned_count"] == 0


@pytest.mark.parametrize("failing_read", ["recent", "counts", "companies"])
def test_database_failure_returns_generic_503_without_audit(client, backend, failing_read):
    getattr(backend, failing_read).side_effect = RuntimeError("PRIVATE BACKEND ERROR")
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 503
    assert response.json["code"] == "platform_admin_data_unavailable"
    assert "PRIVATE" not in response.get_data(as_text=True)
    backend.audit.assert_not_called()


def test_audit_failure_fails_closed(client, backend):
    backend.audit.side_effect = RuntimeError("PRIVATE AUDIT ERROR")
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 503
    assert response.json["code"] == "platform_admin_audit_unavailable"
    assert "data" not in response.json
    assert "PRIVATE" not in response.get_data(as_text=True)


def query_mock(monkeypatch):
    query = MagicMock()
    for method in ("select", "eq", "gte", "lte", "order", "limit", "range"):
        getattr(query, method).return_value = query
    query.not_.is_.return_value = query
    supabase = MagicMock()
    supabase.table.return_value = query
    monkeypatch.setattr(repository, "supabase", supabase)
    return query


def test_recent_query_filters_in_database_before_cap_and_selects_only_metadata(monkeypatch):
    query = query_mock(monkeypatch)
    query.execute.return_value = SimpleNamespace(data=[flag_row()])
    rows = repository.get_platform_content_flags(company_id=100, category="threat", days=30, now=NOW)
    assert rows == [flag_row()]
    query.eq.assert_any_call("intent", "unknown")
    query.eq.assert_any_call("company_id", 100)
    query.eq.assert_any_call("payload->content_flag->>category", "threat")
    query.not_.is_.assert_called_once_with("payload->content_flag", "null")
    query.gte.assert_called_once_with("created_at", (NOW - timedelta(days=30)).isoformat())
    query.lte.assert_called_once_with("created_at", NOW.isoformat())
    query.limit.assert_called_once_with(200)
    assert query.mock_calls.index(call.not_.is_("payload->content_flag", "null")) < query.mock_calls.index(call.limit(200))
    assert query.order.call_args_list == [call("created_at", desc=True), call("id", desc=True)]
    columns = query.select.call_args.args[0]
    assert columns == (
        "created_at,company_id,chatbot_id,conversation_id,"
        "filter:payload->content_flag->filter,mode:payload->content_flag->>mode,"
        "category:payload->content_flag->>category,rule:payload->content_flag->>rule,"
        "source:payload->content_flag->>source"
    )


@pytest.mark.parametrize("kwargs", [{"days": 0}, {"days": 31}, {"days": True}, {"limit": 0}, {"limit": 201}, {"limit": True}])
def test_repository_rejects_attempts_to_exceed_hard_bounds(monkeypatch, kwargs):
    query = query_mock(monkeypatch)
    with pytest.raises(ValueError):
        repository.get_platform_content_flags(**kwargs)
    query.execute.assert_not_called()


def test_seven_day_count_query_pages_past_recent_row_cap_without_reading_payloads(monkeypatch):
    query = query_mock(monkeypatch)
    first_page = [flag_row() for _ in range(200)]
    last_page = [flag_row(company_id=200)]
    query.execute.side_effect = [SimpleNamespace(data=first_page), SimpleNamespace(data=last_page)]
    since = (NOW - timedelta(days=7)).isoformat()
    result = list(repository.iter_platform_content_flag_counts(since=since, until=NOW.isoformat(), company_id=100))
    assert result == first_page + last_page
    assert query.range.call_args_list == [call(0, 199), call(200, 399)]
    assert query.not_.is_.call_args_list == [call("payload->content_flag", "null")] * 2
    assert query.eq.call_args_list == [call("intent", "unknown"), call("company_id", 100)] * 2
    assert query.gte.call_args_list == [call("created_at", since)] * 2
    assert query.lte.call_args_list == [call("created_at", NOW.isoformat())] * 2
    assert query.select.call_args.args[0] == (
        "company_id,category:payload->content_flag->>category,mode:payload->content_flag->>mode"
    )
    calls = query.mock_calls
    assert calls.index(call.not_.is_("payload->content_flag", "null")) < calls.index(call.range(0, 199))
    assert query.order.call_args_list == [call("created_at", desc=True), call("id", desc=True)] * 2
