"""Clearing Analysis reports hides them from the list; nothing is deleted.

Seams: data/074 (text), analysis_repository (Supabase mocked) and the HTTP route through the
real Flask app with mocked auth, as tests/test_analysis_routes.py does.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

from app import create_app
from app.database import analysis_repository as repo

DATA = Path(__file__).resolve().parents[1] / "data"
UP = (DATA / "074_analysis_report_hide.sql").read_text(encoding="utf-8")
DOWN = (DATA / "074_analysis_report_hide_rollback.sql").read_text(encoding="utf-8")
BASE = "/api/chatbots/7/analysis"
HEADERS = {"Authorization": "Bearer test-token"}
REPORT_ID = str(uuid4())


def _sql(text):
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", text)).strip().lower()


def test_the_migration_only_adds_a_column_and_a_scoped_finished_only_function():
    sql = _sql(UP)
    assert sql.startswith("begin;") and sql.endswith("commit;") and "set local lock_timeout" in sql
    assert "add column if not exists hidden_at timestamptz" in sql
    assert "delete" not in sql
    assert "security definer set search_path = ''" in sql
    assert "where company_id = p_company_id and chatbot_id = p_chatbot_id and hidden_at is null" in sql
    assert "order by id for update" in sql and "hidden_by = p_actor_user_id" in sql
    assert "perform public.analysis_require_actor(p_company_id, p_chatbot_id, p_actor_user_id)" in sql
    assert "status in ('complete', 'partial', 'needs_input', 'needs_review', 'failed')" in sql
    assert "revoke all on function public.analysis_hide_reports(bigint, bigint, bigint, uuid[]) from public, anon, authenticated" in sql
    assert "grant execute on function public.analysis_hide_reports(bigint, bigint, bigint, uuid[]) to service_role" in sql


def test_the_rollback_drops_exactly_what_074_added():
    sql = _sql(DOWN)
    for statement in ("drop function if exists public.analysis_hide_reports(bigint, bigint, bigint, uuid[])",
                      "alter table public.analysis_reports drop column if exists hidden_by",
                      "drop index if exists public.analysis_reports_visible",
                      "alter table public.analysis_reports drop column if exists hidden_at"):
        assert statement in sql


@pytest.fixture
def db(monkeypatch):
    fake = Mock()
    fake.rpc.return_value.execute.return_value = SimpleNamespace(data={"hidden": 2})
    monkeypatch.setattr(repo, "supabase", fake)
    return fake


def test_hiding_is_one_scoped_rpc(db):
    assert repo.hide_reports(10, 7, 3, [REPORT_ID]) == 2
    name, args = db.rpc.call_args.args
    assert name == "analysis_hide_reports"
    assert args == {"p_company_id": 10, "p_chatbot_id": 7, "p_actor_user_id": 3, "p_report_ids": [REPORT_ID]}
    db.table.assert_not_called()


def test_clearing_everything_sends_no_id_list(db):
    repo.hide_reports(10, 7, 3, None)
    assert db.rpc.call_args.args[1]["p_report_ids"] is None


@pytest.mark.parametrize("bad", [["not-a-uuid"], [], [REPORT_ID] * 101])
def test_bad_ids_never_reach_the_database(db, bad):
    with pytest.raises(ValueError):
        repo.hide_reports(10, 7, 3, bad)
    db.rpc.assert_not_called()


def test_the_list_leaves_out_cleared_reports(monkeypatch):
    query = MagicMock()
    for method in ("table", "select", "eq", "is_", "or_", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    monkeypatch.setattr(repo, "supabase", query)

    repo.list_reports(10, 7)

    query.is_.assert_called_once_with("hidden_at", "null")


def test_booking_reads_never_select_customer_details():
    for column in ("customer_name", "customer_phone", "customer_ref", "notes"):
        assert column not in repo.BOOKING_COLUMNS


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AGENT_ANALYSIS_ENABLED", "true")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def auth():
    user = {"id": 31, "company_id": 42, "role": "owner", "status": "active"}
    with patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 31}), \
         patch("app.database.user_repository.get_user_by_id", return_value=user), \
         patch("app.services.company_status_service.get_company_status_by_id", return_value={"status": "active"}), \
         patch("app.routes.analysis_routes.verify_chatbot_access", return_value={"id": 7, "company_id": 42}), \
         patch("app.routes.analysis_routes.can_use_plan_feature", return_value=True):
        yield user


def test_an_owner_removes_one_report_of_their_own_bot(client, auth):
    with patch("app.routes.analysis_routes.repo.hide_reports", return_value=1) as hide:
        response = client.post(BASE + "/reports/hide", headers=HEADERS, json={"report_ids": [REPORT_ID]})

    assert response.status_code == 200 and response.json["data"] == {"hidden": 1}
    hide.assert_called_once_with(42, 7, 31, [REPORT_ID])


def test_clear_finished_reports_hides_all_of_them(client, auth):
    with patch("app.routes.analysis_routes.repo.hide_reports", return_value=3) as hide:
        response = client.post(BASE + "/reports/hide", headers=HEADERS, json={"all_finished": True})

    assert response.json["data"] == {"hidden": 3}
    hide.assert_called_once_with(42, 7, 31, None)


@pytest.mark.parametrize("body", [{}, {"report_ids": []}, {"report_ids": "all"}, {"all_finished": "yes"},
                                  {"report_ids": [REPORT_ID], "all_finished": True}, {"company_id": 99}])
def test_an_unclear_clear_request_is_refused(client, auth, body):
    with patch("app.routes.analysis_routes.repo.hide_reports") as hide:
        assert client.post(BASE + "/reports/hide", headers=HEADERS, json=body).status_code == 400
    hide.assert_not_called()


def test_members_cannot_clear_and_another_companys_bot_is_hidden(client, auth):
    with patch("app.routes.analysis_routes.repo.hide_reports") as hide:
        auth["role"] = "member"
        assert client.post(BASE + "/reports/hide", headers=HEADERS, json={"all_finished": True}).status_code == 403
        auth["role"] = "owner"
        with patch("app.routes.analysis_routes.verify_chatbot_access", side_effect=PermissionError()):
            assert client.post(BASE + "/reports/hide", headers=HEADERS, json={"all_finished": True}).status_code == 404
    hide.assert_not_called()
