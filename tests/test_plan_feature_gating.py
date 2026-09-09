"""Subscription gating for the three capabilities added in this cycle.

What is actually under test
---------------------------
``billing_guard.can_use_plan_feature`` fails closed: a plan must carry an
exact boolean ``True`` for the requested key.  ``None``, malformed flags,
missing keys, explicit ``False`` values, and non-boolean truthy values are
all denied.

So the load-bearing test in this module is
:class:`TestMigrationSetsEveryKeyOnEveryPlan`, which parses the shipped SQL and
asserts that **every** ``PLAN_FEATURES`` key has an **explicit boolean** on
**every** plan code the migrations know about, so intended grants stay visible
in data instead of depending on application defaults.

LLM cost
--------
No test in this module reaches a billed provider.  ``generate_system_response``
is asserted *not* called on the denial paths and patched everywhere else; the
ingestion route's scraping/extraction stages are patched.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.billing_guard import (
    PLAN_FEATURES,
    BillingLimitError,
    can_use_plan_feature,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# ── The three keys under test ─────────────────────────────────────────────
UNIFIED_INGESTION = "unified_knowledge_ingestion"
DERIVED_PERSONA = "ai_derived_persona"
CONVERSATION_MEMORY = "conversation_memory"

NEW_FEATURE_KEYS = (UNIFIED_INGESTION, DERIVED_PERSONA, CONVERSATION_MEMORY)

# ── The plan matrix decided by the product owner ──────────────────────────
# Cost-aligned: conversation memory adds no LLM call (pure regex extraction),
# derived persona costs one LLM call per upload, unified ingestion is the
# expensive unbounded one.
EXPECTED_MATRIX = {
    "free": {UNIFIED_INGESTION: False, DERIVED_PERSONA: False, CONVERSATION_MEMORY: False},
    "essential": {UNIFIED_INGESTION: False, DERIVED_PERSONA: True, CONVERSATION_MEMORY: True},
    "advanced": {UNIFIED_INGESTION: True, DERIVED_PERSONA: True, CONVERSATION_MEMORY: True},
    "pro": {UNIFIED_INGESTION: True, DERIVED_PERSONA: True, CONVERSATION_MEMORY: True},
}
EXPECTED_PLAN_CODES = frozenset(EXPECTED_MATRIX)
VALID_FREE_TRIAL_END = "2099-01-01T00:00:00+00:00"
ACTIVE_PRIMARY_PDF = {
    "file_name": "primary.pdf",
    "file_type": "pdf",
    "is_active": True,
    "is_enabled": True,
}


# =========================================================================
# Migration parsing
# =========================================================================

def _without_comments(sql: str) -> str:
    """Strip SQL comments, as tests/test_conversation_graph_memory.py does.

    An assertion about what a migration *executes* must not be satisfied by
    prose in a comment.
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", sql)


_BUILD_OBJECT = re.compile(r"jsonb_build_object\s*\((.*?)\)", re.DOTALL)
_BUILD_PAIR = re.compile(r"'([a-z_]+)'\s*,\s*(true|false)\b", re.IGNORECASE)
_JSON_LITERAL = re.compile(r"'(\{.*?\})'\s*::\s*jsonb", re.DOTALL)
_PLAN_CODE = re.compile(r"LOWER\s*\(\s*code\s*\)\s*=\s*'([a-z0-9_-]+)'", re.IGNORECASE)


def _statement_flags(statement: str) -> dict[str, bool]:
    """Boolean feature flags a single SQL statement writes."""
    flags: dict[str, bool] = {}

    for literal in _JSON_LITERAL.findall(statement):
        try:
            parsed = json.loads(literal)
        except ValueError:
            continue
        for key, value in (parsed or {}).items():
            if isinstance(value, bool):
                flags[key] = value

    for body in _BUILD_OBJECT.findall(statement):
        for key, value in _BUILD_PAIR.findall(body):
            flags[key] = value.lower() == "true"

    return flags


