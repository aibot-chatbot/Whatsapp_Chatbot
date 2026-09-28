"""data/071: the observation RPC takes its industry allowlist from the catalog."""
from pathlib import Path
import re

import pytest

from app.services.industry_template_catalog import template_ids

DATA = Path(__file__).resolve().parents[1] / "data"
M065 = DATA / "065_business_observations.sql"
M071 = DATA / "071_business_observation_industries.sql"
R071 = DATA / "071_business_observation_industries_rollback.sql"
OLD = "p_output->>'industry_id' NOT IN ('general','restaurant','clinic','tuition_center')"
NEW = "p_output->>'industry_id' !~ '^[a-z][a-z_]{1,39}$'"
PATTERN = re.compile(r"[a-z][a-z_]{1,39}")


def _function(path):
    text = path.read_text(encoding="utf-8")
    start = text.index("CREATE OR REPLACE FUNCTION public.analysis_apply_business_observation(")
    return text[start:text.index("TO service_role;", start) + len("TO service_role;")]


def test_only_the_industry_check_changes():
    assert _function(M065).count(OLD) == 1
    assert _function(M071) == _function(M065).replace(OLD, NEW)


def test_rollback_restores_the_065_definition():
    assert _function(R071) == _function(M065)


@pytest.mark.parametrize("path", [M071, R071])
def test_is_one_transaction_with_lock_limits(path):
    sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8")).strip()
    assert sql.startswith("BEGIN;") and sql.endswith("COMMIT;")
    assert "SET LOCAL lock_timeout" in sql and "SET LOCAL statement_timeout" in sql


def test_every_catalog_id_passes_the_database_format_check():
    assert all(PATTERN.fullmatch(template_id) for template_id in template_ids())


@pytest.mark.parametrize("bad", ["", "x", "Beauty", "beauty-salon", "salon'--", "a" * 41, "général", "1salon"])
def test_malformed_industry_ids_fail_the_format_check(bad):
    assert not PATTERN.fullmatch(bad)
