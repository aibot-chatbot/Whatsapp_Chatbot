"""Backend surface for the conversations redesign (DESIGN.md "Pinned API
contract for the conversations redesign" and "Lead status migration").

Covers, each with a tenant-scoping proof:

- GET /api/conversations?company=1 -- company-scoped list across every
  non-archived, non-deleted bot the caller owns (?chatbot_id= is untouched).
- GET /api/conversations/<id>/intents?chatbot_id= -- agent_actions rows,
  never including payload.
- GET /api/company/members -- id/name/email only.
- The crm_leads status vocabulary migration (new/contacted/qualified/
  won/lost), including the one-release write-time compatibility shim for
  the two retired values (in_progress, closed).

Two fake-Supabase shapes are used, matching the two families already in this
suite:

- ``_FakeSupabase`` (queued-response, records writes) -- same shape as
  ``tests/test_persona_derivation.py::_FakeSupabase`` -- for the crm_lead
  write-normalization tests, and a variant for agent_actions that asserts on
  the exact table sequence, matching
  ``tests/test_agent_action_resolution.py``.
- ``_FilterSupabase`` (filter-evaluating, real eq/in_/neq/is_/order) -- same
  shape as ``tests/test_billing_channel_usage_count.py`` -- for the
  company-scoped conversation list, because "which bots/conversations are
  visible" is exactly the tenancy behaviour under test here, not just an
  implementation detail about which calls were made.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch


# =====================================================================
# Fake Supabase #1: filter-evaluating, multi-table (company-scoped list)
# =====================================================================

class _FilterResponse:
    def __init__(self, data=None):
        self.data = data or []


class _FilterQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.rows = [row for row in self.rows if row.get(field) == value]
        return self

    def neq(self, field, value):
        self.rows = [row for row in self.rows if row.get(field) != value]
        return self

    def is_(self, field, value):
        if value == "null":
            self.rows = [row for row in self.rows if row.get(field) is None]
        return self

    def in_(self, field, values):
        allowed = set(values or [])
        self.rows = [row for row in self.rows if row.get(field) in allowed]
        return self

    def order(self, field, desc=False):
        self.rows = sorted(self.rows, key=lambda row: row.get(field), reverse=desc)
        return self

    def limit(self, _value):
        return self

    def execute(self):
        return _FilterResponse(data=self.rows)


class _FilterSupabase:
    """Real per-field filtering over an in-memory {table: [rows]} map, so a
    test can assert "row X is invisible to another tenant" as behaviour, and
    count how many times each table was queried (the N+1 proof)."""

    def __init__(self, tables):
        self.tables = {name: list(rows) for name, rows in tables.items()}
        self.table_calls = []

    def table(self, table_name):
        self.table_calls.append(table_name)
        return _FilterQuery(self.tables.get(table_name, []))


def _patched_company_scope(fake):
    from app.database import billing_usage_repository, conversation_repository

    return (
        patch.object(conversation_repository, "supabase", fake),
        patch.object(billing_usage_repository, "supabase", fake),
    )


# =====================================================================
# 1. GET /api/conversations?company=1 -- repository layer
# =====================================================================

class CompanyScopedConversationsRepositoryTests(unittest.TestCase):
    CHATBOTS = [
        {"id": 10, "company_id": 1, "status": "active", "deleted_at": None, "bot_name": "Support Bot"},
        {"id": 11, "company_id": 1, "status": "active", "deleted_at": None, "bot_name": "Sales Bot"},
        {"id": 12, "company_id": 1, "status": "archived", "deleted_at": None, "bot_name": "Archived Bot"},
        {"id": 13, "company_id": 1, "status": "active", "deleted_at": "2026-01-01T00:00:00Z", "bot_name": "Deleted Bot"},
        {"id": 20, "company_id": 2, "status": "active", "deleted_at": None, "bot_name": "Other Co Bot"},
    ]
    CONVERSATIONS = [
        {"id": 100, "chatbot_id": 10, "updated_at": "2026-08-20T10:00:00Z", "customer_name": "Alice"},
        {"id": 101, "chatbot_id": 11, "updated_at": "2026-08-20T11:00:00Z", "customer_name": "Bob"},
        {"id": 102, "chatbot_id": 12, "updated_at": "2026-08-20T09:00:00Z", "customer_name": "Archived-bot lead"},
        {"id": 103, "chatbot_id": 13, "updated_at": "2026-08-20T09:30:00Z", "customer_name": "Deleted-bot lead"},
        {"id": 104, "chatbot_id": 20, "updated_at": "2026-08-20T12:00:00Z", "customer_name": "Other company lead"},
    ]
    MESSAGES = [
        {"conversation_id": 100}, {"conversation_id": 100}, {"conversation_id": 100},
        {"conversation_id": 101},
        {"conversation_id": 104},  # belongs to an excluded conversation; must not leak in
    ]

    def _call(self, company_id, tables=None):
        from app.database.conversation_repository import get_conversations_for_company

        fake = _FilterSupabase(tables or {
            "chatbots": self.CHATBOTS,
            "conversations": self.CONVERSATIONS,
            "messages": self.MESSAGES,
        })
        repo_patch, billing_patch = _patched_company_scope(fake)
        with repo_patch, billing_patch:
            result = get_conversations_for_company(company_id)
        return result, fake

    def test_only_conversations_from_non_archived_non_deleted_owned_bots_are_returned(self):
        result, _ = self._call(1)

        self.assertEqual({row["id"] for row in result}, {100, 101})

    def test_archived_bot_conversations_are_excluded(self):
        result, _ = self._call(1)

        self.assertNotIn(102, {row["id"] for row in result})

    def test_deleted_bot_conversations_are_excluded(self):
        result, _ = self._call(1)

        self.assertNotIn(103, {row["id"] for row in result})

    def test_another_companys_conversations_never_appear(self):
        result, _ = self._call(1)

        self.assertNotIn(104, {row["id"] for row in result})

    def test_cross_tenant_isolation_is_symmetric(self):
        result, _ = self._call(2)

        self.assertEqual([row["id"] for row in result], [104])

    def test_each_row_is_annotated_with_chatbot_id_bot_name_and_message_count(self):
        result, _ = self._call(1)
        by_id = {row["id"]: row for row in result}

        self.assertEqual(by_id[100]["chatbot_id"], 10)
        self.assertEqual(by_id[100]["bot_name"], "Support Bot")
        self.assertEqual(by_id[100]["message_count"], 3)

        self.assertEqual(by_id[101]["chatbot_id"], 11)
        self.assertEqual(by_id[101]["bot_name"], "Sales Bot")
        self.assertEqual(by_id[101]["message_count"], 1)

    def test_a_conversation_with_no_messages_reports_zero_not_a_missing_key(self):
        tables = {
            "chatbots": [{"id": 10, "company_id": 1, "status": "active", "deleted_at": None, "bot_name": "Support Bot"}],
            "conversations": [{"id": 100, "chatbot_id": 10, "updated_at": "2026-08-20T10:00:00Z"}],
            "messages": [],
        }
        result, _ = self._call(1, tables=tables)

        self.assertEqual(result[0]["message_count"], 0)

    def test_results_are_ordered_most_recently_updated_first(self):
        result, _ = self._call(1)

        self.assertEqual([row["id"] for row in result], [101, 100])

    def test_message_count_is_one_batched_query_not_one_per_conversation(self):
        _, fake = self._call(1)

        self.assertEqual(fake.table_calls.count("messages"), 1)

    def test_a_company_with_no_owned_chatbots_short_circuits_without_querying_conversations(self):
        result, fake = self._call(1, tables={"chatbots": [], "conversations": self.CONVERSATIONS, "messages": self.MESSAGES})

        self.assertEqual(result, [])
        self.assertNotIn("conversations", fake.table_calls)
        self.assertNotIn("messages", fake.table_calls)


# =====================================================================
# 2. GET /api/conversations?company=1 / ?chatbot_id= -- route layer
# =====================================================================

class ConversationsRouteCompanyModeTests(unittest.TestCase):
    AUTH_HEADERS = {"Authorization": "Bearer test-token"}

    def setUp(self):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _auth(self, company_id=28, user_id=31, role="admin"):
        user = {"id": user_id, "company_id": company_id, "role": role, "status": "active"}
        return (
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": user_id, "company_id": company_id, "role": role},
            ),
            patch("app.database.user_repository.get_user_by_id", return_value=user),
        )

    def test_chatbot_id_mode_is_byte_identical_to_before(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch("app.routes.conversation_routes.verify_chatbot_access") as verify, \
                patch("app.routes.conversation_routes.get_conversations_by_bot", return_value=[{"id": 1}]) as by_bot, \
                patch("app.routes.conversation_routes.get_conversations_for_company") as by_company:
            response = self.client.get("/api/conversations?chatbot_id=29", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "success", "data": [{"id": 1}]})
        verify.assert_called_once_with(29)
        by_bot.assert_called_once_with(29)
        by_company.assert_not_called()

    def test_company_mode_is_used_when_chatbot_id_is_absent(self):
        jwt_patch, user_patch = self._auth(company_id=28)
        with jwt_patch, user_patch, \
                patch("app.routes.conversation_routes.get_conversations_for_company", return_value=[{"id": 2}]) as by_company, \
                patch("app.routes.conversation_routes.get_conversations_by_bot") as by_bot, \
                patch("app.routes.conversation_routes.verify_chatbot_access") as verify:
            response = self.client.get("/api/conversations?company=1", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "success", "data": [{"id": 2}]})
        by_company.assert_called_once_with(28)
        by_bot.assert_not_called()
        verify.assert_not_called()

    def test_chatbot_id_takes_precedence_when_both_are_given(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch("app.routes.conversation_routes.verify_chatbot_access"), \
                patch("app.routes.conversation_routes.get_conversations_by_bot", return_value=[]) as by_bot, \
                patch("app.routes.conversation_routes.get_conversations_for_company") as by_company:
            response = self.client.get("/api/conversations?chatbot_id=29&company=1", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        by_bot.assert_called_once_with(29)
        by_company.assert_not_called()

    def test_missing_both_params_returns_the_original_400(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch:
            response = self.client.get("/api/conversations", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "chatbot_id is required"},
        )

    def test_company_mode_always_uses_the_authoritative_company_id_not_a_query_param(self):
        # This endpoint takes no company-id query parameter at all, so there
        # is no field to spoof -- prove two different authenticated
        # companies get their own, correctly-scoped call from an identical
        # query string.
        for company_id in (28, 99):
            jwt_patch, user_patch = self._auth(company_id=company_id)
            with jwt_patch, user_patch, \
                    patch("app.routes.conversation_routes.get_conversations_for_company", return_value=[]) as by_company:
                response = self.client.get("/api/conversations?company=1", headers=self.AUTH_HEADERS)

            self.assertEqual(response.status_code, 200)
            by_company.assert_called_once_with(company_id)

    def test_cross_tenant_chatbot_id_mode_denies_before_data_access(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch(
                    "app.routes.conversation_routes.verify_chatbot_access",
                    side_effect=PermissionError("You do not have access to this chatbot."),
                ), \
                patch("app.routes.conversation_routes.get_conversations_by_bot") as by_bot:
            response = self.client.get("/api/conversations?chatbot_id=999", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 403)
        by_bot.assert_not_called()


# =====================================================================
# 3. GET /api/conversations/<id>/intents -- repository layer
# =====================================================================

class _SimpleQuery:
    def __init__(self, data):
        self.data = data
        self.select_fields = None
        self.eq_calls = []

    def select(self, fields):
        self.select_fields = fields
        return self

    def eq(self, *_args, **_kwargs):
        self.eq_calls.append((_args[0], _args[1]))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class _SequencedSupabase:
    """Replays one (table_name, rows) pair per .table() call and asserts the
    table name matches what the repository is expected to query next --
    same shape as tests/test_agent_action_resolution.py::_MultiTableSupabase."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def table(self, table_name):
        expected_table, data = self.responses.pop(0)
        assert table_name == expected_table, (table_name, expected_table)
        query = _SimpleQuery(data)
        self.queries.append(query)
        return query


