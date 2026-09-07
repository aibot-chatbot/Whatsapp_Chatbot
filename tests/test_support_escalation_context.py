"""Slice 3 - escalation trail, urgency and source on a support request.

Contract: docs/sdlc/01-requirements.md FR-3 and FR-4, docs/sdlc/02-analysis.md
section 3. User-authored searches follow the description's sensitive-content
policy; published article titles remain usable even when discussing tokens.
"""

import json
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

from app.database import tenant_support_repository
from app.rate_limit import init_limiter
from app.routes.support_routes import support_bp
from app.services import tenant_support_service


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "data" / "052_support_escalation_context.sql"
ROLLBACK = ROOT / "data" / "052_support_escalation_context_rollback.sql"

VALID_BASE = {
    "category": "technical",
    "title": "Cannot connect a number",
    "redacted_description": "The connect button does nothing on my account.",
}


def _payload(**extra):
    payload = dict(VALID_BASE)
    payload.update(extra)
    return payload


class EscalationMigrationTest(unittest.TestCase):
    @staticmethod
    def _statements(text):
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

    def test_migration_and_rollback_are_transactional(self):
        for statements in (self.statements, self.rollback_statements):
            self.assertTrue(statements.startswith("begin;"))
            self.assertTrue(statements.endswith("commit;"))

    def test_adds_a_nullable_jsonb_escalation_context_column(self):
        self.assertIn(
            "add column if not exists escalation_context jsonb", self.normalized
        )
        self.assertNotIn("escalation_context jsonb not null", self.normalized)

    def test_escalation_context_is_bounded_in_the_database_too(self):
        self.assertIn(
            "tenant_support_requests_escalation_context_check", self.normalized
        )
        self.assertIn("jsonb_typeof(escalation_context) = 'object'", self.normalized)
        self.assertIn(
            str(tenant_support_service.MAX_ESCALATION_CONTEXT_BYTES), self.normalized
        )

    def test_priority_check_is_widened_to_the_three_urgency_levels(self):
        match = re.search(
            r"tenant_support_requests_priority_check\s+check\s*\(\s*priority in \(([^)]*)\)",
            self.normalized,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            set(re.findall(r"'([a-z_]+)'", match.group(1))),
            set(tenant_support_service.ALLOWED_PRIORITIES),
        )

    def test_source_check_keeps_the_legacy_value_and_adds_the_two_new_ones(self):
        match = re.search(
            r"tenant_support_requests_source_check\s+check\s*\(\s*source in \(([^)]*)\)",
            self.normalized,
        )
        self.assertIsNotNone(match)
        found = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        # 'tenant' is what every existing row holds; dropping it would make the
        # constraint invalid against live data.
        self.assertEqual(
            found, set(tenant_support_service.ALLOWED_SOURCES) | {"tenant"}
        )

    def test_the_rpc_is_replaced_rather_than_overloaded(self):
        # Two functions of the same name would make every postgrest call
        # ambiguous, so the five-argument version must be dropped first.
        drop_at = self.normalized.find("drop function if exists public.create_tenant_support_request")
        create_at = self.normalized.find("create or replace function public.create_tenant_support_request")
        self.assertNotEqual(drop_at, -1)
        self.assertNotEqual(create_at, -1)
        self.assertLess(drop_at, create_at)

    def test_the_new_rpc_parameters_default_so_an_old_deploy_still_works(self):
        for parameter in (
            "p_priority text default 'normal'",
            "p_source text default 'direct'",
            "p_escalation_context jsonb default null",
        ):
            with self.subTest(parameter=parameter):
                self.assertIn(parameter, self.normalized)

    def test_the_rpc_writes_the_three_new_values(self):
        self.assertIn("p_escalation_context", self.normalized)
        self.assertIn("escalation_context", self.normalized)
        self.assertIn("grant execute on function public.create_tenant_support_request", self.normalized)

    def test_rollback_removes_the_column_and_restores_the_old_rpc(self):
        self.assertIn("drop column if exists escalation_context", self.rollback)
        self.assertIn(
            "create or replace function public.create_tenant_support_request",
            self.rollback,
        )
        self.assertIn("check (priority = 'normal')", self.rollback)
        self.assertIn("check (source = 'tenant')", self.rollback)


