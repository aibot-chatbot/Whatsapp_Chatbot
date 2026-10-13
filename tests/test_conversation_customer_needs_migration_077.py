"""data/077: the needs card column is additive, bounded and reversible."""
from pathlib import Path
import re

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"
M077 = DATA / "077_conversation_customer_needs.sql"
R077 = DATA / "077_conversation_customer_needs_rollback.sql"


def _sql(path):
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8")).strip()


@pytest.mark.parametrize("path", [M077, R077])
def test_is_one_transaction_with_lock_limits(path):
    sql = _sql(path)
    assert sql.startswith("BEGIN;") and sql.endswith("COMMIT;")
    assert "SET LOCAL lock_timeout" in sql and "SET LOCAL statement_timeout" in sql


def test_adds_only_a_nullable_bounded_object_column():
    sql = _sql(M077)
    assert "ADD COLUMN IF NOT EXISTS customer_needs jsonb" in sql
    assert "NOT NULL" not in sql and "DEFAULT" not in sql  # no table rewrite
    assert "jsonb_typeof(customer_needs) = 'object'" in sql
    assert "pg_column_size(customer_needs) <= 4096" in sql
    assert not re.search(r"\b(DROP|DELETE|UPDATE|TRUNCATE)\b", sql)


def test_rollback_drops_only_that_column():
    sql = _sql(R077)
    assert "DROP COLUMN IF EXISTS customer_needs;" in sql
    assert sql.count("DROP") == 1