_INTENT_ROW = {
    "message_id": 501,
    "intent": "lead_interest",
    "confidence": 0.8,
    "action_type": "create_lead",
    "reason": "Asked for pricing.",
    "status": "detected",
    "conversations": {"chatbot_id": 7},
}


class AgentActionsIntentsRepositoryTests(unittest.TestCase):
    def test_pending_escalations_use_a_safe_action_projection(self):
        from app.database import agent_action_repository

        fake = _SequencedSupabase([
            ("agent_actions", [{"id": 1, "conversation_id": 5}]),
            ("conversations", []),
        ])
        with patch.object(agent_action_repository, "supabase", fake):
            agent_action_repository.get_pending_escalations(7, 28)

        self.assertNotIn("*", fake.queries[0].select_fields)
        self.assertNotIn("payload", fake.queries[0].select_fields)

    def test_select_never_requests_the_payload_column(self):
        from app.database import agent_action_repository

        fake = _SequencedSupabase([("agent_actions", [dict(_INTENT_ROW)])])
        with patch.object(agent_action_repository, "supabase", fake):
            agent_action_repository.get_agent_actions_by_conversation_and_chatbot(5, 7, 28)

        select_fields = fake.queries[0].select_fields
        self.assertNotIn("payload", select_fields)
        for expected_field in ("message_id", "intent", "confidence", "action_type", "reason", "status"):
            self.assertIn(expected_field, select_fields)
        self.assertIn(("chatbot_id", 7), fake.queries[0].eq_calls)
        self.assertIn(("company_id", 28), fake.queries[0].eq_calls)

    def test_strips_the_embedded_conversations_join_key_from_each_row(self):
        from app.database import agent_action_repository

        fake = _SequencedSupabase([("agent_actions", [dict(_INTENT_ROW)])])
        with patch.object(agent_action_repository, "supabase", fake):
            result = agent_action_repository.get_agent_actions_by_conversation_and_chatbot(5, 7, 28)

        self.assertEqual(len(result), 1)
        self.assertNotIn("conversations", result[0])
        self.assertNotIn("payload", result[0])
        self.assertEqual(result[0]["message_id"], 501)

    def test_returns_none_when_the_conversation_belongs_to_a_different_chatbot(self):
        from app.database import agent_action_repository

        fake = _SequencedSupabase([
            ("agent_actions", []),
            ("conversations", []),
        ])
        with patch.object(agent_action_repository, "supabase", fake):
            result = agent_action_repository.get_agent_actions_by_conversation_and_chatbot(5, 7, 28)

        self.assertIsNone(result)

    def test_returns_empty_list_when_the_conversation_has_no_agent_actions_yet(self):
        from app.database import agent_action_repository

        fake = _SequencedSupabase([
            ("agent_actions", []),
            ("conversations", [{"id": 5}]),
        ])
        with patch.object(agent_action_repository, "supabase", fake):
            result = agent_action_repository.get_agent_actions_by_conversation_and_chatbot(5, 7, 28)

        self.assertEqual(result, [])


