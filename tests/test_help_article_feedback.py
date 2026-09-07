"""Slice 2 - help article helpfulness feedback.

Contract: docs/sdlc/01-requirements.md FR-1, docs/sdlc/02-analysis.md sections
3 and 4. One vote per tenant per article, tenancy derived from the JWT and
never from the body, and no way to learn that an unpublished article exists.
"""

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

from app.database import help_article_repository
from app.routes.help_routes import help_bp
from app.services import help_article_service


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "050_help_articles.sql"

ARTICLE_ROWS = (
    {"id": 1, "slug": "published", "is_published": True},
    {"id": 4, "slug": "unpublished-draft", "is_published": False},
)


class _UniqueViolation(Exception):
    """What supabase-py raises when a unique index rejects an insert."""

    def __init__(self):
        super().__init__({"code": "23505", "message": "duplicate key value"})
        self.code = "23505"


class _FakeTable:
    def __init__(self, rows, *, insert_error=None):
        self.rows = [dict(row) for row in rows]
        self.insert_error = insert_error
        self.selected = None
        self.filters = []
        self.inserted = None
        self.updated = None
        self.limit_value = None

    def select(self, fields):
        self.selected = fields
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        self.rows = [row for row in self.rows if row.get(field) == value]
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def insert(self, payload):
        self.inserted = dict(payload)
        return self

    def update(self, payload):
        self.updated = dict(payload)
        return self

    def execute(self):
        if self.inserted is not None and self.insert_error is not None:
            raise self.insert_error
        if self.inserted is not None or self.updated is not None:
            return MagicMock(data=[dict(self.inserted or self.updated)])
        fields = [name for name in (self.selected or "").split(",") if name]
        rows = self.rows[: self.limit_value] if self.limit_value else self.rows
        return MagicMock(data=[{name: row.get(name) for name in fields} for row in rows])


class _FakeSupabase:
    def __init__(self, rows=ARTICLE_ROWS, *, insert_error=None):
        self._rows = rows
        self._insert_error = insert_error
        self.tables = []

    def table(self, name):
        rows = self._rows if name == "help_articles" else ()
        table = _FakeTable(rows, insert_error=self._insert_error)
        self.tables.append((name, table))
        return table

    def named(self, name):
        return [table for table_name, table in self.tables if table_name == name]


class FeedbackMigrationTest(unittest.TestCase):
    """Slice 2 writes to a table slice 1's migration already created."""

    @classmethod
    def setUpClass(cls):
        cls.normalized = re.sub(
            r"\s+", " ", MIGRATION.read_text(encoding="utf-8")
        ).lower()

    def test_feedback_table_grants_the_update_the_second_vote_needs(self):
        self.assertIn(
            "grant select, insert, update on table public.help_article_feedback "
            "to service_role",
            self.normalized,
        )

    def test_feedback_table_never_grants_delete(self):
        self.assertNotIn(
            "delete on table public.help_article_feedback to service_role",
            self.normalized,
        )

    def test_one_vote_per_tenant_per_article_is_enforced_by_a_unique_index(self):
        self.assertIn(
            "create unique index if not exists help_article_feedback_article_company_idx "
            "on public.help_article_feedback(article_id, company_id)",
            self.normalized,
        )


