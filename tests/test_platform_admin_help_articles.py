"""Platform-admin help article CRUD - slice 5 of the support redesign.

The contract under test is docs/sdlc/01-requirements.md FR-6, plus the
platform-admin conventions already established by
app/routes/platform_admin_routes.py: the blueprint-wide platform_admin_required
guard, the {status, data} success envelope and the {status, code, message}
error envelope.

Two properties this file exists to defend:

* a tenant admin or owner is not a platform admin and must be refused, and
* listing articles must not issue one feedback count query per article.
"""

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

from app.database import help_article_repository
from app.routes.platform_admin_routes import platform_admin_bp
from app.services import platform_admin_help_article_service as admin_help


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "050_help_articles.sql"

SUPPORTED_CATEGORIES = {
    "technical", "account", "chatbot", "integration",
    "billing_question", "ai_credits", "other",
}


def _article(article_id, **overrides):
    row = {
        "id": article_id,
        "category": "chatbot",
        "title": f"Article {article_id}",
        "body": "Body text.",
        "slug": f"article-{article_id}",
        "is_published": True,
        "sort_order": article_id * 10,
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }
    row.update(overrides)
    return row


PUBLISHED = _article(1, slug="published-one", sort_order=10)
ALSO_PUBLISHED = _article(2, slug="published-two", sort_order=10)
DRAFT = _article(3, slug="staff-draft", sort_order=5, is_published=False)

SAMPLE_ARTICLES = (PUBLISHED, ALSO_PUBLISHED, DRAFT)

SAMPLE_FEEDBACK = (
    {"id": 1, "article_id": 1, "company_id": 100, "was_helpful": True},
    {"id": 2, "article_id": 1, "company_id": 101, "was_helpful": True},
    {"id": 3, "article_id": 1, "company_id": 102, "was_helpful": False},
    {"id": 4, "article_id": 3, "company_id": 100, "was_helpful": False},
)


class _FakeUniqueViolation(Exception):
    """What supabase-py surfaces when a unique index rejects a write."""

    code = "23505"


class _FakeQuery:
    def __init__(self, store, table, log):
        self.store = store
        self.table = table
        self.log = log
        self.op = None
        self.payload = None
        self.selected = None
        self.filters = []
        self.orders = []
        self.limit_value = None

    def select(self, fields, **_kwargs):
        self.op = "select"
        self.selected = fields
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, list(values)))
        return self

    def order(self, field, desc=False):
        self.orders.append((field, desc))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def _matches(self, row):
        for kind, field, value in self.filters:
            if kind == "eq" and row.get(field) != value:
                return False
            if kind == "in" and row.get(field) not in value:
                return False
        return True

    def _rows(self):
        return [row for row in self.store.tables[self.table] if self._matches(row)]

    def _reject_duplicate_slug(self, slug, *, ignoring=None):
        for row in self.store.tables["help_articles"]:
            if row.get("slug") == slug and row.get("id") != ignoring:
                raise _FakeUniqueViolation("duplicate key value violates unique constraint")

    def execute(self):
        self.log.append((self.table, self.op))
        if self.op == "select":
            rows = self._rows()
            for field, desc in reversed(self.orders):
                rows = sorted(rows, key=lambda row: row.get(field), reverse=desc)
            if self.limit_value is not None:
                rows = rows[: self.limit_value]
            fields = [name for name in (self.selected or "").split(",") if name]
            return MagicMock(data=[{name: row.get(name) for name in fields} for row in rows])
        if self.op == "insert":
            row = dict(self.payload)
            if self.table == "help_articles":
                self._reject_duplicate_slug(row.get("slug"))
            row.setdefault("id", self.store.next_id(self.table))
            row.setdefault("created_at", "2026-09-05T00:00:00+00:00")
            row.setdefault("updated_at", "2026-09-05T00:00:00+00:00")
            self.store.tables[self.table].append(row)
            return MagicMock(data=[dict(row)])
        if self.op == "update":
            targets = self._rows()
            if self.table == "help_articles" and "slug" in self.payload:
                for target in targets:
                    self._reject_duplicate_slug(self.payload["slug"], ignoring=target.get("id"))
            for target in targets:
                target.update(self.payload)
            return MagicMock(data=[dict(row) for row in targets])
        if self.op == "delete":
            targets = self._rows()
            remaining = [row for row in self.store.tables[self.table] if row not in targets]
            self.store.tables[self.table] = remaining
            return MagicMock(data=[dict(row) for row in targets])
        raise AssertionError(f"Unsupported operation: {self.op}")