class EscalationContextValidationTests(unittest.TestCase):
    """Pure validation, no database: the service is the only guard that matters."""

    def _submit(self, payload, rpc=None):
        target = rpc if rpc is not None else MagicMock(return_value=31)
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            target,
        ), patch.object(tenant_support_service, "_notify_platform_support"):
            try:
                result = tenant_support_service.submit_tenant_support_request(
                    payload, company_id=100, requester_user_id=7
                )
            except tenant_support_service.TenantSupportServiceError as exc:
                return exc, target
            return result, target

    def _kwargs(self, payload):
        result, rpc = self._submit(payload)
        self.assertNotIsInstance(result, tenant_support_service.TenantSupportServiceError)
        return rpc.call_args.kwargs

    # --- defaults ---------------------------------------------------------

    def test_priority_defaults_to_normal_when_absent(self):
        self.assertEqual(self._kwargs(_payload())["priority"], "normal")

    def test_source_defaults_to_direct_when_absent(self):
        self.assertEqual(self._kwargs(_payload())["source"], "direct")

    def test_escalation_context_defaults_to_none_when_absent(self):
        self.assertIsNone(self._kwargs(_payload())["escalation_context"])

    # --- enums ------------------------------------------------------------

    def test_every_allowed_priority_is_accepted(self):
        for priority in ("low", "normal", "urgent"):
            with self.subTest(priority=priority):
                self.assertEqual(
                    self._kwargs(_payload(priority=priority))["priority"], priority
                )

    def test_an_explicit_null_means_not_supplied_for_every_optional_field(self):
        """A page that always sends the key gets the default, not a 400."""
        kwargs = self._kwargs(
            _payload(priority=None, source=None, escalation_context=None)
        )
        self.assertEqual(kwargs["priority"], "normal")
        self.assertEqual(kwargs["source"], "direct")
        self.assertIsNone(kwargs["escalation_context"])

    def test_unknown_priority_is_rejected(self):
        for priority in ("high", "URGENT", "", " ", 1, True, ["low"]):
            with self.subTest(priority=priority):
                error, rpc = self._submit(_payload(priority=priority))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_priority")
                rpc.assert_not_called()

    def test_every_allowed_source_is_accepted(self):
        for source in ("faq_dead_end", "direct"):
            with self.subTest(source=source):
                self.assertEqual(self._kwargs(_payload(source=source))["source"], source)

    def test_unknown_source_is_rejected(self):
        # 'tenant' is the legacy column value; a browser may not claim it.
        for source in ("tenant", "faq", "FAQ_DEAD_END", "", 3, True):
            with self.subTest(source=source):
                error, rpc = self._submit(_payload(source=source))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_source")
                rpc.assert_not_called()

    # --- escalation_context shape ----------------------------------------

    def test_a_full_valid_trail_is_passed_through_intact(self):
        context = {
            "searches": ["whatsapp number", "qr code"],
            "viewed": ["Connect a WhatsApp number"],
            "unhelpful": ["Choose an AI provider and model"],
            "from_page": "support.html",
        }
        self.assertEqual(
            self._kwargs(_payload(escalation_context=context))["escalation_context"],
            context,
        )

    def test_unknown_escalation_context_keys_are_rejected(self):
        for key in ("company_id", "user_id", "notes", "Searches", "from_Page"):
            with self.subTest(key=key):
                error, rpc = self._submit(
                    _payload(escalation_context={"from_page": "support.html", key: "x"})
                )
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_escalation_context")
                rpc.assert_not_called()

    def test_escalation_context_must_be_an_object(self):
        for value in ([], "searches", 1, True, ["a"]):
            with self.subTest(value=value):
                error, rpc = self._submit(_payload(escalation_context=value))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_escalation_context")
                rpc.assert_not_called()

    def test_explicit_null_escalation_context_is_accepted_as_absent(self):
        self.assertIsNone(
            self._kwargs(_payload(escalation_context=None))["escalation_context"]
        )

    def test_an_empty_trail_is_stored_as_null_rather_than_an_empty_object(self):
        for value in ({}, {"searches": []}, {"from_page": "   "}):
            with self.subTest(value=value):
                self.assertIsNone(
                    self._kwargs(_payload(escalation_context=value))[
                        "escalation_context"
                    ]
                )

    def test_trail_arrays_must_be_lists_of_strings(self):
        for context in (
            {"searches": "whatsapp"},
            {"viewed": {"0": "a"}},
            {"unhelpful": [1]},
            {"searches": [None]},
            {"viewed": [["nested"]]},
            {"searches": [True]},
        ):
            with self.subTest(context=context):
                error, rpc = self._submit(_payload(escalation_context=context))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_escalation_context")
                rpc.assert_not_called()

    def test_from_page_must_be_a_string(self):
        for value in (1, True, ["support.html"], {"page": "support.html"}):
            with self.subTest(value=value):
                error, rpc = self._submit(
                    _payload(escalation_context={"from_page": value})
                )
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_escalation_context")
                rpc.assert_not_called()

    # --- escalation_context bounds ---------------------------------------

    def test_array_length_is_capped_at_ten_items(self):
        limit = tenant_support_service.MAX_ESCALATION_ITEMS
        for key in ("searches", "viewed", "unhelpful"):
            with self.subTest(key=key):
                at_limit = {key: [f"term {index}" for index in range(limit)]}
                self.assertEqual(
                    len(
                        self._kwargs(_payload(escalation_context=at_limit))[
                            "escalation_context"
                        ][key]
                    ),
                    limit,
                )
                over = {key: [f"term {index}" for index in range(limit + 1)]}
                error, rpc = self._submit(_payload(escalation_context=over))
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_escalation_context")
                rpc.assert_not_called()

    def test_item_length_is_capped_at_two_hundred_characters(self):
        limit = tenant_support_service.MAX_ESCALATION_ITEM_LENGTH
        for key in ("searches", "viewed", "unhelpful"):
            with self.subTest(key=key):
                self.assertEqual(
                    self._kwargs(_payload(escalation_context={key: ["x" * limit]}))[
                        "escalation_context"
                    ][key],
                    ["x" * limit],
                )
                error, rpc = self._submit(
                    _payload(escalation_context={key: ["x" * (limit + 1)]})
                )
                self.assertEqual(error.status_code, 400)
                self.assertEqual(error.code, "invalid_escalation_context")
                rpc.assert_not_called()

    def test_from_page_length_is_capped_at_sixty_four_characters(self):
        limit = tenant_support_service.MAX_ESCALATION_FROM_PAGE_LENGTH
        self.assertEqual(
            self._kwargs(_payload(escalation_context={"from_page": "p" * limit}))[
                "escalation_context"
            ]["from_page"],
            "p" * limit,
        )
        error, rpc = self._submit(
            _payload(escalation_context={"from_page": "p" * (limit + 1)})
        )
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "invalid_escalation_context")
        rpc.assert_not_called()

    def test_total_serialised_size_is_capped_even_when_every_item_fits(self):
        items = tenant_support_service.MAX_ESCALATION_ITEMS
        length = tenant_support_service.MAX_ESCALATION_ITEM_LENGTH
        oversized = {
            key: ["x" * length for _ in range(items)]
            for key in ("searches", "viewed", "unhelpful")
        }
        # Every individual bound is satisfied; only the total is not.
        self.assertGreater(
            len(json.dumps(oversized)),
            tenant_support_service.MAX_ESCALATION_CONTEXT_BYTES,
        )
        error, rpc = self._submit(_payload(escalation_context=oversized))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "invalid_escalation_context")
        rpc.assert_not_called()

    def test_a_trail_just_under_the_total_cap_is_accepted(self):
        length = tenant_support_service.MAX_ESCALATION_ITEM_LENGTH
        context = {"searches": ["x" * length for _ in range(10)]}
        self.assertLess(
            len(json.dumps(context)),
            tenant_support_service.MAX_ESCALATION_CONTEXT_BYTES,
        )
        self.assertEqual(
            len(
                self._kwargs(_payload(escalation_context=context))[
                    "escalation_context"
                ]["searches"]
            ),
            10,
        )

    def test_oversized_input_is_rejected_and_never_silently_truncated(self):
        length = tenant_support_service.MAX_ESCALATION_ITEM_LENGTH
        error, rpc = self._submit(
            _payload(escalation_context={"searches": ["y" * (length + 50)]})
        )
        self.assertIsInstance(error, tenant_support_service.TenantSupportServiceError)
        rpc.assert_not_called()

    # --- the FORBIDDEN_TERMS asymmetry -----------------------------------

    def test_sensitive_searches_are_omitted_but_article_titles_are_preserved(self):
        """A real help article is called "Rotate your API token"."""
        context = {
            "viewed": ["Rotate your API token"],
            "unhelpful": ["Where do I find my password reset link"],
            "searches": ["cookie banner", "PASSWORD=fake-review-value", "connect a number"],
            "from_page": "support.html",
        }
        kwargs = self._kwargs(_payload(escalation_context=context))
        self.assertEqual(kwargs["escalation_context"], {
            **context, "searches": ["connect a number"],
        })

    def test_sensitive_only_searches_are_not_persisted(self):
        for term in tenant_support_service.FORBIDDEN_TERMS:
            with self.subTest(term=term):
                kwargs = self._kwargs(_payload(escalation_context={"searches": [term + "=fake"]}))
                self.assertIsNone(kwargs["escalation_context"])

    def test_redacted_description_still_runs_through_forbidden_terms(self):
        error, rpc = self._submit(
            _payload(redacted_description="Rotate your API token for me please.")
        )
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.code, "invalid_redacted_description")
        rpc.assert_not_called()

    def test_the_title_still_runs_through_forbidden_terms(self):
        error, _ = self._submit(_payload(title="Password reset loop"))
        self.assertEqual(error.code, "invalid_title")

    def test_a_forbidden_term_in_the_trail_does_not_rescue_a_bad_description(self):
        error, _ = self._submit(
            _payload(
                redacted_description="My password will not reset.",
                escalation_context={"viewed": ["Rotate your API token"]},
            )
        )
        self.assertEqual(error.code, "invalid_redacted_description")


