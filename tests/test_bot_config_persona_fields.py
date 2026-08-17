"""Persona field unification for public.bot_configs.

The same three values were stored under two column names each:

    business_description  <-  business_objective   (legacy)
    tone                  <-  response_style       (legacy)
    custom_prompt         <-  prompt_text          (legacy)

Reads were canonical-first with a legacy fallback; writes mirrored every value
into both names.  These tests lock the canonical name, the read-compatibility
fallback that keeps old rows resolving, and the write payload that stops
producing new drift.
"""

from pathlib import Path
import unittest
from unittest.mock import patch


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MIGRATION = DATA_DIR / "039_unify_bot_config_persona_fields.sql"
ROLLBACK = DATA_DIR / "039_unify_bot_config_persona_fields_rollback.sql"

CANONICAL_FIELDS = ("business_description", "tone", "custom_prompt")
LEGACY_FIELDS = ("business_objective", "response_style", "prompt_text")


class _Response:
    def __init__(self, data=None):
        self.data = data or []


class _FakeSupabase:
    """Minimal PostgREST builder double.

    ``select_responses`` are popped in call order; insert/update payloads are
    recorded so tests can assert on the exact row written.
    """

    def __init__(self, select_responses=None, write_result=None):
        self._select_responses = list(select_responses or [])
        self._write_result = write_result
        self.inserts = []
        self.updates = []
        self._mode = None
        self._table = None
        self._payload = None

    # -- builder surface -------------------------------------------------
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

    def eq(self, *_args, **_kwargs):
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

    # -- assertions helpers ----------------------------------------------
    @property
    def last_write_payload(self):
        writes = self.inserts + self.updates
        if not writes:
            raise AssertionError("no insert/update was issued")
        return writes[-1][1]


# =====================================================================
# 1. Shared field module: one canonical name per value
# =====================================================================

class PersonaFieldResolutionTests(unittest.TestCase):
    """Read side: legacy rows must keep resolving after the change."""

    def _resolve(self, row):
        from app.services.bot_config_fields import resolve_persona_fields

        return resolve_persona_fields(row)

    def test_legacy_only_row_resolves_to_canonical_keys(self):
        # Arrange: a row written before the canonical columns were populated.
        row = {
            "business_objective": "We sell artisanal rope.",
            "response_style": "Formal",
            "prompt_text": "Answer as a rope expert.",
        }

        # Act
        resolved = self._resolve(row)

        # Assert
        self.assertEqual(resolved["business_description"], "We sell artisanal rope.")
        self.assertEqual(resolved["tone"], "Formal")
        self.assertEqual(resolved["custom_prompt"], "Answer as a rope expert.")

    def test_canonical_only_row_resolves(self):
        row = {
            "business_description": "We sell rope.",
            "tone": "Friendly",
            "custom_prompt": "Be brief.",
        }

        resolved = self._resolve(row)

        self.assertEqual(resolved["business_description"], "We sell rope.")
        self.assertEqual(resolved["tone"], "Friendly")
        self.assertEqual(resolved["custom_prompt"], "Be brief.")

    def test_both_populated_and_different_resolves_to_canonical(self):
        # The documented winner is the canonical column.
        row = {
            "business_description": "CANONICAL desc",
            "business_objective": "LEGACY desc",
            "tone": "CANONICAL tone",
            "response_style": "LEGACY tone",
            "custom_prompt": "CANONICAL prompt",
            "prompt_text": "LEGACY prompt",
        }

        resolved = self._resolve(row)

        self.assertEqual(resolved["business_description"], "CANONICAL desc")
        self.assertEqual(resolved["tone"], "CANONICAL tone")
        self.assertEqual(resolved["custom_prompt"], "CANONICAL prompt")

    def test_blank_canonical_falls_back_to_legacy_for_unbackfilled_rows(self):
        # Rollout compatibility: a row the 031 backfill has not reached yet
        # may carry NULL or '' in the canonical column.
        row = {
            "business_description": None,
            "business_objective": "LEGACY desc",
            "tone": "",
            "response_style": "LEGACY tone",
            "custom_prompt": None,
            "prompt_text": "LEGACY prompt",
        }

        resolved = self._resolve(row)

        self.assertEqual(resolved["business_description"], "LEGACY desc")
        self.assertEqual(resolved["tone"], "LEGACY tone")
        self.assertEqual(resolved["custom_prompt"], "LEGACY prompt")

    def test_empty_and_none_rows_resolve_to_blank_strings(self):
        for row in ({}, {"business_description": None, "business_objective": None}):
            resolved = self._resolve(row)
            for field in CANONICAL_FIELDS:
                self.assertEqual(resolved[field], "", f"{field} from {row!r}")

    def test_resolution_never_emits_legacy_keys(self):
        resolved = self._resolve({"business_objective": "x", "response_style": "y"})

        for legacy in LEGACY_FIELDS:
            self.assertNotIn(legacy, resolved)

    def test_resolution_does_not_mutate_the_input_row(self):
        row = {"business_objective": "LEGACY desc"}
        original = dict(row)

        self._resolve(row)

        self.assertEqual(row, original)