def parse_migrated_feature_flags(sql_files: list[Path]) -> dict[str, dict[str, bool]]:
    """Replay every subscription-plan feature-flag write, in migration order.

    Returns ``{plan_code: {feature_key: bool}}`` -- the cumulative state a
    freshly migrated database ends up in.  Files are applied in filename order,
    which is migration order because they are numbered.
    """
    merged: dict[str, dict[str, bool]] = {}

    for path in sorted(sql_files):
        sql = _without_comments(path.read_text(encoding="utf-8-sig"))
        for statement in sql.split(";"):
            if "subscription_plans" not in statement or "feature_flags" not in statement:
                continue
            codes = _PLAN_CODE.findall(statement)
            flags = _statement_flags(statement)
            if not codes or not flags:
                continue
            # An INSERT ... WHERE NOT EXISTS (... LOWER(code) = 'x') names the
            # same code twice; the last match is the row the statement targets.
            merged.setdefault(codes[-1].lower(), {}).update(flags)

    return merged


def missing_flags(
    migrated: dict[str, dict[str, bool]], feature_keys: frozenset[str]
) -> dict[str, list[str]]:
    """``{plan_code: [keys with no explicit boolean]}`` -- empty when complete."""
    gaps: dict[str, list[str]] = {}
    for code, flags in migrated.items():
        absent = sorted(
            key
            for key in feature_keys
            if not isinstance(flags.get(key), bool)
        )
        if absent:
            gaps[code] = absent
    return gaps


def _forward_migrations() -> list[Path]:
    return [p for p in DATA_DIR.glob("*.sql") if "rollback" not in p.name.lower()]


MIGRATED_FLAGS = parse_migrated_feature_flags(_forward_migrations())


# =========================================================================
# 1. The registry
# =========================================================================

class TestPlanFeatureRegistry(unittest.TestCase):
    def test_every_new_key_is_registered(self):
        for key in NEW_FEATURE_KEYS:
            with self.subTest(feature_key=key):
                self.assertIn(key, PLAN_FEATURES)

    def test_the_pre_existing_keys_are_untouched(self):
        for key in (
            "batch_website_scraping",
            "single_website_scraping",
            "ai_generated_reports",
            "ai_assisted_menu_generation",
            "crm_lead_assignment",
        ):
            with self.subTest(feature_key=key):
                self.assertIn(key, PLAN_FEATURES)

    def test_an_unregistered_key_is_denied_rather_than_allowed(self):
        with self.assertRaises(BillingLimitError):
            can_use_plan_feature(1, "unified_knowledge_ingest")  # near-miss typo


# =========================================================================
# 2. The migration IS the gate
# =========================================================================

class TestMigrationSetsEveryKeyOnEveryPlan(unittest.TestCase):
    """The load-bearing test. See the module docstring."""

    def test_the_parser_actually_found_the_shipped_migrations(self):
        # Guards against a parser that silently matches nothing and lets every
        # assertion below pass vacuously.
        self.assertEqual(set(MIGRATED_FLAGS), set(EXPECTED_PLAN_CODES))
        self.assertIs(MIGRATED_FLAGS["pro"]["batch_website_scraping"], True)
        self.assertIs(MIGRATED_FLAGS["free"]["single_website_scraping"], False)

    def test_every_registered_key_has_an_explicit_boolean_on_every_plan(self):
        gaps = missing_flags(MIGRATED_FLAGS, PLAN_FEATURES)
        self.assertEqual(
            gaps,
            {},
            "can_use_plan_feature returns True for an absent key "
            "(billing_guard.py:439-440), so a plan missing one of these keys "
            "keeps the capability for free: " + repr(gaps),
        )

    def test_the_new_keys_match_the_approved_matrix(self):
        for code, expected in EXPECTED_MATRIX.items():
            for key, value in expected.items():
                with self.subTest(plan=code, feature_key=key):
                    self.assertIs(MIGRATED_FLAGS[code][key], value)

    def test_a_plan_code_no_migration_configures_would_be_caught(self):
        # Proof the coverage check can fail: a fifth plan carrying only the old
        # keys must be reported, not shrugged off.
        with_extra = dict(MIGRATED_FLAGS)
        with_extra["enterprise"] = {"batch_website_scraping": True}
        gaps = missing_flags(with_extra, PLAN_FEATURES)
        self.assertIn("enterprise", gaps)
        for key in NEW_FEATURE_KEYS:
            self.assertIn(key, gaps["enterprise"])

    def test_a_key_added_to_one_plan_only_would_be_caught(self):
        partial = {code: dict(flags) for code, flags in MIGRATED_FLAGS.items()}
        partial["essential"].pop(CONVERSATION_MEMORY)
        gaps = missing_flags(partial, PLAN_FEATURES)
        self.assertEqual(gaps, {"essential": [CONVERSATION_MEMORY]})

    def test_a_null_valued_key_does_not_count_as_explicit(self):
        # feature_flags -> {"conversation_memory": null} is not a boolean and
        # can_use_plan_feature would block on it; the migration must never
        # write one.
        loose = {code: dict(flags) for code, flags in MIGRATED_FLAGS.items()}
        loose["free"][CONVERSATION_MEMORY] = None
        self.assertIn("free", missing_flags(loose, PLAN_FEATURES))


