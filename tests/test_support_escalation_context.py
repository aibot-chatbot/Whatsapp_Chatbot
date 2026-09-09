"""Legacy runtime contract; retained migration checks do not execute SQL."""

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
            "4000", self.normalized
        )

    def test_priority_check_is_widened_to_the_three_urgency_levels(self):
        match = re.search(
            r"tenant_support_requests_priority_check\s+check\s*\(\s*priority in \(([^)]*)\)",
            self.normalized,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            set(re.findall(r"'([a-z_]+)'", match.group(1))),
            {"low", "normal", "urgent"},
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
            found, {"faq_dead_end", "direct", "tenant"}
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


class LegacySupportContractTests(unittest.TestCase):
    def test_submission_reaches_legacy_rpc_and_preserves_notification(self):
        client = MagicMock()

        def legacy_rpc(name, payload):
            self.assertEqual(name, "create_tenant_support_request")
            self.assertEqual(payload, {
                "p_company_id": 100,
                "p_requester_user_id": 7,
                "p_category": VALID_BASE["category"],
                "p_title": VALID_BASE["title"],
                "p_redacted_description": VALID_BASE["redacted_description"],
            })
            return MagicMock(execute=MagicMock(return_value=MagicMock(data=31)))

        client.rpc.side_effect = legacy_rpc
        with patch.object(tenant_support_repository, "supabase", client), patch.object(
            tenant_support_service, "_notify_platform_support"
        ) as notify:
            result = tenant_support_service.submit_tenant_support_request(
                _payload(), company_id=100, requester_user_id=7
            )
        self.assertEqual(result, {"request_id": 31})
        client.rpc.assert_called_once()
        client.table.assert_not_called()
        notify.assert_called_once_with(
            request_id=31, company_id=100, category="technical",
            description=VALID_BASE["redacted_description"],
        )

    def test_removed_fields_are_rejected_without_processing_or_writing(self):
        for key in ("priority", "source", "escalation_context"):
            for value in (None, "urgent", "direct", {}, [], True, 1,
                          {"searches": ["password=fake"]}):
                with self.subTest(key=key, value=value), patch.object(
                    tenant_support_repository, "create_tenant_support_request"
                ) as create, patch.object(
                    tenant_support_service, "_notify_platform_support"
                ) as notify:
                    with self.assertRaises(tenant_support_service.TenantSupportServiceError) as caught:
                        tenant_support_service.submit_tenant_support_request(
                            _payload(**{key: value}), company_id=100, requester_user_id=7
                        )
                    self.assertEqual(caught.exception.status_code, 400)
                    self.assertEqual(caught.exception.code, "unsupported_field")
                    create.assert_not_called()
                    notify.assert_not_called()

    def test_title_and_description_still_reject_all_sensitive_terms(self):
        for field in ("title", "redacted_description"):
            for term in tenant_support_service.FORBIDDEN_TERMS:
                with self.subTest(field=field, term=term), patch.object(
                    tenant_support_repository, "create_tenant_support_request"
                ) as create:
                    with self.assertRaises(tenant_support_service.TenantSupportServiceError) as caught:
                        tenant_support_service.submit_tenant_support_request(
                            _payload(**{field: term + "=fake"}),
                            company_id=100, requester_user_id=7,
                        )
                    self.assertEqual(caught.exception.code, "invalid_" + field)
                    create.assert_not_called()


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
        rpc.assert_called_once_with(company_id=100, requester_user_id=7, **VALID_BASE)

    def test_a_field_outside_the_widened_allowlist_is_still_rejected(self):
        for extra in ({"status": "closed"}, {"company_id": 1}, {"assignment": 2},
                      {"priority": "urgent"}, {"source": "direct"}, {"escalation_context": None}):
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
        self.assertEqual(response.json["code"], "unsupported_field")
        rpc.assert_not_called()

    def test_the_tenant_never_sees_its_own_priority_reflected_back(self):
        """Submission keeps the existing minimal response contract."""
        with patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            return_value=31,
        ):
            response = self.client.post(
                "/api/support/requests",
                json=_payload(),
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"], {"request_id": 31})


if __name__ == "__main__":
    unittest.main()