class EscalationRepositoryTests(unittest.TestCase):
    def test_the_rpc_carries_the_three_new_fields(self):
        supabase = MagicMock()
        supabase.rpc.return_value.execute.return_value = MagicMock(data=31)
        context = {"from_page": "support.html"}
        with patch.object(tenant_support_repository, "supabase", supabase):
            request_id = tenant_support_repository.create_tenant_support_request(
                company_id=100,
                requester_user_id=7,
                category="technical",
                title="Test",
                redacted_description="Test description",
                priority="urgent",
                source="faq_dead_end",
                escalation_context=context,
            )
        self.assertEqual(request_id, 31)
        supabase.rpc.assert_called_once_with(
            "create_tenant_support_request",
            {
                "p_company_id": 100,
                "p_requester_user_id": 7,
                "p_category": "technical",
                "p_title": "Test",
                "p_redacted_description": "Test description",
                "p_priority": "urgent",
                "p_source": "faq_dead_end",
                "p_escalation_context": context,
            },
        )

    def test_a_null_trail_is_sent_as_null_not_as_an_empty_object(self):
        supabase = MagicMock()
        supabase.rpc.return_value.execute.return_value = MagicMock(data=31)
        with patch.object(tenant_support_repository, "supabase", supabase):
            tenant_support_repository.create_tenant_support_request(
                company_id=100,
                requester_user_id=7,
                category="technical",
                title="Test",
                redacted_description="Test description",
                priority="normal",
                source="direct",
                escalation_context=None,
            )
        self.assertIsNone(supabase.rpc.call_args[0][1]["p_escalation_context"])


class EscalationRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True, RATELIMIT_ENABLED=False, RATELIMIT_STORAGE_URI="memory://"
        )
        init_limiter(self.app)
        self.app.register_blueprint(support_bp)
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
            patch.object(tenant_support_service, "_notify_platform_support"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_a_dead_end_escalation_reaches_the_repository_whole(self):
        context = {
            "searches": ["qr code"],
            "viewed": ["Connect a WhatsApp number"],
            "unhelpful": ["Connect a WhatsApp number"],
            "from_page": "support.html",
        }
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            return_value=31,
        ) as rpc:
            response = self.client.post(
                "/api/support/requests",
                json=_payload(
                    priority="urgent",
                    source="faq_dead_end",
                    escalation_context=context,
                ),
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        rpc.assert_called_once_with(
            company_id=100,
            requester_user_id=7,
            category="technical",
            title="Cannot connect a number",
            redacted_description="The connect button does nothing on my account.",
            priority="urgent",
            source="faq_dead_end",
            escalation_context=context,
        )

    def test_a_direct_submission_still_works_with_none_of_the_new_fields(self):
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            return_value=31,
        ) as rpc:
            response = self.client.post(
                "/api/support/requests", json=_payload(), headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(rpc.call_args.kwargs["priority"], "normal")
        self.assertEqual(rpc.call_args.kwargs["source"], "direct")
        self.assertIsNone(rpc.call_args.kwargs["escalation_context"])

    def test_a_field_outside_the_widened_allowlist_is_still_rejected(self):
        for extra in ({"status": "closed"}, {"company_id": 1}, {"assignment": 2}):
            with self.subTest(extra=extra):
                with patch.object(
                    tenant_support_service.tenant_support_repository,
                    "create_tenant_support_request",
                ) as rpc:
                    response = self.client.post(
                        "/api/support/requests",
                        json=_payload(**extra),
                        headers=self.headers,
                    )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["code"], "unsupported_field")
                rpc.assert_not_called()

    def test_an_oversized_trail_is_a_400_and_writes_nothing(self):
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
        ) as rpc:
            response = self.client.post(
                "/api/support/requests",
                json=_payload(escalation_context={"searches": ["x" * 500]}),
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "invalid_escalation_context")
        rpc.assert_not_called()

    def test_the_tenant_never_sees_its_own_priority_reflected_back(self):
        """Pinned by test_tenant_support_routes; urgency is staff-facing."""
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            return_value=31,
        ):
            response = self.client.post(
                "/api/support/requests",
                json=_payload(priority="urgent"),
                headers=self.headers,
            )
        self.assertNotIn("urgent", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