class TestMigration042(unittest.TestCase):
    """The new migration is a new file, not an edit to an applied one."""

    @classmethod
    def setUpClass(cls):
        matches = sorted(DATA_DIR.glob("042_*.sql"))
        cls.forward = [p for p in matches if "rollback" not in p.name.lower()]
        cls.sql = (
            _without_comments(cls.forward[0].read_text(encoding="utf-8-sig"))
            if cls.forward
            else ""
        )

    def test_the_new_flags_ship_as_migration_042(self):
        self.assertTrue(
            self.forward,
            "004 has already been applied to real databases, so editing it "
            "would never run there; the new keys need their own migration.",
        )

    def test_004_is_not_retroactively_edited(self):
        four = _without_comments(
            (DATA_DIR / "004_add_subscription_plan_feature_flags.sql").read_text(
                encoding="utf-8-sig"
            )
        )
        for key in NEW_FEATURE_KEYS:
            with self.subTest(feature_key=key):
                self.assertNotIn(key, four)

    def test_it_merges_rather_than_replaces_the_flags(self):
        # || on COALESCE(feature_flags, '{}') keeps keys earlier migrations set.
        self.assertIn("COALESCE(feature_flags", self.sql)
        self.assertIn("jsonb_build_object", self.sql)
        self.assertNotIn("feature_flags = jsonb_build_object", self.sql)

    def test_it_names_all_four_plan_codes(self):
        named = {code.lower() for code in _PLAN_CODE.findall(self.sql)}
        self.assertEqual(named, set(EXPECTED_PLAN_CODES))

    def test_an_unnamed_plan_code_is_defaulted_to_false(self):
        """A fifth plan code in a real database must not keep the features.

        An absent key is *allowed* by can_use_plan_feature, so the migration
        needs a catch-all that writes false for every code it does not name.
        """
        self.assertRegex(self.sql, r"LOWER\s*\(\s*code\s*\)\s+NOT\s+IN")
        catch_all = [
            stmt
            for stmt in self.sql.split(";")
            if re.search(r"LOWER\s*\(\s*code\s*\)\s+NOT\s+IN", stmt, re.IGNORECASE)
        ]
        self.assertTrue(catch_all)
        flags = _statement_flags(catch_all[0])
        for key in NEW_FEATURE_KEYS:
            with self.subTest(feature_key=key):
                self.assertIs(flags.get(key), False)

    def test_a_rollback_exists(self):
        self.assertTrue(sorted(DATA_DIR.glob("042_*rollback*.sql")))

    def test_it_touches_no_price_limit_or_model_tier(self):
        for column in (
            "price",
            "chatbot_limit",
            "team_member_limit",
            "knowledge_file_limit",
            "knowledge_storage_limit_bytes",
            "channel_limit",
            "model_access_tier",
            "included_ai_credit_micro_myr",
        ):
            with self.subTest(column=column):
                self.assertNotIn(column, self.sql)


# =========================================================================
# 3. The guard, driven by the flags the migration actually writes
# =========================================================================