class PersonaWritePayloadTests(unittest.TestCase):
    """Write side: one canonical name per value, legacy actively retired."""

    def _payload(self, values):
        from app.services.bot_config_fields import persona_write_payload

        return persona_write_payload(values)

    def test_payload_writes_the_canonical_column(self):
        payload = self._payload({
            "business_description": "We sell rope.",
            "tone": "Friendly",
            "custom_prompt": "Be brief.",
        })

        self.assertEqual(payload["business_description"], "We sell rope.")
        self.assertEqual(payload["tone"], "Friendly")
        self.assertEqual(payload["custom_prompt"], "Be brief.")

    def test_payload_nulls_every_legacy_column(self):
        # Explicit NULL (not omission) is what stops a stale mirror from
        # being resurrected by the read fallback after a value is blanked.
        payload = self._payload({
            "business_description": "We sell rope.",
            "tone": "Friendly",
            "custom_prompt": "Be brief.",
        })

        for legacy in LEGACY_FIELDS:
            self.assertIn(legacy, payload)
            self.assertIsNone(payload[legacy])

    def test_payload_defaults_missing_values_to_blank_strings(self):
        payload = self._payload({})

        for field in CANONICAL_FIELDS:
            self.assertEqual(payload[field], "")

    def test_payload_coalesces_falsy_values_to_blank_strings(self):
        # Deliberate narrowing of the `.get(name, "")` the two writers used
        # before this module, which passed None/0/False through to the column.
        # All three columns are free text, so no falsy value carries meaning.
        # Pinned here so a pair whose falsy value IS meaningful cannot be added
        # to LEGACY_ALIASES without this test failing first.
        for falsy in (None, 0, False, "", 0.0):
            payload = self._payload({"tone": falsy})

            self.assertEqual(payload["tone"], "", f"tone={falsy!r}")

    def test_payload_carries_only_the_six_persona_columns(self):
        payload = self._payload({"business_description": "x"})

        self.assertEqual(
            set(payload),
            set(CANONICAL_FIELDS) | set(LEGACY_FIELDS),
        )

    def test_payload_does_not_mutate_its_input(self):
        values = {"business_description": "x"}
        original = dict(values)

        self._payload(values)

        self.assertEqual(values, original)


# =====================================================================
# 2. settings_service integration
# =====================================================================