class _FakeSupabase:
    def __init__(self, articles=SAMPLE_ARTICLES, feedback=SAMPLE_FEEDBACK):
        self.tables = {
            "help_articles": [dict(row) for row in articles],
            "help_article_feedback": [dict(row) for row in feedback],
        }
        self.log = []

    def next_id(self, table):
        ids = [row.get("id") for row in self.tables[table] if isinstance(row.get("id"), int)]
        return (max(ids) + 1) if ids else 1

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"Unexpected table: {name}")
        return _FakeQuery(self, name, self.log)

    def tables_touched(self):
        return [table for table, _ in self.log]


class HelpArticleAdminRepositoryTests(unittest.TestCase):
    def _with(self, fake):
        return patch.object(help_article_repository, "supabase", fake)

    def test_admin_listing_includes_drafts_the_tenant_endpoint_hides(self):
        fake = _FakeSupabase()
        with self._with(fake):
            admin_rows = help_article_repository.list_all_help_articles()
            tenant_rows = help_article_repository.list_published_help_articles()
        self.assertIn("staff-draft", [row["slug"] for row in admin_rows])
        self.assertNotIn("staff-draft", [row["slug"] for row in tenant_rows])

    def test_admin_listing_projects_the_full_staff_field_set(self):
        fake = _FakeSupabase()
        with self._with(fake):
            rows = help_article_repository.list_all_help_articles()
        self.assertEqual(
            set(rows[0]),
            {
                "id", "category", "title", "body", "slug",
                "is_published", "sort_order", "created_at", "updated_at",
            },
        )

    def test_admin_listing_orders_by_sort_order_then_id(self):
        fake = _FakeSupabase()
        with self._with(fake):
            rows = help_article_repository.list_all_help_articles()
        self.assertEqual([row["id"] for row in rows], [3, 1, 2])

    def test_feedback_counts_are_tallied_in_one_query(self):
        fake = _FakeSupabase()
        with self._with(fake):
            counts = help_article_repository.count_help_article_feedback([1, 2, 3])
        self.assertEqual(fake.tables_touched(), ["help_article_feedback"])
        self.assertEqual(counts[1], {"helpful_count": 2, "unhelpful_count": 1})
        self.assertEqual(counts[2], {"helpful_count": 0, "unhelpful_count": 0})
        self.assertEqual(counts[3], {"helpful_count": 0, "unhelpful_count": 1})

    def test_feedback_counts_skip_the_query_entirely_when_there_are_no_articles(self):
        fake = _FakeSupabase()
        with self._with(fake):
            counts = help_article_repository.count_help_article_feedback([])
        self.assertEqual(counts, {})
        self.assertEqual(fake.log, [])

    def test_feedback_count_row_cap_is_bounded(self):
        fake = _FakeSupabase()
        with self._with(fake):
            help_article_repository.count_help_article_feedback([1])
        self.assertGreater(help_article_repository.MAX_FEEDBACK_ROWS, 0)

    def test_create_returns_the_inserted_row(self):
        fake = _FakeSupabase()
        with self._with(fake):
            row = help_article_repository.create_help_article(
                category="account", title="New", body="Body", slug="new-one",
                is_published=False, sort_order=7,
            )
        self.assertEqual(row["slug"], "new-one")
        self.assertEqual(row["sort_order"], 7)
        self.assertIn("id", row)

    def test_create_translates_a_unique_violation_into_a_slug_conflict(self):
        fake = _FakeSupabase()
        with self._with(fake), self.assertRaises(
            help_article_repository.HelpArticleSlugConflict
        ):
            help_article_repository.create_help_article(
                category="account", title="Clash", body="Body", slug="published-one",
                is_published=False, sort_order=0,
            )

    def test_create_rejects_an_unsupported_category_before_any_query(self):
        fake = _FakeSupabase()
        with self._with(fake), self.assertRaises(ValueError):
            help_article_repository.create_help_article(
                category="billing", title="X", body="Y", slug="x", is_published=True,
                sort_order=0,
            )
        self.assertEqual(fake.log, [])

    def test_update_stamps_updated_at(self):
        fake = _FakeSupabase()
        before = fake.tables["help_articles"][0]["updated_at"]
        with self._with(fake):
            row = help_article_repository.update_help_article(1, {"title": "Renamed"})
        self.assertEqual(row["title"], "Renamed")
        self.assertNotEqual(row["updated_at"], before)
        datetime.fromisoformat(row["updated_at"])

    def test_update_returns_none_when_the_article_does_not_exist(self):
        fake = _FakeSupabase()
        with self._with(fake):
            self.assertIsNone(help_article_repository.update_help_article(999, {"title": "X"}))

    def test_update_translates_a_unique_violation_into_a_slug_conflict(self):
        fake = _FakeSupabase()
        with self._with(fake), self.assertRaises(
            help_article_repository.HelpArticleSlugConflict
        ):
            help_article_repository.update_help_article(1, {"slug": "published-two"})

    def test_update_rejects_unsupported_fields_before_any_query(self):
        fake = _FakeSupabase()
        with self._with(fake), self.assertRaises(ValueError):
            help_article_repository.update_help_article(1, {"created_at": "now"})
        self.assertEqual(fake.log, [])

    def test_delete_removes_the_article_and_returns_it(self):
        fake = _FakeSupabase()
        with self._with(fake):
            row = help_article_repository.delete_help_article(1)
        self.assertEqual(row["id"], 1)
        self.assertNotIn(1, [item["id"] for item in fake.tables["help_articles"]])

    def test_delete_returns_none_when_the_article_does_not_exist(self):
        fake = _FakeSupabase()
        with self._with(fake):
            self.assertIsNone(help_article_repository.delete_help_article(999))

    def test_delete_never_touches_the_feedback_table_itself(self):
        # Orphan prevention is the FK's job, not this function's: migration 050
        # declares ON DELETE CASCADE, and service_role holds no DELETE grant on
        # help_article_feedback, so a hand-rolled cleanup would fail anyway.
        fake = _FakeSupabase()
        with self._with(fake):
            help_article_repository.delete_help_article(1)
        self.assertEqual(fake.tables_touched(), ["help_articles"])

    def test_migration_050_cascades_feedback_so_deletes_cannot_orphan(self):
        sql = re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8")).lower()
        self.assertIn(
            "article_id bigint not null references public.help_articles(id) on delete cascade",
            sql,
        )