def subscription_for(plan_code: str) -> dict:
    """An active subscription carrying the *migrated* flags for that plan."""
    subscription = {
        "status": "active",
        "current_period_end": "2099-01-01T00:00:00+00:00",
        "plan": {
            "code": plan_code,
            "name": plan_code.title(),
            "feature_flags": dict(MIGRATED_FLAGS[plan_code]),
        },
    }
    if plan_code == "free":
        subscription["trial_ends_at"] = VALID_FREE_TRIAL_END
    return subscription


class TestGuardMatchesTheMatrix(unittest.TestCase):
    COMPANY_ID = 4242

    def _allowed(self, plan_code: str, feature_key: str) -> bool:
        with patch(
            "app.services.billing_guard.get_current_subscription",
            return_value=subscription_for(plan_code),
        ), patch(
            "app.services.billing_guard.ensure_default_company_subscription",
            return_value=None,
        ):
            try:
                return can_use_plan_feature(self.COMPANY_ID, feature_key) is True
            except BillingLimitError:
                return False

    def test_free_tier_is_denied_every_new_feature(self):
        for key in NEW_FEATURE_KEYS:
            with self.subTest(feature_key=key):
                self.assertFalse(self._allowed("free", key))

    def test_every_plan_matches_the_matrix(self):
        for code, expected in EXPECTED_MATRIX.items():
            for key, value in expected.items():
                with self.subTest(plan=code, feature_key=key):
                    self.assertEqual(self._allowed(code, key), value)

    def test_denial_carries_the_feature_code_and_key(self):
        with patch(
            "app.services.billing_guard.get_current_subscription",
            return_value=subscription_for("free"),
        ), patch(
            "app.services.billing_guard.ensure_default_company_subscription",
            return_value=None,
        ):
            with self.assertRaises(BillingLimitError) as ctx:
                can_use_plan_feature(self.COMPANY_ID, CONVERSATION_MEMORY)

        self.assertEqual(ctx.exception.code, "feature_not_available")
        self.assertEqual(
            (ctx.exception.details or {}).get("feature_key"), CONVERSATION_MEMORY
        )


class TestGuardFailsClosedWithoutTheMigration(unittest.TestCase):
    """The application denies malformed or incomplete feature-flag data."""

    COMPANY_ID = 4242

    def _allowed_with_flags(self, feature_flags) -> bool:
        subscription = {
            "status": "active",
            "trial_ends_at": VALID_FREE_TRIAL_END,
            "plan": {"code": "free", "name": "Free", "feature_flags": feature_flags},
        }
        with patch(
            "app.services.billing_guard.get_current_subscription",
            return_value=subscription,
        ), patch(
            "app.services.billing_guard.ensure_default_company_subscription",
            return_value=None,
        ):
            try:
                return can_use_plan_feature(self.COMPANY_ID, CONVERSATION_MEMORY) is True
            except BillingLimitError:
                return False

    def test_a_plan_row_the_migration_never_reached_is_denied(self):
        self.assertFalse(self._allowed_with_flags({"batch_website_scraping": True}))

    def test_a_null_feature_flags_column_is_denied(self):
        self.assertFalse(self._allowed_with_flags(None))

    def test_a_non_object_feature_flags_column_is_denied(self):
        for junk in ("[]", [], 0, "true"):
            with self.subTest(feature_flags=junk):
                self.assertFalse(self._allowed_with_flags(junk))

    def test_truthy_non_boolean_values_are_denied(self):
        for value in ("true", 1):
            with self.subTest(value=value):
                self.assertFalse(self._allowed_with_flags({CONVERSATION_MEMORY: value}))