class SettingsServicePersonaTests(unittest.TestCase):
    def test_update_settings_writes_canonical_and_nulls_legacy(self):
        from app.services import settings_service

        fake = _FakeSupabase(select_responses=[[], []])

        with patch.object(settings_service, "supabase", fake):
            settings_service.update_settings(
                {
                    "business_description": "We sell rope.",
                    "tone": "Formal",
                    "custom_prompt": "Be brief.",
                    "active_profile": "Default Profile",
                },
                chatbot_id=7,
            )

        payload = fake.last_write_payload

        self.assertEqual(payload["business_description"], "We sell rope.")
        self.assertEqual(payload["tone"], "Formal")
        self.assertEqual(payload["custom_prompt"], "Be brief.")

        for legacy in LEGACY_FIELDS:
            self.assertIsNone(
                payload[legacy],
                f"{legacy} must not receive a mirrored value",
            )

    def test_update_settings_of_a_legacy_only_row_promotes_to_canonical(self):
        # Requirement 5: a row written by the old code must still resolve, and
        # editing one unrelated field must not drop the legacy-held values.
        from app.services import settings_service

        legacy_row = {
            "id": 3,
            "chatbot_id": 7,
            "profile_name": "Default Profile",
            "bot_name": "Ropey",
            "company_name": "Rope Co",
            "business_objective": "We sell artisanal rope.",
            "response_style": "Formal",
            "prompt_text": "Answer as a rope expert.",
            "is_active": True,
        }
        fake = _FakeSupabase(select_responses=[[legacy_row], [{"id": 3}]])

        with patch.object(settings_service, "supabase", fake):
            result = settings_service.update_settings(
                {"bot_name": "Ropey II"}, chatbot_id=7
            )

        payload = fake.last_write_payload

        self.assertEqual(payload["business_description"], "We sell artisanal rope.")
        self.assertEqual(payload["tone"], "Formal")
        self.assertEqual(payload["custom_prompt"], "Answer as a rope expert.")
        self.assertEqual(result["business_description"], "We sell artisanal rope.")
        self.assertEqual(result["tone"], "Formal")
        self.assertEqual(result["custom_prompt"], "Answer as a rope expert.")

    def test_blanking_a_value_does_not_resurrect_the_legacy_mirror(self):
        # A row the old code wrote carries both names.  Blanking the canonical
        # value must not let the read fallback restore the legacy copy.
        from app.services import settings_service

        old_row = {
            "id": 3,
            "chatbot_id": 7,
            "profile_name": "Default Profile",
            "business_description": "We sell rope.",
            "business_objective": "We sell rope.",
            "tone": "Formal",
            "response_style": "Formal",
            "custom_prompt": "Be brief.",
            "prompt_text": "Be brief.",
            "is_active": True,
        }
        fake = _FakeSupabase(select_responses=[[old_row], [{"id": 3}]])

        with patch.object(settings_service, "supabase", fake):
            result = settings_service.update_settings(
                {"business_description": "", "custom_prompt": ""}, chatbot_id=7
            )

        self.assertEqual(result["business_description"], "")
        self.assertEqual(result["custom_prompt"], "")
        self.assertIsNone(fake.last_write_payload["business_objective"])
        self.assertIsNone(fake.last_write_payload["prompt_text"])

    def test_update_then_read_round_trip_is_stable(self):
        from app.services import settings_service

        fake = _FakeSupabase(select_responses=[[], []])
        new_data = {
            "bot_name": "Ropey",
            "company_name": "Rope Co",
            "business_description": "We sell rope.",
            "tone": "Formal",
            "additional_instructions": "Never discuss knots.",
            "custom_prompt": "Be brief.",
            "active_profile": "Default Profile",
        }

        with patch.object(settings_service, "supabase", fake):
            written = settings_service.update_settings(new_data, chatbot_id=7)

        # Feed the persisted row back through the read path.
        persisted = dict(fake.last_write_payload)
        persisted["id"] = 1

        reread = settings_service._row_to_settings(persisted)

        self.assertEqual(written, reread)
        for key, value in new_data.items():
            self.assertEqual(reread[key], value, f"round trip lost {key}")

    def test_row_to_settings_still_resolves_a_row_written_by_old_code(self):
        from app.services import settings_service

        old_row = {
            "bot_name": "Ropey",
            "company_name": "Rope Co",
            "business_description": "We sell rope.",
            "business_objective": "We sell rope.",
            "tone": "Formal",
            "response_style": "Formal",
            "custom_prompt": "Be brief.",
            "prompt_text": "Be brief.",
            "profile_name": "Default Profile",
        }

        resolved = settings_service._row_to_settings(old_row)

        self.assertEqual(resolved["business_description"], "We sell rope.")
        self.assertEqual(resolved["tone"], "Formal")
        self.assertEqual(resolved["custom_prompt"], "Be brief.")
        self.assertEqual(resolved["active_profile"], "Default Profile")


# =====================================================================
# 3. profile_service: the sibling writer to the same table
# =====================================================================