class FeedbackRepositoryTests(unittest.TestCase):
    def test_published_article_lookup_filters_on_id_and_publication(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            row = help_article_repository.get_published_help_article(1)
        self.assertEqual(row, {"id": 1})
        table = fake.named("help_articles")[0]
        self.assertIn(("id", 1), table.filters)
        self.assertIn(("is_published", True), table.filters)

    def test_unpublished_article_is_indistinguishable_from_a_missing_one(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            self.assertIsNone(help_article_repository.get_published_help_article(4))
            self.assertIsNone(help_article_repository.get_published_help_article(999))

    def test_article_lookup_rejects_bad_ids_before_any_query(self):
        for article_id in (0, -1, True, None, "1", 1.5):
            with self.subTest(article_id=article_id):
                fake = _FakeSupabase()
                with patch.object(help_article_repository, "supabase", fake):
                    with self.assertRaises(ValueError):
                        help_article_repository.get_published_help_article(article_id)
                self.assertEqual(fake.tables, [])

    def test_first_vote_inserts_exactly_the_three_feedback_columns(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            created = help_article_repository.record_help_article_feedback(
                article_id=1, company_id=100, was_helpful=False
            )
        self.assertTrue(created)
        table = fake.named("help_article_feedback")[0]
        self.assertEqual(
            table.inserted,
            {"article_id": 1, "company_id": 100, "was_helpful": False},
        )
        self.assertIsNone(table.updated)

    def test_second_vote_updates_the_existing_row_for_that_tenant(self):
        fake = _FakeSupabase(insert_error=_UniqueViolation())
        with patch.object(help_article_repository, "supabase", fake):
            created = help_article_repository.record_help_article_feedback(
                article_id=1, company_id=100, was_helpful=True
            )
        self.assertFalse(created)
        tables = fake.named("help_article_feedback")
        self.assertEqual(len(tables), 2)
        update_table = tables[1]
        self.assertEqual(update_table.updated, {"was_helpful": True})
        self.assertEqual(
            update_table.filters, [("article_id", 1), ("company_id", 100)]
        )

    def test_a_non_unique_database_error_propagates_instead_of_updating(self):
        fake = _FakeSupabase(insert_error=RuntimeError("connection reset"))
        with patch.object(help_article_repository, "supabase", fake):
            with self.assertRaises(RuntimeError):
                help_article_repository.record_help_article_feedback(
                    article_id=1, company_id=100, was_helpful=True
                )
        self.assertEqual(len(fake.named("help_article_feedback")), 1)

    def test_feedback_write_rejects_bad_arguments_before_any_query(self):
        cases = [
            {"article_id": 0, "company_id": 100, "was_helpful": True},
            {"article_id": 1, "company_id": 0, "was_helpful": True},
            {"article_id": 1, "company_id": True, "was_helpful": True},
            {"article_id": 1, "company_id": 100, "was_helpful": "yes"},
            {"article_id": 1, "company_id": 100, "was_helpful": 1},
            {"article_id": 1, "company_id": 100, "was_helpful": None},
        ]
        for kwargs in cases:
            with self.subTest(**kwargs):
                fake = _FakeSupabase()
                with patch.object(help_article_repository, "supabase", fake):
                    with self.assertRaises(ValueError):
                        help_article_repository.record_help_article_feedback(**kwargs)
                self.assertEqual(fake.tables, [])


class FeedbackServiceTests(unittest.TestCase):
    def _record(self, payload, *, company_id=100, article_id=1, **patches):
        defaults = {
            "get_published_help_article": {"id": article_id},
            "record_help_article_feedback": True,
        }
        defaults.update(patches)
        with patch.object(
            help_article_service.help_article_repository,
            "get_published_help_article",
            **self._side(defaults["get_published_help_article"]),
        ) as reader, patch.object(
            help_article_service.help_article_repository,
            "record_help_article_feedback",
            **self._side(defaults["record_help_article_feedback"]),
        ) as writer:
            try:
                result = help_article_service.record_article_feedback(
                    article_id, payload, company_id=company_id
                )
            except help_article_service.HelpArticleServiceError as exc:
                return exc, reader, writer
            return result, reader, writer

    @staticmethod
    def _side(value):
        if isinstance(value, Exception):
            return {"side_effect": value}
        return {"return_value": value}

    def test_happy_path_returns_the_recorded_vote(self):
        result, _, writer = self._record({"was_helpful": True})
        self.assertEqual(result, {"article_id": 1, "was_helpful": True})
        writer.assert_called_once_with(article_id=1, company_id=100, was_helpful=True)

    def test_tenancy_comes_from_the_server_context_only(self):
        result, _, writer = self._record({"was_helpful": False}, company_id=555)
        self.assertEqual(result["was_helpful"], False)
        self.assertEqual(writer.call_args.kwargs["company_id"], 555)

    def test_a_body_carrying_company_id_is_rejected(self):
        error, _, writer = self._record({"was_helpful": True, "company_id": 1})
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "unsupported_field")
        writer.assert_not_called()

    def test_a_non_object_body_is_rejected(self):
        for payload in (None, [], "was_helpful", 1):
            with self.subTest(payload=payload):
                error, reader, _ = self._record(payload)
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_request")
                reader.assert_not_called()

    def test_was_helpful_must_be_a_real_boolean(self):
        for value in ({}, {"was_helpful": "true"}, {"was_helpful": 1},
                      {"was_helpful": None}, {"was_helpful": "yes"}):
            with self.subTest(payload=value):
                error, reader, _ = self._record(value)
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_was_helpful")
                reader.assert_not_called()

    def test_unpublished_or_missing_article_is_a_404_and_writes_nothing(self):
        error, _, writer = self._record(
            {"was_helpful": True}, get_published_help_article=None
        )
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.code, "help_article_not_found")
        writer.assert_not_called()

    def test_invalid_article_id_is_rejected_before_the_lookup(self):
        for article_id in (0, -3, True):
            with self.subTest(article_id=article_id):
                error, reader, _ = self._record(
                    {"was_helpful": True}, article_id=article_id
                )
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_article_id")
                reader.assert_not_called()

    def test_broken_tenant_context_fails_closed_as_a_server_error(self):
        for company_id in (0, None, "100", True):
            with self.subTest(company_id=company_id):
                error, reader, _ = self._record(
                    {"was_helpful": True}, company_id=company_id
                )
                self.assertEqual(error.status_code, 500)
                self.assertEqual(error.code, "authentication_context_invalid")
                reader.assert_not_called()

    def test_lookup_failure_becomes_503_without_leaking_postgrest(self):
        error, _, writer = self._record(
            {"was_helpful": True},
            get_published_help_article=RuntimeError(
                "postgrest: relation help_articles does not exist"
            ),
        )
        self.assertEqual(error.status_code, 503)
        self.assertEqual(error.code, "help_feedback_unavailable")
        self.assertNotIn("postgrest", error.message)
        writer.assert_not_called()

    def test_write_failure_becomes_503_without_leaking_postgrest(self):
        error, _, _ = self._record(
            {"was_helpful": True},
            record_help_article_feedback=RuntimeError(
                "postgrest: duplicate key value violates help_article_feedback"
            ),
        )
        self.assertEqual(error.status_code, 503)
        self.assertEqual(error.code, "help_feedback_unavailable")
        self.assertNotIn("help_article_feedback", error.message)


class FeedbackRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(help_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": 7, "company_id": 100, "role": "member"},
            ),
            patch(
                "app.database.user_repository.get_user_by_id",
                return_value={
                    "id": 7,
                    "company_id": 100,
                    "email": "tenant@example.test",
                    "status": "active",
                    "role": "member",
                },
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def _post(self, payload, article_id=1):
        return self.client.post(
            f"/api/help/articles/{article_id}/feedback",
            json=payload,
            headers=self.headers,
        )

    def test_unauthenticated_vote_is_rejected_and_never_reaches_the_database(self):
        with patch.object(
            help_article_service.help_article_repository,
            "record_help_article_feedback",
        ) as writer:
            response = self.client.post(
                "/api/help/articles/1/feedback", json={"was_helpful": True}
            )
        self.assertEqual(response.status_code, 401)
        writer.assert_not_called()

    def test_successful_vote_uses_the_jwt_company_and_returns_the_envelope(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self._post({"was_helpful": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"status": "success", "data": {"article_id": 1, "was_helpful": False}},
        )
        self.assertEqual(
            fake.named("help_article_feedback")[0].inserted["company_id"], 100
        )

    def test_a_second_vote_updates_rather_than_duplicating(self):
        fake = _FakeSupabase(insert_error=_UniqueViolation())
        with patch.object(help_article_repository, "supabase", fake):
            response = self._post({"was_helpful": True})
        self.assertEqual(response.status_code, 200)
        tables = fake.named("help_article_feedback")
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[1].updated, {"was_helpful": True})

    def test_voting_on_an_unpublished_article_is_a_404(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self._post({"was_helpful": True}, article_id=4)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["code"], "help_article_not_found")
        self.assertEqual(fake.named("help_article_feedback"), [])

    def test_the_404_body_never_says_the_article_is_unpublished(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            unpublished = self._post({"was_helpful": True}, article_id=4)
            missing = self._post({"was_helpful": True}, article_id=999)
        self.assertEqual(unpublished.json, missing.json)
        body = unpublished.get_data(as_text=True)
        self.assertNotIn("published", body)
        self.assertNotIn("draft", body)

    def test_a_rejected_body_carries_a_stable_machine_readable_code(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self._post({"was_helpful": "true"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json), {"status", "code", "message"})
        self.assertEqual(response.json["code"], "invalid_was_helpful")
        self.assertEqual(fake.tables, [])

    def test_the_article_read_route_keeps_its_two_key_error_envelope(self):
        """Slice 1's shape is pinned by 03-design section 5; do not widen it."""
        with patch.object(
            help_article_service.help_article_repository,
            "list_published_help_articles",
            side_effect=RuntimeError("boom"),
        ):
            response = self.client.get("/api/help/articles", headers=self.headers)
        self.assertEqual(set(response.json), {"status", "message"})

    def test_the_feedback_route_is_registered_on_the_real_app(self):
        from app import create_app

        rules = {rule.rule for rule in create_app().url_map.iter_rules()}
        self.assertIn("/api/help/articles/<int:article_id>/feedback", rules)


if __name__ == "__main__":
    unittest.main()