class TestChatbotScopedGuard(unittest.TestCase):
    """Message-path seams carry a chatbot_id, not a company_id."""

    def _check(self, bot, plan_code="free", bot_error=None):
        from app.services import billing_guard

        with patch(
            "app.database.bot_repository.get_bot_by_id",
            return_value=bot,
            side_effect=bot_error,
        ), patch(
            "app.services.billing_guard.get_current_subscription",
            return_value=subscription_for(plan_code),
        ), patch(
            "app.services.billing_guard.ensure_default_company_subscription",
            return_value=None,
        ):
            return billing_guard.can_use_plan_feature_for_chatbot(
                7, CONVERSATION_MEMORY
            )

    def test_it_resolves_the_owning_company_and_allows_an_entitled_plan(self):
        self.assertTrue(self._check({"id": 7, "company_id": 11}, "advanced"))

    def test_it_denies_a_free_tier_chatbot(self):
        with self.assertRaises(BillingLimitError):
            self._check({"id": 7, "company_id": 11}, "free")

    def test_an_unresolvable_chatbot_fails_closed(self):
        for bot in (None, {}, {"id": 7}, {"id": 7, "company_id": None},
                    {"id": 7, "company_id": 0}, {"id": 7, "company_id": True}):
            with self.subTest(bot=bot):
                with self.assertRaises(BillingLimitError):
                    self._check(bot, "pro")

    def test_a_repository_outage_fails_closed(self):
        with self.assertRaises(BillingLimitError):
            self._check(None, "pro", bot_error=RuntimeError("postgrest down"))

    def test_a_row_that_is_not_the_bot_asked_for_fails_closed(self):
        # Defence in depth against a loosened lookup: the entitlement must
        # never be evaluated against a company that does not own *this* bot.
        with self.assertRaises(BillingLimitError) as ctx:
            self._check({"id": 8, "company_id": 11}, "pro")  # asked for 7
        self.assertEqual(ctx.exception.code, "company_unresolved")


# =========================================================================
# 4. Entry point: POST /api/knowledge/ingest
# =========================================================================

AUTH_HEADERS = {"Authorization": "Bearer test-token"}
COMPANY_ID = 28
CHATBOT_ID = 29
INGEST_URL = f"/api/knowledge/ingest?chatbot_id={CHATBOT_ID}"
CURRENT_USER = {
    "id": 31,
    "company_id": COMPANY_ID,
    "email": "tenant-28@example.test",
    "role": "admin",
    "status": "active",
}


def plan_gate_for(plan_code: str):
    """A can_use_plan_feature double answering from the migrated flags.

    Mirrors the real guard's fail-closed semantics for absent keys.
    """

    def gate(company_id, feature_key):
        flags = MIGRATED_FLAGS[plan_code]
        if flags.get(feature_key) is True:
            return True
        raise BillingLimitError(
            f'The feature "{feature_key}" is not available on your current '
            "subscription plan.",
            code="feature_not_available",
            details={"feature_key": feature_key},
        )

    return gate


class IngestRouteGateTests(unittest.TestCase):
    def setUp(self):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _post(self, plan_code):
        from app.services import knowledge_service

        with patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
        ), patch(
            "app.database.user_repository.get_user_by_id", return_value=CURRENT_USER
        ), patch(
            "app.routes.knowledge_routes.verify_chatbot_access"
        ), patch(
            "app.routes.knowledge_routes.get_active_knowledge_file",
            return_value=ACTIVE_PRIMARY_PDF,
        ), patch(
            "app.routes.knowledge_routes.can_upload_knowledge_file"
        ), patch(
            "app.routes.knowledge_routes.can_use_plan_feature",
            side_effect=plan_gate_for(plan_code),
        ) as gate, patch.object(
            knowledge_service, "fetch_and_parse_url"
        ) as fetch, patch.object(
            knowledge_service, "extract_business_knowledge"
        ) as extract, patch(
            "app.routes.knowledge_routes.ingest_website_sources",
            return_value={"status": "succeeded", "chatbot_id": CHATBOT_ID},
        ), patch(
            "app.routes.knowledge_routes.summarize_report", return_value="ok"
        ):
            response = self.client.post(
                INGEST_URL,
                json={"sources": ["https://example.test"]},
                headers=AUTH_HEADERS,
            )
        return response, gate, fetch, extract

    def test_free_tier_is_denied_and_nothing_is_scraped_or_extracted(self):
        response, gate, fetch, extract = self._post("free")

        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertEqual(body["code"], "feature_not_available")
        self.assertEqual(
            body["details"]["feature_key"],
            UNIFIED_INGESTION,
            "the route must deny on its own capability key first",
        )
        fetch.assert_not_called()
        extract.assert_not_called()

    def test_the_route_asks_for_the_unified_ingestion_key(self):
        _, gate, _, _ = self._post("pro")
        asked = [call.args[1] for call in gate.call_args_list]
        self.assertIn(UNIFIED_INGESTION, asked)
        self.assertEqual(gate.call_args_list[0].args[0], COMPANY_ID)

    def test_an_entitled_plan_reaches_the_pipeline(self):
        response, _, _, _ = self._post("pro")
        self.assertEqual(response.status_code, 200)

    def test_essential_is_denied(self):
        response, _, fetch, _ = self._post("essential")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["details"]["feature_key"], UNIFIED_INGESTION
        )
        fetch.assert_not_called()

    def test_advanced_still_meets_the_pre_existing_batch_scraping_gate(self):
        """Characterisation, not endorsement.

        The matrix grants Advanced ``unified_knowledge_ingestion``, but this
        endpoint scrapes many pages per source and the pre-existing
        ``batch_website_scraping`` gate -- false for Advanced since
        data/004 -- still applies.  Advanced is therefore denied here by the
        *older* key.  Loosening that would hand Advanced a monetised feature
        through the composed endpoint; it is a product decision, not a
        refactor.
        """
        response, _, fetch, _ = self._post("advanced")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["details"]["feature_key"], "batch_website_scraping"
        )
        fetch.assert_not_called()