class HelpArticleAdminServiceTests(unittest.TestCase):
    def _with(self, fake):
        return patch.object(help_article_repository, "supabase", fake)

    def _error(self, call):
        with self.assertRaises(admin_help.PlatformAdminServiceError) as caught:
            call()
        return caught.exception

    def test_listing_returns_the_pinned_field_set_with_counts(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.list_help_articles()
        self.assertEqual(set(result), {"articles"})
        self.assertEqual(
            set(result["articles"][0]),
            {
                "id", "category", "title", "body", "slug", "is_published",
                "sort_order", "created_at", "updated_at",
                "helpful_count", "unhelpful_count",
            },
        )

    def test_listing_reports_feedback_counts_per_article(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.list_help_articles()
        by_id = {row["id"]: row for row in result["articles"]}
        self.assertEqual((by_id[1]["helpful_count"], by_id[1]["unhelpful_count"]), (2, 1))
        self.assertEqual((by_id[2]["helpful_count"], by_id[2]["unhelpful_count"]), (0, 0))
        self.assertEqual((by_id[3]["helpful_count"], by_id[3]["unhelpful_count"]), (0, 1))

    def test_listing_includes_drafts(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.list_help_articles()
        states = {row["slug"]: row["is_published"] for row in result["articles"]}
        self.assertEqual(states["staff-draft"], False)

    def test_listing_issues_a_constant_number_of_queries(self):
        # The N+1 guard. Two queries for three articles, two for forty.
        small = _FakeSupabase()
        with self._with(small):
            admin_help.list_help_articles()
        many = _FakeSupabase(
            articles=tuple(_article(index) for index in range(1, 41)),
            feedback=tuple(
                {"id": index, "article_id": index, "company_id": 100, "was_helpful": True}
                for index in range(1, 41)
            ),
        )
        with self._with(many):
            result = admin_help.list_help_articles()
        self.assertEqual(len(result["articles"]), 40)
        self.assertEqual(len(small.log), 2)
        self.assertEqual(len(many.log), 2)

    def test_listing_surfaces_a_repository_failure_as_503(self):
        with patch.object(
            help_article_repository, "list_all_help_articles",
            side_effect=RuntimeError("postgrest: relation help_articles does not exist"),
        ):
            error = self._error(admin_help.list_help_articles)
        self.assertEqual(error.status_code, 503)
        self.assertEqual(error.code, "platform_admin_data_unavailable")
        self.assertNotIn("postgrest", error.message)

    def test_create_derives_the_slug_from_the_title(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.create_help_article({
                "category": "account", "title": "Reset Your  Password!", "body": "Body",
            })
        self.assertEqual(result["article"]["slug"], "reset-your-password")

    def test_create_uses_an_explicit_slug_when_one_is_supplied(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.create_help_article({
                "category": "account", "title": "Reset Your Password",
                "body": "Body", "slug": "password-reset",
            })
        self.assertEqual(result["article"]["slug"], "password-reset")

    def test_create_defaults_to_an_unpublished_draft_at_sort_order_zero(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.create_help_article({
                "category": "account", "title": "Draft", "body": "Body",
            })
        self.assertIs(result["article"]["is_published"], False)
        self.assertEqual(result["article"]["sort_order"], 0)

    def test_the_response_is_a_field_whitelist_not_the_raw_row(self):
        """A column added to help_articles later must not start leaking.

        _safe_article projects ARTICLE_FIELDS rather than deleting unwanted
        keys, so a column added tomorrow is absent by default instead of
        exposed by default. Added after a mutation audit found this was the one
        guard in the slice with no test behind it: swapping the projection for
        dict(row) broke nothing at all.
        """
        row = _article(9)
        row["internal_review_note"] = "staff only, never serialised"

        with patch.object(
            help_article_repository, "create_help_article", return_value=row
        ):
            result = admin_help.create_help_article({
                "category": "account", "title": "Whitelist", "body": "Body",
            })

        self.assertNotIn("internal_review_note", result["article"])
        self.assertEqual(
            set(result["article"]),
            set(admin_help.ARTICLE_FIELDS) | {"helpful_count", "unhelpful_count"},
        )

    def test_create_reports_zero_counts_for_a_brand_new_article(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.create_help_article({
                "category": "account", "title": "Draft", "body": "Body",
            })
        self.assertEqual(result["article"]["helpful_count"], 0)
        self.assertEqual(result["article"]["unhelpful_count"], 0)

    def test_create_rejects_a_colliding_slug_with_409_and_writes_nothing(self):
        fake = _FakeSupabase()
        with self._with(fake):
            error = self._error(lambda: admin_help.create_help_article({
                "category": "account", "title": "Clash", "body": "Body",
                "slug": "published-one",
            }))
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.code, "help_article_slug_exists")
        original = [row for row in fake.tables["help_articles"] if row["slug"] == "published-one"]
        self.assertEqual(len(original), 1)
        self.assertEqual(original[0]["title"], "Article 1")
        self.assertNotIn(("help_articles", "update"), fake.log)

    def test_create_rejects_a_title_that_derives_to_an_empty_slug(self):
        fake = _FakeSupabase()
        with self._with(fake):
            error = self._error(lambda: admin_help.create_help_article({
                "category": "account", "title": "!!! ???", "body": "Body",
            }))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "invalid_slug")
        self.assertEqual(fake.log, [])

    def test_create_rejects_a_slug_the_database_check_would_reject(self):
        for slug in ("Not-Lower", "trailing-", "-leading", "double--hyphen", "has space", ""):
            with self.subTest(slug=slug):
                fake = _FakeSupabase()
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article({
                        "category": "account", "title": "T", "body": "B", "slug": slug,
                    }))
                self.assertEqual(error.code, "invalid_slug")
                self.assertEqual(fake.log, [])

    def test_create_restricts_category_to_the_seven_support_values(self):
        fake = _FakeSupabase()
        for category in ("billing", "", "Technical", None, 1):
            with self.subTest(category=category):
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article({
                        "category": category, "title": "T", "body": "B",
                    }))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_category")
        self.assertEqual(fake.log, [])

    def test_create_accepts_every_supported_category(self):
        for index, category in enumerate(sorted(SUPPORTED_CATEGORIES)):
            with self.subTest(category=category):
                fake = _FakeSupabase()
                with self._with(fake):
                    result = admin_help.create_help_article({
                        "category": category, "title": f"T{index}", "body": "B",
                    })
                self.assertEqual(result["article"]["category"], category)

    def test_create_bounds_the_title_at_two_hundred_characters(self):
        fake = _FakeSupabase()
        with self._with(fake):
            ok = admin_help.create_help_article({
                "category": "account", "title": "a" * 200, "body": "B",
            })
            self.assertEqual(len(ok["article"]["title"]), 200)
            error = self._error(lambda: admin_help.create_help_article({
                "category": "account", "title": "b" * 201, "body": "B",
            }))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "invalid_title")

    def test_create_rejects_a_blank_or_non_text_title(self):
        fake = _FakeSupabase()
        for title in ("", "   ", None, 5, ["x"]):
            with self.subTest(title=title):
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article({
                        "category": "account", "title": title, "body": "B",
                    }))
                self.assertEqual(error.code, "invalid_title")

    def test_create_bounds_the_body_at_eight_thousand_characters(self):
        fake = _FakeSupabase()
        with self._with(fake):
            ok = admin_help.create_help_article({
                "category": "account", "title": "Long body", "body": "c" * 8000,
            })
            self.assertEqual(len(ok["article"]["body"]), 8000)
            error = self._error(lambda: admin_help.create_help_article({
                "category": "account", "title": "Too long", "body": "d" * 8001,
            }))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "invalid_body")

    def test_create_rejects_a_blank_or_non_text_body(self):
        fake = _FakeSupabase()
        for body in ("", "  ", None, 5):
            with self.subTest(body=body):
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article({
                        "category": "account", "title": "T", "body": body,
                    }))
                self.assertEqual(error.code, "invalid_body")

    def test_create_requires_category_title_and_body(self):
        for payload in (
            {"title": "T", "body": "B"},
            {"category": "account", "body": "B"},
            {"category": "account", "title": "T"},
        ):
            with self.subTest(payload=sorted(payload)):
                fake = _FakeSupabase()
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article(payload))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_request")

    def test_create_rejects_unsupported_fields_and_non_object_bodies(self):
        fake = _FakeSupabase()
        for payload in (
            {"category": "account", "title": "T", "body": "B", "id": 9},
            {"category": "account", "title": "T", "body": "B", "created_at": "now"},
            None,
            [],
            "text",
        ):
            with self.subTest(payload=payload):
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article(payload))
                self.assertEqual(error.code, "invalid_request")
        self.assertEqual(fake.log, [])

    def test_create_rejects_a_non_boolean_is_published(self):
        fake = _FakeSupabase()
        for value in ("true", 1, 0, None):
            with self.subTest(value=value):
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article({
                        "category": "account", "title": "T", "body": "B",
                        "is_published": value,
                    }))
                self.assertEqual(error.code, "invalid_is_published")

    def test_create_rejects_a_sort_order_the_column_cannot_hold(self):
        fake = _FakeSupabase()
        for value in (True, "10", 1.5, None, 2 ** 31, -(2 ** 31) - 1):
            with self.subTest(value=value):
                with self._with(fake):
                    error = self._error(lambda: admin_help.create_help_article({
                        "category": "account", "title": "T", "body": "B",
                        "sort_order": value,
                    }))
                self.assertEqual(error.code, "invalid_sort_order")

    def test_update_applies_only_the_supplied_fields(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.update_help_article(1, {"is_published": False})
        self.assertIs(result["article"]["is_published"], False)
        self.assertEqual(result["article"]["title"], "Article 1")
        self.assertEqual(result["article"]["slug"], "published-one")

    def test_update_does_not_re_derive_the_slug_when_the_title_changes(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.update_help_article(1, {"title": "A Completely New Title"})
        self.assertEqual(result["article"]["slug"], "published-one")

    def test_update_reports_current_feedback_counts(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.update_help_article(1, {"sort_order": 99})
        self.assertEqual(result["article"]["helpful_count"], 2)
        self.assertEqual(result["article"]["unhelpful_count"], 1)

    def test_update_rejects_an_empty_change_set(self):
        fake = _FakeSupabase()
        with self._with(fake):
            error = self._error(lambda: admin_help.update_help_article(1, {}))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "no_change")
        self.assertEqual(fake.log, [])

    def test_update_returns_404_for_an_unknown_article(self):
        fake = _FakeSupabase()
        with self._with(fake):
            error = self._error(lambda: admin_help.update_help_article(999, {"title": "X"}))
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.code, "help_article_not_found")

    def test_update_rejects_a_colliding_slug_with_409_without_overwriting(self):
        fake = _FakeSupabase()
        with self._with(fake):
            error = self._error(
                lambda: admin_help.update_help_article(1, {"slug": "published-two"})
            )
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.code, "help_article_slug_exists")
        slugs = sorted(row["slug"] for row in fake.tables["help_articles"])
        self.assertEqual(slugs, ["published-one", "published-two", "staff-draft"])

    def test_update_enforces_the_same_bounds_as_create(self):
        cases = (
            ({"title": "a" * 201}, "invalid_title"),
            ({"title": "  "}, "invalid_title"),
            ({"body": "b" * 8001}, "invalid_body"),
            ({"category": "billing"}, "invalid_category"),
            ({"slug": "Bad Slug"}, "invalid_slug"),
            ({"is_published": "yes"}, "invalid_is_published"),
            ({"sort_order": 2 ** 31}, "invalid_sort_order"),
        )
        for payload, code in cases:
            with self.subTest(payload=payload):
                fake = _FakeSupabase()
                with self._with(fake):
                    error = self._error(lambda: admin_help.update_help_article(1, payload))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, code)
                self.assertEqual(fake.log, [])

    def test_update_rejects_unsupported_fields_and_non_object_bodies(self):
        fake = _FakeSupabase()
        for payload in ({"created_at": "now"}, {"id": 4}, None, [], "text"):
            with self.subTest(payload=payload):
                with self._with(fake):
                    error = self._error(lambda: admin_help.update_help_article(1, payload))
                self.assertEqual(error.code, "invalid_request")
        self.assertEqual(fake.log, [])

    def test_delete_removes_the_article(self):
        fake = _FakeSupabase()
        with self._with(fake):
            result = admin_help.delete_help_article(1)
        self.assertEqual(result, {"article_id": 1, "deleted": True})
        self.assertNotIn(1, [row["id"] for row in fake.tables["help_articles"]])

    def test_delete_returns_404_for_an_unknown_article(self):
        fake = _FakeSupabase()
        with self._with(fake):
            error = self._error(lambda: admin_help.delete_help_article(999))
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.code, "help_article_not_found")

    def test_delete_leaves_feedback_cleanup_to_the_foreign_key(self):
        fake = _FakeSupabase()
        with self._with(fake):
            admin_help.delete_help_article(1)
        self.assertEqual(fake.tables_touched(), ["help_articles"])

    def test_invalid_article_ids_are_refused_before_any_query(self):
        fake = _FakeSupabase()
        for article_id in (0, -1, True, "1", None):
            with self.subTest(article_id=article_id):
                with self._with(fake):
                    error = self._error(lambda: admin_help.delete_help_article(article_id))
                self.assertEqual(error.code, "invalid_article_id")
        self.assertEqual(fake.log, [])