class ProfileServicePersonaTests(unittest.TestCase):
    def test_save_profile_writes_canonical_and_nulls_legacy(self):
        from app.services import profile_service

        fake = _FakeSupabase(select_responses=[[]])

        with patch.object(profile_service, "supabase", fake):
            profile_service.save_profile(
                {
                    "name": "Support",
                    "business_description": "We sell rope.",
                    "tone": "Formal",
                    "custom_prompt": "Be brief.",
                },
                chatbot_id=7,
            )

        payload = fake.last_write_payload

        self.assertEqual(payload["business_description"], "We sell rope.")
        self.assertEqual(payload["tone"], "Formal")
        self.assertEqual(payload["custom_prompt"], "Be brief.")

        for legacy in LEGACY_FIELDS:
            self.assertIsNone(
                payload[legacy],
                f"{legacy} must not receive a mirrored value",
            )

    def test_save_profile_still_writes_out_of_scope_reply(self):
        # Guard against the refactor dropping the non-persona column.
        from app.services import profile_service

        fake = _FakeSupabase(select_responses=[[]])

        with patch.object(profile_service, "supabase", fake):
            profile_service.save_profile(
                {"name": "Support", "out_of_scope_reply": "Sorry."}, chatbot_id=7
            )

        self.assertEqual(fake.last_write_payload["out_of_scope_reply"], "Sorry.")

    def test_row_to_profile_resolves_a_legacy_only_row(self):
        from app.services import profile_service

        resolved = profile_service._row_to_profile({
            "id": 3,
            "profile_name": "Support",
            "business_objective": "We sell rope.",
            "response_style": "Formal",
            "prompt_text": "Be brief.",
        })

        self.assertEqual(resolved["business_description"], "We sell rope.")
        self.assertEqual(resolved["tone"], "Formal")
        self.assertEqual(resolved["custom_prompt"], "Be brief.")


# =====================================================================
# 4. Migration 031 and its rollback
# =====================================================================

def _sql_without_comments(path):
    text = path.read_text(encoding="utf-8")
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    ).lower()


class PersonaBackfillMigrationTests(unittest.TestCase):
    def test_migration_and_rollback_files_exist(self):
        self.assertTrue(MIGRATION.is_file(), f"missing {MIGRATION.name}")
        self.assertTrue(ROLLBACK.is_file(), f"missing {ROLLBACK.name}")

    def test_header_records_that_bot_configs_ddl_is_unavailable(self):
        header = MIGRATION.read_text(encoding="utf-8").lower()

        self.assertIn("bot_configs", header)
        self.assertIn("no create table", header)

    def test_backfill_targets_every_canonical_column(self):
        code = _sql_without_comments(MIGRATION)

        for canonical, legacy in zip(CANONICAL_FIELDS, LEGACY_FIELDS):
            self.assertIn(f"set {canonical} = {legacy}", code)

    def test_backfill_only_touches_blank_canonical_with_populated_legacy(self):
        code = _sql_without_comments(MIGRATION)

        for canonical, legacy in zip(CANONICAL_FIELDS, LEGACY_FIELDS):
            self.assertIn(f"{canonical} is null or btrim({canonical}) = ''", code)
            self.assertIn(f"{legacy} is not null", code)
            self.assertIn(f"btrim({legacy}) <> ''", code)

    def test_migration_relaxes_legacy_columns_so_writes_may_omit_them(self):
        code = _sql_without_comments(MIGRATION)

        for legacy in LEGACY_FIELDS:
            self.assertIn(f"alter column {legacy} drop not null", code)

    def test_migration_never_backfills_in_the_legacy_direction(self):
        code = _sql_without_comments(MIGRATION)

        for canonical, legacy in zip(CANONICAL_FIELDS, LEGACY_FIELDS):
            self.assertNotIn(f"set {legacy} = {canonical}", code)

    def test_migration_does_not_drop_or_rename_any_column(self):
        code = _sql_without_comments(MIGRATION)

        self.assertNotIn("drop column", code)
        self.assertNotIn("rename column", code)
        self.assertNotIn("drop table", code)

    def test_rollback_restores_every_legacy_column_from_canonical(self):
        code = _sql_without_comments(ROLLBACK)

        for canonical, legacy in zip(CANONICAL_FIELDS, LEGACY_FIELDS):
            self.assertIn(f"set {legacy} = {canonical}", code)

    def test_rollback_does_not_destroy_canonical_values(self):
        code = _sql_without_comments(ROLLBACK)

        self.assertNotIn("drop column", code)
        for canonical in CANONICAL_FIELDS:
            self.assertNotIn(f"set {canonical} = null", code)

    def test_rollback_states_what_it_cannot_restore(self):
        text = ROLLBACK.read_text(encoding="utf-8").lower()

        self.assertIn("cannot", text)

    def test_no_migration_number_collision(self):
        siblings = sorted(p.name for p in DATA_DIR.glob("039_*.sql"))

        self.assertEqual(siblings, sorted([MIGRATION.name, ROLLBACK.name]))


if __name__ == "__main__":
    unittest.main()