# =========================================================================
# 5. Entry point: persona derivation on document upload
# =========================================================================

class PersonaDerivationGateTests(unittest.TestCase):
    CHATBOT_ID = 7

    def _derive(self, plan_code):
        from app.services import ai_router, persona_derivation_service as svc

        with patch(
            "app.database.bot_repository.get_bot_by_id",
            return_value={"id": self.CHATBOT_ID, "company_id": 11},
        ), patch(
            "app.services.billing_guard.get_current_subscription",
            return_value=subscription_for(plan_code),
        ), patch(
            "app.services.billing_guard.ensure_default_company_subscription",
            return_value=None,
        ), patch.object(
            svc, "derive_persona_from_documents"
        ) as derive, patch.object(
            ai_router, "generate_system_response"
        ) as llm:
            derive.return_value = svc.PersonaDerivationResult(
                status=svc.STATUS_SUCCEEDED
            )
            result = svc.derive_persona_for_upload(self.CHATBOT_ID)
        return result, derive, llm

    def test_free_tier_is_denied_and_no_llm_call_is_made(self):
        from app.services import persona_derivation_service as svc

        result, derive, llm = self._derive("free")

        derive.assert_not_called()
        llm.assert_not_called()
        self.assertEqual(result.status, svc.STATUS_SKIPPED)
        self.assertEqual(result.error_code, "feature_not_available")

    def test_the_denial_does_not_raise_into_a_successful_upload(self):
        # /upload-pdf already saved the file and consumed the quota; a plan
        # denial for the description step must not turn that into a 403.
        result, _, _ = self._derive("free")
        self.assertIsNotNone(result.error_message)

    def test_an_entitled_plan_still_derives(self):
        from app.services import persona_derivation_service as svc

        result, derive, _ = self._derive("essential")

        derive.assert_called_once_with(self.CHATBOT_ID)
        self.assertEqual(result.status, svc.STATUS_SUCCEEDED)

    def test_every_entitled_plan_in_the_matrix_derives(self):
        for code, expected in EXPECTED_MATRIX.items():
            if not expected[DERIVED_PERSONA]:
                continue
            with self.subTest(plan=code):
                _, derive, _ = self._derive(code)
                derive.assert_called_once()

    def test_an_unverifiable_entitlement_fails_closed(self):
        from app.services import ai_router, persona_derivation_service as svc

        with patch(
            "app.database.bot_repository.get_bot_by_id",
            side_effect=RuntimeError("postgrest down"),
        ), patch.object(
            svc, "derive_persona_from_documents"
        ) as derive, patch.object(
            ai_router, "generate_system_response"
        ) as llm:
            result = svc.derive_persona_for_upload(self.CHATBOT_ID)

        derive.assert_not_called()
        llm.assert_not_called()
        self.assertEqual(result.status, svc.STATUS_SKIPPED)
        self.assertIsNotNone(result.error_code)


# =========================================================================
# 6. Entry point: conversation memory (producer + consumer)
# =========================================================================