class _PlatformAdminRouteHarness(unittest.TestCase):
    """Blueprint under test with the platform-admin guard satisfied."""

    is_platform_admin = True

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer token"}
        mapping = {"platform_role": "super_admin", "modules": {"billing": True, "support": True, "customers": True}, "id": 3, "user_id": 7, "is_active": True} if self.is_platform_admin else None
        self.patches = [
            patch("app.decorators.auth_decorator.get_jwt_secret", return_value="secret"),
            patch("app.decorators.auth_decorator.jwt.decode", return_value={
                "user_id": 7, "company_id": 100, "role": "owner",
            }),
            patch("app.database.user_repository.get_user_by_id", return_value={
                "id": 7, "company_id": 100, "email": "owner@tenant.test",
                "status": "active", "role": "owner",
            }),
            patch(
                "app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                return_value=mapping,
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)


class HelpArticleAdminRouteTests(_PlatformAdminRouteHarness):
    def test_routes_are_registered_with_the_pinned_methods(self):
        methods = {}
        for rule in self.app.url_map.iter_rules():
            if rule.rule.startswith("/api/platform-admin/help"):
                methods.setdefault(rule.rule, set()).update(
                    rule.methods - {"HEAD", "OPTIONS"}
                )
        self.assertEqual(methods, {
            "/api/platform-admin/help/articles": {"GET", "POST"},
            "/api/platform-admin/help/articles/<int:article_id>": {"PATCH", "DELETE"},
        })

    def test_routes_exist_on_the_real_application(self):
        from app import create_app

        rules = {rule.rule for rule in create_app().url_map.iter_rules()}
        self.assertIn("/api/platform-admin/help/articles", rules)
        self.assertIn("/api/platform-admin/help/articles/<int:article_id>", rules)

    def test_list_success_envelope_matches_the_pinned_contract(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.get(
                "/api/platform-admin/help/articles", headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {"status", "data"})
        self.assertEqual(response.json["status"], "success")
        self.assertEqual(set(response.json["data"]), {"articles"})
        self.assertEqual(
            set(response.json["data"]["articles"][0]),
            {
                "id", "category", "title", "body", "slug", "is_published",
                "sort_order", "created_at", "updated_at",
                "helpful_count", "unhelpful_count",
            },
        )

    def test_list_shows_drafts_unlike_the_tenant_endpoint(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            admin = self.client.get(
                "/api/platform-admin/help/articles", headers=self.headers
            )
        admin_slugs = {row["slug"] for row in admin.json["data"]["articles"]}
        self.assertIn("staff-draft", admin_slugs)

        tenant_app = Flask(__name__)
        tenant_app.config["TESTING"] = True
        from app.routes.help_routes import help_bp

        tenant_app.register_blueprint(help_bp)
        with patch.object(help_article_repository, "supabase", _FakeSupabase()):
            tenant = tenant_app.test_client().get(
                "/api/help/articles", headers=self.headers
            )
        tenant_slugs = {row["slug"] for row in tenant.json["data"]["articles"]}
        self.assertNotIn("staff-draft", tenant_slugs)

    def test_create_returns_the_created_article(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.post(
                "/api/platform-admin/help/articles",
                headers=self.headers,
                json={"category": "account", "title": "Brand New", "body": "Body"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["article"]["slug"], "brand-new")

    def test_slug_collision_is_a_409_with_a_stable_code(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.post(
                "/api/platform-admin/help/articles",
                headers=self.headers,
                json={
                    "category": "account", "title": "Clash", "body": "Body",
                    "slug": "published-one",
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json, {
            "status": "error",
            "code": "help_article_slug_exists",
            "message": response.json["message"],
        })
        self.assertEqual(response.json["code"], "help_article_slug_exists")

    def test_validation_failures_use_the_platform_admin_error_envelope(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.post(
                "/api/platform-admin/help/articles",
                headers=self.headers,
                json={"category": "billing", "title": "T", "body": "B"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json), {"status", "code", "message"})
        self.assertEqual(response.json["status"], "error")
        self.assertEqual(response.json["code"], "invalid_category")

    def test_patch_updates_an_article(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.patch(
                "/api/platform-admin/help/articles/1",
                headers=self.headers,
                json={"is_published": False},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json["data"]["article"]["is_published"], False)

    def test_patch_of_an_unknown_article_is_404(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.patch(
                "/api/platform-admin/help/articles/999",
                headers=self.headers,
                json={"title": "X"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["code"], "help_article_not_found")

    def test_delete_removes_an_article(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.delete(
                "/api/platform-admin/help/articles/1", headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"], {"article_id": 1, "deleted": True})

    def test_delete_of_an_unknown_article_is_404(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.delete(
                "/api/platform-admin/help/articles/999", headers=self.headers
            )
        self.assertEqual(response.status_code, 404)

    def test_unexpected_repository_failure_becomes_503_without_leaking(self):
        with patch.object(
            help_article_repository, "list_all_help_articles",
            side_effect=RuntimeError("postgrest: column help_articles.body does not exist"),
        ):
            response = self.client.get(
                "/api/platform-admin/help/articles", headers=self.headers
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "platform_admin_data_unavailable")
        self.assertNotIn("postgrest", response.get_data(as_text=True))


class HelpArticleTenantDenialTests(_PlatformAdminRouteHarness):
    """A tenant owner is authenticated but is not a platform admin."""

    is_platform_admin = False

    def _requests(self):
        return (
            ("GET", "/api/platform-admin/help/articles", None),
            ("POST", "/api/platform-admin/help/articles",
             {"category": "account", "title": "T", "body": "B"}),
            ("PATCH", "/api/platform-admin/help/articles/1", {"title": "T"}),
            ("DELETE", "/api/platform-admin/help/articles/1", None),
        )

    def test_tenant_owner_is_denied_on_every_verb(self):
        for method, path, payload in self._requests():
            with self.subTest(method=method):
                response = self.client.open(
                    path, method=method, headers=self.headers, json=payload
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json["status"], "error")
                self.assertEqual(response.json["code"], "platform_admin_access_denied")

    def test_denied_requests_never_reach_the_database(self):
        fake = _FakeSupabase()
        with patch.object(help_article_repository, "supabase", fake):
            for method, path, payload in self._requests():
                self.client.open(path, method=method, headers=self.headers, json=payload)
        self.assertEqual(fake.log, [])


class HelpArticleUnauthenticatedTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(platform_admin_bp)
        self.client = self.app.test_client()

    def test_every_help_article_route_requires_a_token(self):
        for method, path in (
            ("GET", "/api/platform-admin/help/articles"),
            ("POST", "/api/platform-admin/help/articles"),
            ("PATCH", "/api/platform-admin/help/articles/1"),
            ("DELETE", "/api/platform-admin/help/articles/1"),
        ):
            with self.subTest(method=method):
                self.assertEqual(self.client.open(path, method=method).status_code, 401)


if __name__ == "__main__":
    unittest.main()
