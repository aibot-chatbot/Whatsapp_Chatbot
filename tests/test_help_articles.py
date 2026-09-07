"""Help article read path - migration 050, repository, service and route.

Slice 1 of the support redesign. The contract under test is
docs/sdlc/03-design.md section 5 and docs/sdlc/02-analysis.md section 3.
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
ROLLBACK = ROOT / "data" / "050_help_articles_rollback.sql"

SUPPORTED_CATEGORIES = {
    "technical",
    "account",
    "chatbot",
    "integration",
    "billing_question",
    "ai_credits",
    "other",
}

# One published row per shape the reader cares about, plus a draft that must
# never reach a tenant.
SAMPLE_ROWS = (
    {
        "id": 3,
        "category": "integration",
        "title": "Connect a WhatsApp number",
        "body": "Open Integrations.",
        "slug": "connect-a-whatsapp-number",
        "is_published": True,
        "sort_order": 20,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    },
    {
        "id": 1,
        "category": "chatbot",
        "title": "Create your first chatbot",
        "body": "Open My Bots.",
        "slug": "create-your-first-chatbot",
        "is_published": True,
        "sort_order": 10,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    },
    {
        "id": 2,
        "category": "chatbot",
        "title": "Second article at the same sort order",
        "body": "Ties break on id.",
        "slug": "second-article-at-the-same-sort-order",
        "is_published": True,
        "sort_order": 10,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    },
    {
        "id": 4,
        "category": "billing_question",
        "title": "Unpublished draft",
        "body": "Staff have not released this yet.",
        "slug": "unpublished-draft",
        "is_published": False,
        "sort_order": 5,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    },
)


class _FakeQuery:
    """A postgrest query builder that actually filters, so exclusion is proved."""

    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]
        self.selected = None
        self.filters = []
        self.orders = []
        self.limit_value = None

    def select(self, fields):
        self.selected = fields
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        self.rows = [row for row in self.rows if row.get(field) == value]
        return self

    def order(self, field, desc=False):
        self.orders.append((field, desc))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        rows = list(self.rows)
        # Later sorts are less significant, so apply them first: a stable sort
        # chain leaves the first .order() call dominant, as postgrest does.
        for field, desc in reversed(self.orders):
            rows = sorted(rows, key=lambda row: row.get(field), reverse=desc)
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        fields = [name for name in (self.selected or "").split(",") if name]
        return MagicMock(data=[{name: row.get(name) for name in fields} for row in rows])


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.table_name = None
        self.last_query = None

    def table(self, name):
        self.table_name = name
        self.last_query = _FakeQuery(self._rows)
        return self.last_query


class HelpArticlesMigrationTest(unittest.TestCase):
    @staticmethod
    def _statements(text):
        """The SQL with its comment header lines dropped, whitespace collapsed."""
        body = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("--")
        )
        return re.sub(r"\s+", " ", body).strip().lower()

    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"\s+", " ", cls.sql).lower()
        cls.statements = cls._statements(cls.sql)
        cls.rollback_text = ROLLBACK.read_text(encoding="utf-8")
        cls.rollback = re.sub(r"\s+", " ", cls.rollback_text).lower()
        cls.rollback_statements = cls._statements(cls.rollback_text)

    def test_migration_is_transactional(self):
        self.assertTrue(self.statements.startswith("begin;"))
        self.assertTrue(self.statements.endswith("commit;"))

    def test_creates_both_help_tables(self):
        for table in ("help_articles", "help_article_feedback"):
            with self.subTest(table=table):
                self.assertIn(
                    f"create table if not exists public.{table}", self.normalized
                )

    def test_article_columns_match_the_domain_model(self):
        for column in (
            "category text not null",
            "title text not null",
            "body text not null",
            "slug text not null",
            "is_published boolean not null default false",
            "sort_order integer not null default 0",
            "created_at timestamptz not null default now()",
            "updated_at timestamptz not null default now()",
        ):
            with self.subTest(column=column):
                self.assertIn(column, self.normalized)

    def test_category_check_allows_only_the_seven_support_categories(self):
        match = re.search(
            r"help_articles_category_check check \( category in \(([^)]*)\)",
            self.normalized,
        )
        self.assertIsNotNone(match)
        found = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        self.assertEqual(found, SUPPORTED_CATEGORIES)

    def test_slug_is_unique_and_feedback_is_one_vote_per_tenant(self):
        self.assertIn("unique index if not exists help_articles_slug_idx", self.normalized)
        self.assertIn("on public.help_articles(slug)", self.normalized)
        self.assertIn(
            "on public.help_article_feedback(article_id, company_id)", self.normalized
        )

    def test_feedback_is_tenant_scoped_and_cascades(self):
        self.assertIn(
            "article_id bigint not null references public.help_articles(id) on delete cascade",
            self.normalized,
        )
        self.assertIn(
            "company_id bigint not null references public.companies(id) on delete cascade",
            self.normalized,
        )

    def test_tables_are_locked_down_to_service_role(self):
        for table in ("help_articles", "help_article_feedback"):
            with self.subTest(table=table):
                self.assertIn(
                    f"alter table public.{table} enable row level security",
                    self.normalized,
                )
                self.assertIn(
                    f"revoke all privileges on table public.{table} "
                    "from public, anon, authenticated",
                    self.normalized,
                )
                self.assertIn(f"on table public.{table} to service_role", self.normalized)
                self.assertIn(
                    f"grant usage, select on sequence public.{table}_id_seq to service_role",
                    self.normalized,
                )

    def test_each_table_is_documented(self):
        for table in ("help_articles", "help_article_feedback"):
            with self.subTest(table=table):
                self.assertIn(f"comment on table public.{table} is", self.normalized)

    def _seeded_categories(self):
        return re.findall(r"^\s*\('([a-z_]+)',", self.sql, re.MULTILINE)

    def test_seeds_between_fifteen_and_twenty_articles(self):
        seeded = self._seeded_categories()
        self.assertGreaterEqual(len(seeded), 15)
        self.assertLessEqual(len(seeded), 20)

    def test_seeded_categories_are_all_supported(self):
        self.assertTrue(set(self._seeded_categories()).issubset(SUPPORTED_CATEGORIES))

    def test_seed_covers_every_topic_card_category(self):
        # The seven hardcoded topic cards must all have somewhere to land.
        self.assertEqual(set(self._seeded_categories()), SUPPORTED_CATEGORIES)

    def test_seed_is_rerunnable(self):
        self.assertIn("on conflict (slug) do nothing", self.normalized)

    def test_seed_slugs_are_unique(self):
        slugs = re.findall(r"^\s*'([a-z0-9-]+)',\s*$", self.sql, re.MULTILINE)
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_rollback_drops_both_tables_transactionally(self):
        self.assertTrue(self.rollback_statements.startswith("begin;"))
        self.assertTrue(self.rollback_statements.endswith("commit;"))
        self.assertIn("drop table if exists public.help_article_feedback", self.rollback)
        self.assertIn("drop table if exists public.help_articles", self.rollback)


class HelpArticleRepositoryTests(unittest.TestCase):
    def _list(self, rows=SAMPLE_ROWS, **kwargs):
        fake = _FakeSupabase(rows)
        with patch.object(help_article_repository, "supabase", fake):
            return help_article_repository.list_published_help_articles(**kwargs), fake

    def test_reads_the_help_articles_table_only(self):
        _, fake = self._list()
        self.assertEqual(fake.table_name, "help_articles")

    def test_unpublished_articles_are_excluded(self):
        rows, fake = self._list()
        self.assertIn(("is_published", True), fake.last_query.filters)
        self.assertNotIn("unpublished-draft", [row["slug"] for row in rows])
        self.assertEqual(len(rows), 3)

    def test_articles_are_ordered_by_sort_order_then_id(self):
        rows, _ = self._list()
        self.assertEqual(
            [row["id"] for row in rows],
            [1, 2, 3],
        )

    def test_selected_fields_never_include_publication_or_audit_state(self):
        rows, _ = self._list()
        self.assertEqual(
            set(rows[0]),
            {"id", "category", "title", "body", "slug", "sort_order"},
        )

    def test_category_filter_is_applied_when_supplied(self):
        rows, fake = self._list(category="integration")
        self.assertIn(("category", "integration"), fake.last_query.filters)
        self.assertEqual([row["slug"] for row in rows], ["connect-a-whatsapp-number"])

    def test_unsupported_category_is_rejected_before_any_query(self):
        fake = _FakeSupabase(SAMPLE_ROWS)
        with patch.object(help_article_repository, "supabase", fake):
            with self.assertRaises(ValueError):
                help_article_repository.list_published_help_articles(
                    category="billing"
                )
        self.assertIsNone(fake.last_query)

    def test_invalid_limit_is_rejected_before_any_query(self):
        for limit in (0, -1, True, None, "25", 1.5, 10**6):
            with self.subTest(limit=limit):
                fake = _FakeSupabase(SAMPLE_ROWS)
                with patch.object(help_article_repository, "supabase", fake):
                    with self.assertRaises(ValueError):
                        help_article_repository.list_published_help_articles(limit=limit)
                self.assertIsNone(fake.last_query)

    def test_limit_is_pushed_into_the_query(self):
        rows, fake = self._list(limit=1)
        self.assertEqual(fake.last_query.limit_value, 1)
        self.assertEqual(len(rows), 1)

    def test_missing_data_returns_an_empty_list(self):
        supabase = MagicMock()
        supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=None)
        )
        with patch.object(help_article_repository, "supabase", supabase):
            self.assertEqual(help_article_repository.list_published_help_articles(), [])


class HelpArticleServiceTests(unittest.TestCase):
    def test_serialises_only_the_contract_fields(self):
        leaky_row = {
            "id": 1,
            "category": "chatbot",
            "title": "Create your first chatbot",
            "body": "Open My Bots.",
            "slug": "create-your-first-chatbot",
            "sort_order": 10,
            "is_published": True,
            "company_id": 100,
            "created_at": "2026-09-01T00:00:00Z",
        }
        with patch.object(
            help_article_service.help_article_repository,
            "list_published_help_articles",
            return_value=[leaky_row],
        ):
            result = help_article_service.list_published_articles()
        self.assertEqual(
            result,
            {
                "articles": [
                    {
                        "id": 1,
                        "category": "chatbot",
                        "title": "Create your first chatbot",
                        "body": "Open My Bots.",
                        "slug": "create-your-first-chatbot",
                        "sort_order": 10,
                    }
                ]
            },
        )

    def test_non_dict_rows_do_not_crash_the_reader(self):
        with patch.object(
            help_article_service.help_article_repository,
            "list_published_help_articles",
            return_value=[None],
        ):
            result = help_article_service.list_published_articles()
        self.assertEqual(result["articles"][0]["id"], None)

    def test_repository_failure_becomes_a_500_without_leaking(self):
        with patch.object(
            help_article_service.help_article_repository,
            "list_published_help_articles",
            side_effect=RuntimeError("postgrest: relation help_articles does not exist"),
        ):
            with self.assertRaises(help_article_service.HelpArticleServiceError) as ctx:
                help_article_service.list_published_articles()
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.message, "Unable to load help articles.")
        self.assertNotIn("postgrest", ctx.exception.message)


class HelpArticleRouteTests(unittest.TestCase):
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

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get("/api/help/articles")
        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_request_does_not_reach_the_repository(self):
        with patch.object(
            help_article_service.help_article_repository,
            "list_published_help_articles",
        ) as reader:
            self.client.get("/api/help/articles")
        reader.assert_not_called()

    def test_success_envelope_matches_the_design_contract(self):
        fake = _FakeSupabase(SAMPLE_ROWS)
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.get("/api/help/articles", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {"status", "data"})
        self.assertEqual(response.json["status"], "success")
        self.assertEqual(set(response.json["data"]), {"articles"})
        self.assertEqual(
            response.json["data"]["articles"][0],
            {
                "id": 1,
                "category": "chatbot",
                "title": "Create your first chatbot",
                "body": "Open My Bots.",
                "slug": "create-your-first-chatbot",
                "sort_order": 10,
            },
        )

    def test_unpublished_articles_never_reach_the_response(self):
        fake = _FakeSupabase(SAMPLE_ROWS)
        with patch.object(help_article_repository, "supabase", fake):
            response = self.client.get("/api/help/articles", headers=self.headers)
        body = response.get_data(as_text=True)
        self.assertNotIn("unpublished-draft", body)
        self.assertNotIn("is_published", body)
        self.assertEqual(len(response.json["data"]["articles"]), 3)

    def test_repository_failure_returns_500_without_leaking_the_exception(self):
        with patch.object(
            help_article_service.help_article_repository,
            "list_published_help_articles",
            side_effect=RuntimeError("postgrest: relation help_articles does not exist"),
        ):
            response = self.client.get("/api/help/articles", headers=self.headers)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json,
            {"status": "error", "message": "Unable to load help articles."},
        )
        self.assertNotIn("postgrest", response.get_data(as_text=True))

    def test_blueprint_is_registered_on_the_real_app(self):
        from app import create_app

        rules = {rule.rule for rule in create_app().url_map.iter_rules()}
        self.assertIn("/api/help/articles", rules)


if __name__ == "__main__":
    unittest.main()