class ConversationMemoryDenialTests(unittest.TestCase):
    CHATBOT_ID = 7
    CONVERSATION_ID = 3

    def _denial(self, plan_code=None, bot_error=None):
        from app.services import conversation_memory_service as memory

        with patch(
            "app.database.bot_repository.get_bot_by_id",
            return_value={"id": self.CHATBOT_ID, "company_id": 11},
            side_effect=bot_error,
        ), patch(
            "app.services.billing_guard.get_current_subscription",
            return_value=subscription_for(plan_code or "free"),
        ), patch(
            "app.services.billing_guard.ensure_default_company_subscription",
            return_value=None,
        ):
            return memory.conversation_memory_denial(self.CHATBOT_ID)

    def test_free_tier_is_denied_with_a_code(self):
        self.assertEqual(self._denial("free"), "feature_not_available")

    def test_entitled_plans_are_not_denied(self):
        for code, expected in EXPECTED_MATRIX.items():
            with self.subTest(plan=code):
                self.assertEqual(
                    self._denial(code) is None, expected[CONVERSATION_MEMORY]
                )

    def test_it_never_raises_into_the_reply_path(self):
        # The customer on WhatsApp is not the paying tenant and cannot act on a
        # billing error, so the denial is returned, never raised.
        self.assertIsNotNone(self._denial(bot_error=RuntimeError("postgrest down")))


class ConversationMemoryProducerGateTests(unittest.TestCase):
    """chat_pipeline_service.py:115-145 -- the seam whose except swallows."""

    def test_a_denied_plan_writes_no_fact_and_is_not_reported_as_a_store_failure(self):
        from app.services import chat_pipeline_service as pipeline
        from app.services import conversation_memory_service as memory

        with patch.object(
            memory, "conversation_memory_denial", return_value="feature_not_available"
        ), patch.object(
            memory, "remember_conversation_facts"
        ) as remember, self.assertLogs(level="INFO") as logs:
            result = self._run_pipeline(pipeline)

        remember.assert_not_called()
        self.assertIsNotNone(result)
        joined = "\n".join(logs.output)
        self.assertIn("feature_not_available", joined)
        self.assertNotIn("store failed", joined)

    def test_an_entitled_plan_still_stores(self):
        from app.services import chat_pipeline_service as pipeline
        from app.services import conversation_memory_service as memory

        with patch.object(
            memory, "conversation_memory_denial", return_value=None
        ), patch.object(memory, "remember_conversation_facts") as remember:
            self._run_pipeline(pipeline)

        remember.assert_called_once()
        self.assertEqual(remember.call_args.kwargs["conversation_id"], 3)

    def _run_pipeline(self, pipeline):
        with patch.object(
            pipeline,
            "get_or_create_conversation",
            return_value={"id": 3, "customer_phone": "60123"},
        ), patch.object(
            pipeline, "get_recent_chat_history", return_value=[]
        ), patch(
            "app.database.agent_action_repository.is_conversation_escalated",
            return_value=False,
        ), patch.object(
            pipeline,
            "analyze_agent_intent",
            return_value={
                "intent": "general_query",
                "suggested_action": "none",
                "confidence": 0.9,
                "reason": "",
                "extracted_fields": {"name": "Alice"},
            },
        ), patch.object(
            pipeline, "get_bot_by_id", return_value={"id": 7, "company_id": 11}
        ), patch.object(
            pipeline, "save_agent_action"
        ), patch.object(
            pipeline, "create_crm_lead_from_agent_signal"
        ), patch.object(
            pipeline, "detect_intent", return_value="general_query"
        ), patch.object(
            pipeline, "update_workflow_state"
        ), patch.object(
            pipeline, "retrieve_relevant_chunks", return_value=[]
        ), patch.object(
            pipeline, "build_prompt", return_value="PROMPT"
        ):
            return pipeline.prepare_chat_prompt("hi", "60123", 7)