# =====================================================================
# 4. GET /api/conversations/<id>/intents -- route layer
# =====================================================================

class ConversationIntentsRouteTests(unittest.TestCase):
    AUTH_HEADERS = {"Authorization": "Bearer test-token"}

    def setUp(self):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _auth(self, company_id=28, user_id=31, role="admin"):
        user = {"id": user_id, "company_id": company_id, "role": role, "status": "active"}
        return (
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": user_id, "company_id": company_id, "role": role},
            ),
            patch("app.database.user_repository.get_user_by_id", return_value=user),
        )

    def test_missing_chatbot_id_returns_400(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch:
            response = self.client.get("/api/conversations/5/intents", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 400)

    def test_cross_tenant_conversation_denies_before_data_access(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch(
                    "app.routes.conversation_routes.verify_chatbot_access",
                    side_effect=PermissionError("You do not have access to this chatbot."),
                ), \
                patch("app.routes.conversation_routes.get_agent_actions_by_conversation_and_chatbot") as get_intents:
            response = self.client.get("/api/conversations/5/intents?chatbot_id=29", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 403)
        get_intents.assert_not_called()

    def test_unknown_conversation_returns_404(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch("app.routes.conversation_routes.verify_chatbot_access"), \
                patch("app.routes.conversation_routes.get_agent_actions_by_conversation_and_chatbot", return_value=None):
            response = self.client.get("/api/conversations/5/intents?chatbot_id=29", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 404)

    def test_success_returns_the_repository_rows_and_never_a_payload_key(self):
        rows = [{
            "message_id": 501,
            "intent": "lead_interest",
            "confidence": 0.92,
            "action_type": "create_lead",
            "reason": "Customer asked for pricing.",
            "status": "detected",
        }]
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch("app.routes.conversation_routes.verify_chatbot_access"), \
                patch(
                    "app.routes.conversation_routes.get_agent_actions_by_conversation_and_chatbot",
                    return_value=rows,
                ) as get_intents:
            response = self.client.get("/api/conversations/5/intents?chatbot_id=29", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body, {"status": "success", "data": rows})
        for row in body["data"]:
            self.assertNotIn("payload", row)
        get_intents.assert_called_once_with(5, 29, 28)


# =====================================================================
# 5. GET /api/company/members
# =====================================================================

class CompanyMembersRouteTests(unittest.TestCase):
    AUTH_HEADERS = {"Authorization": "Bearer test-token"}

    def setUp(self):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _auth(self, company_id=28, user_id=31, role="admin"):
        user = {"id": user_id, "company_id": company_id, "role": role, "status": "active"}
        return (
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": user_id, "company_id": company_id, "role": role},
            ),
            patch("app.database.user_repository.get_user_by_id", return_value=user),
        )

    def test_only_id_name_and_email_are_exposed(self):
        company_users = [{
            "id": 1,
            "company_id": 28,
            "full_name": "Alice Tan",
            "email": "alice@example.test",
            "role": "owner",
            "status": "active",
            "is_verified": True,
            "password_hash": "should-never-appear",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }]
        jwt_patch, user_patch = self._auth(company_id=28)
        with jwt_patch, user_patch, \
                patch("app.routes.company_routes.get_users_by_company", return_value=company_users) as get_members:
            response = self.client.get("/api/company/members", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(
            body["data"],
            [{"id": 1, "name": "Alice Tan", "email": "alice@example.test"}],
        )
        for member in body["data"]:
            self.assertEqual(set(member), {"id", "name", "email"})
        get_members.assert_called_once_with(28)

    def test_uses_the_refreshed_company_id_not_a_stale_jwt_claim(self):
        user = {"id": 31, "company_id": 28, "role": "admin", "status": "active"}
        with patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"user_id": 31, "company_id": 1, "role": "owner"},
        ), patch("app.database.user_repository.get_user_by_id", return_value=user), \
                patch("app.routes.company_routes.get_users_by_company", return_value=[]) as get_members:
            self.client.get("/api/company/members", headers=self.AUTH_HEADERS)

        get_members.assert_called_once_with(28)

    def test_inactive_members_are_not_offered_for_new_assignments(self):
        users = [
            {"id": 1, "full_name": "Active", "email": "active@example.test", "status": "active"},
            {"id": 2, "full_name": "Inactive", "email": "inactive@example.test", "status": "inactive"},
        ]
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, patch(
            "app.routes.company_routes.get_users_by_company", return_value=users
        ):
            response = self.client.get("/api/company/members", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"], [{
            "id": 1,
            "name": "Active",
            "email": "active@example.test",
        }])

    def test_repository_error_is_reported_as_a_400(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch(
                    "app.routes.company_routes.get_users_by_company",
                    side_effect=ValueError("Company ID is required"),
                ):
            response = self.client.get("/api/company/members", headers=self.AUTH_HEADERS)

        self.assertEqual(response.status_code, 400)


# =====================================================================
# 6. Lead status migration
# =====================================================================

class CrmLeadStatusVocabularyTests(unittest.TestCase):
    def test_allowed_statuses_are_the_new_five_stage_vocabulary(self):
        from app.database.crm_lead_repository import ALLOWED_CRM_LEAD_STATUSES

        self.assertEqual(
            ALLOWED_CRM_LEAD_STATUSES,
            ["new", "contacted", "qualified", "won", "lost"],
        )

    def test_open_statuses_are_new_contacted_qualified(self):
        from app.database.crm_lead_repository import OPEN_CRM_LEAD_STATUSES

        self.assertEqual(OPEN_CRM_LEAD_STATUSES, ["new", "contacted", "qualified", "in_progress"])

    def test_normalize_maps_in_progress_to_contacted(self):
        from app.database.crm_lead_repository import normalize_crm_lead_status

        self.assertEqual(normalize_crm_lead_status("in_progress"), "contacted")

    def test_normalize_maps_closed_to_lost(self):
        from app.database.crm_lead_repository import normalize_crm_lead_status

        self.assertEqual(normalize_crm_lead_status("closed"), "lost")

    def test_normalize_is_case_and_whitespace_insensitive(self):
        from app.database.crm_lead_repository import normalize_crm_lead_status

        self.assertEqual(normalize_crm_lead_status("  In_Progress  "), "contacted")

    def test_normalize_passes_through_current_vocabulary_unchanged(self):
        from app.database.crm_lead_repository import (
            ALLOWED_CRM_LEAD_STATUSES,
            normalize_crm_lead_status,
        )

        for status in ALLOWED_CRM_LEAD_STATUSES:
            self.assertEqual(normalize_crm_lead_status(status), status)


class _Response:
    def __init__(self, data=None):
        self.data = data or []


class _FakeSupabase:
    """Queued-response PostgREST double, same shape as
    tests/test_persona_derivation.py::_FakeSupabase, plus in_/neq
    passthroughs for OPEN_CRM_LEAD_STATUSES filtering."""

    def __init__(self, select_responses=None, write_result=None):
        self._select_responses = list(select_responses or [])
        self._write_result = write_result
        self.inserts = []
        self.updates = []
        self._mode = None
        self._table = None
        self._payload = None
        self.filters = []

    def table(self, table_name):
        self._table = table_name
        return self

    def select(self, *_args, **_kwargs):
        self._mode = "select"
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def eq(self, *args, **_kwargs):
        if len(args) >= 2:
            self.filters.append((args[0], args[1]))
        return self

    def neq(self, *_args, **_kwargs):
        return self

    def in_(self, *args, **_kwargs):
        if len(args) >= 2:
            self.filters.append((args[0], tuple(args[1])))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self._mode == "select":
            if self._select_responses:
                return _Response(self._select_responses.pop(0))
            return _Response([])

        payload = dict(self._payload)

        if self._mode == "insert":
            self.inserts.append((self._table, payload))
        else:
            self.updates.append((self._table, payload))

        returned = self._write_result
        if returned is None:
            returned = dict(payload)
            returned.setdefault("id", 1)

        return _Response([returned])

    @property
    def last_write_payload(self):
        writes = self.inserts + self.updates
        if not writes:
            raise AssertionError("no insert/update was issued")
        return writes[-1][1]


class CrmLeadStatusWriteNormalizationTests(unittest.TestCase):
    def test_get_accepts_retired_status_filters(self):
        from app.database import crm_lead_repository

        fake = _FakeSupabase()
        with patch.object(crm_lead_repository, "supabase", fake):
            crm_lead_repository.get_crm_leads_by_chatbot(
                chatbot_id=7, status="in_progress"
            )

        self.assertIn(("status", ("contacted", "in_progress")), fake.filters)

    def test_update_accepts_retired_in_progress_and_writes_contacted(self):
        from app.database import crm_lead_repository

        fake = _FakeSupabase()
        with patch.object(crm_lead_repository, "supabase", fake):
            crm_lead_repository.update_crm_lead_status_notes(
                chatbot_id=7, lead_id=3, status="in_progress"
            )

        self.assertEqual(fake.last_write_payload["status"], "contacted")

    def test_update_accepts_retired_closed_and_writes_lost(self):
        from app.database import crm_lead_repository

        fake = _FakeSupabase()
        with patch.object(crm_lead_repository, "supabase", fake):
            crm_lead_repository.update_crm_lead_status_notes(
                chatbot_id=7, lead_id=3, status="closed"
            )

        self.assertEqual(fake.last_write_payload["status"], "lost")

    def test_update_rejects_a_truly_invalid_status_and_writes_nothing(self):
        from app.database import crm_lead_repository

        fake = _FakeSupabase()
        with patch.object(crm_lead_repository, "supabase", fake):
            with self.assertRaises(ValueError):
                crm_lead_repository.update_crm_lead_status_notes(
                    chatbot_id=7, lead_id=3, status="bogus"
                )

        self.assertEqual(fake.inserts + fake.updates, [])

    def test_upsert_normalizes_retired_status_when_updating_an_open_lead(self):
        from app.database import crm_lead_repository

        existing_open_lead = {
            "id": 9,
            "chatbot_id": 7,
            "company_id": 28,
            "conversation_id": 55,
            "status": "new",
        }
        fake = _FakeSupabase(select_responses=[[existing_open_lead]])
        with patch.object(crm_lead_repository, "supabase", fake):
            crm_lead_repository.upsert_crm_lead_by_conversation(
                company_id=28,
                chatbot_id=7,
                conversation_id=55,
                status="in_progress",
            )

        self.assertEqual(fake.last_write_payload["status"], "contacted")

    def test_upsert_rejects_a_truly_invalid_status_before_any_write(self):
        from app.database import crm_lead_repository

        fake = _FakeSupabase()
        with patch.object(crm_lead_repository, "supabase", fake):
            with self.assertRaises(ValueError):
                crm_lead_repository.upsert_crm_lead_by_conversation(
                    company_id=28, chatbot_id=7, conversation_id=55, status="bogus"
                )

        self.assertEqual(fake.inserts + fake.updates, [])


class CrmRoutesRetiredStatusAcceptanceTests(unittest.TestCase):
    """The HTTP layer must accept the retired vocabulary too -- it used to
    pre-validate against ALLOWED_CRM_LEAD_STATUSES before the repository
    ever got a chance to normalise, which would have 400'd an older client
    sending "in_progress" or "closed" despite the repository accepting it."""

    AUTH_HEADERS = {"Authorization": "Bearer test-token"}

    def setUp(self):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _auth(self, company_id=28, user_id=31, role="admin"):
        user = {"id": user_id, "company_id": company_id, "role": role, "status": "active"}
        return (
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": user_id, "company_id": company_id, "role": role},
            ),
            patch("app.database.user_repository.get_user_by_id", return_value=user),
        )

    def test_patch_lead_accepts_retired_in_progress(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch("app.routes.crm_routes.verify_chatbot_access"), \
                patch(
                    "app.routes.crm_routes.update_crm_lead_status_notes",
                    return_value={"id": 3, "status": "contacted"},
                ) as update_status:
            response = self.client.patch(
                "/api/crm/leads/3",
                json={"chatbot_id": 7, "status": "in_progress"},
                headers=self.AUTH_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(update_status.call_args.kwargs["status"], "contacted")

    def test_upsert_lead_accepts_retired_closed(self):
        jwt_patch, user_patch = self._auth()
        conversation = {
            "id": 55, "chatbot_id": 7, "customer_phone": "+60123",
            "customer_name": "Bob", "source_channel": "whatsapp",
        }
        with jwt_patch, user_patch, \
                patch("app.routes.crm_routes.verify_chatbot_access", return_value={"company_id": 28}), \
                patch("app.routes.crm_routes.get_conversation_by_id_and_chatbot", return_value=conversation), \
                patch(
                    "app.routes.crm_routes.upsert_crm_lead_by_conversation",
                    return_value={"id": 9, "status": "lost"},
                ) as upsert:
            response = self.client.post(
                "/api/crm/leads/upsert",
                json={"chatbot_id": 7, "conversation_id": 55, "status": "closed"},
                headers=self.AUTH_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(upsert.call_args.kwargs["status"], "lost")

    def test_patch_lead_still_rejects_a_truly_invalid_status(self):
        jwt_patch, user_patch = self._auth()
        with jwt_patch, user_patch, \
                patch("app.routes.crm_routes.verify_chatbot_access") as verify, \
                patch("app.routes.crm_routes.update_crm_lead_status_notes") as update_status:
            response = self.client.patch(
                "/api/crm/leads/3",
                json={"chatbot_id": 7, "status": "bogus"},
                headers=self.AUTH_HEADERS,
            )

        self.assertEqual(response.status_code, 400)
        verify.assert_not_called()
        update_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