class ConversationMemoryConsumerGateTests(unittest.TestCase):
    """rag_service.py:637-685 -- the conversation_id branch."""

    def _retrieve(self, denial):
        from app.services import conversation_memory_service as memory
        from app.services import rag_service

        with patch.object(
            rag_service, "get_active_pdf_knowledge_file", return_value={"id": 10}
        ), patch.object(
            rag_service, "get_supporting_knowledge_files", return_value=[]
        ), patch.object(
            rag_service,
            "get_chunks_by_file_for_chatbot",
            return_value=[{"content": "We open at 9am."}],
        ), patch.object(
            rag_service, "generate_embedding", return_value=None
        ), patch.object(
            rag_service, "_vector_matches_for_file", return_value=[]
        ), patch.object(
            memory, "conversation_memory_denial", return_value=denial
        ), patch.object(
            memory,
            "recall_conversation_facts",
            return_value=["- The customer's name is Alice."],
        ) as recall:
            chunks = rag_service.retrieve_relevant_chunks(
                "remind me of my name", chatbot_id=7, top_k=3, conversation_id=3
            )
        return chunks, recall

    def test_a_denied_plan_recalls_nothing(self):
        # Matters after a downgrade: facts written while entitled must stop
        # reaching the prompt.
        chunks, recall = self._retrieve("feature_not_available")

        recall.assert_not_called()
        self.assertNotIn("Alice", "\n".join(chunks))

    def test_an_entitled_plan_still_recalls(self):
        chunks, recall = self._retrieve(None)

        recall.assert_called_once()
        self.assertIn("Alice", "\n".join(chunks))

    def test_the_document_context_survives_a_denial(self):
        chunks, _ = self._retrieve("feature_not_available")
        self.assertTrue(chunks, "a plan denial must not empty the RAG context")


class NoUngatedCallerTests(unittest.TestCase):
    """The gate lives at the seams, so a third seam would bypass it.

    Scans for the *identifier*, not for ``identifier(``.  A call is only one of
    the ways a primitive gets reached: ``alias = svc.derive_persona_from_docu\
ments`` and ``getattr(svc, "recall_conversation_facts")`` both invoke it
    without ever writing ``name(``, and both would slip past a call-shaped
    regex.  Paths are reported relative to the repository root rather than by
    bare filename, so two modules of the same name in different packages
    cannot mask each other.
    """

    APP = PROJECT_ROOT / "app"

    def _mentions(self, identifier: str) -> set[str]:
        found = set()
        for path in self.APP.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(rf"\b{identifier}\b", text):
                found.add(path.relative_to(PROJECT_ROOT).as_posix())
        return found

    def test_the_producer_has_exactly_one_caller_and_it_is_gated(self):
        self.assertEqual(
            self._mentions("remember_conversation_facts"),
            {
                "app/services/chat_pipeline_service.py",
                "app/services/conversation_memory_service.py",
            },
            "a new caller must call conversation_memory_denial first",
        )

    def test_the_consumer_has_exactly_one_caller_and_it_is_gated(self):
        self.assertEqual(
            self._mentions("recall_conversation_facts"),
            {
                "app/services/rag_service.py",
                "app/services/conversation_memory_service.py",
            },
            "a new caller must call conversation_memory_denial first",
        )

    def test_the_memory_seams_consult_the_gate(self):
        for name in ("chat_pipeline_service.py", "rag_service.py"):
            with self.subTest(module=name):
                text = (self.APP / "services" / name).read_text(encoding="utf-8")
                self.assertIn("conversation_memory_denial", text)

    def test_the_ungated_persona_primitive_is_reached_only_through_its_seam(self):
        # derive_persona_from_documents makes the billed LLM call and has no
        # gate of its own; derive_persona_for_upload is the gate.  A route that
        # imported the primitive directly would derive personas for free.
        self.assertEqual(
            self._mentions("derive_persona_from_documents"),
            {"app/services/persona_derivation_service.py"},
            "a new caller must go through derive_persona_for_upload",
        )

    def test_the_persona_seam_consults_the_gate(self):
        text = (
            self.APP / "services" / "persona_derivation_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("can_use_plan_feature_for_chatbot", text)

    def test_the_unified_ingestion_pipeline_is_reached_only_through_its_route(self):
        self.assertEqual(
            self._mentions("ingest_website_sources"),
            {
                "app/routes/knowledge_routes.py",
                "app/services/knowledge_ingestion_service.py",
            },
            "a new caller must gate on unified_knowledge_ingestion first",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
