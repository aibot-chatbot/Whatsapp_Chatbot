"""Migration 072 must keep matching the code that reads and writes it.

Seam: the SQL text against the repository/service constants. The migration was also applied,
exercised and rolled back on a scratch Postgres 18 when it was written; these checks stop the
two from drifting apart afterwards (a column the code selects but the table lacks only shows up
in production otherwise).
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database import service_booking_repository as repo
from app.services import booking_service as svc

DATA = Path(__file__).resolve().parent.parent / "data"
UP = (DATA / "072_service_bookings.sql").read_text(encoding="utf-8")
DOWN = (DATA / "072_service_bookings_rollback.sql").read_text(encoding="utf-8")


def _statements(sql):
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [part.strip() for part in code.split(";") if part.strip()]


def _table_body():
    match = re.search(r"CREATE TABLE public\.service_bookings \((.*?)\n\);", UP, re.S)
    assert match, "CREATE TABLE public.service_bookings not found"
    return match.group(1)


def _columns():
    names = set()
    for line in _table_body().splitlines():
        line = line.strip()
        if not line or line.startswith(("--", "CONSTRAINT", "CHECK", "UNIQUE")):
            continue
        first = line.split()[0]
        if re.fullmatch(r"[a-z_]+", first):
            names.add(first)
    return names


def _literals(column):
    """The quoted values of the column's `IN (...)` check."""
    match = re.search(rf"\b{column}\s+text[^,]*?\bIN \(([^)]*)\)", _table_body(), re.S)
    assert match, f"no IN-list check for {column}"
    return re.findall(r"'([^']*)'", match.group(1))


def test_there_is_exactly_one_072_migration_and_one_rollback():
    assert sorted(path.name for path in DATA.glob("072_*")) == [
        "072_service_bookings.sql", "072_service_bookings_rollback.sql"]


def _added_by_073():
    """Columns data/073_availability_booking.sql adds to service_bookings."""
    sql = (DATA / "073_availability_booking.sql").read_text(encoding="utf-8")
    alter = re.search(r"ALTER TABLE public\.service_bookings(.*?);", sql, re.S).group(1)
    return set(re.findall(r"ADD COLUMN\s+(\w+)", alter))


def test_every_column_the_repository_selects_exists():
    selected = set(repo._COLUMNS.split(","))
    known = _columns() | _added_by_073()

    assert selected <= known, selected - known


def test_every_column_the_service_writes_exists():
    written = {"company_id", "chatbot_id", "conversation_id", "kind", "status", "source", "intake_key",
               "customer_name", "customer_phone", "customer_ref", "channel", "service_name",
               "scheduled_for", "party_size", "notes"}

    assert written <= _columns(), written - _columns()


def test_every_editable_field_exists():
    assert set(repo._EDITABLE) <= _columns()


def test_the_enumerations_match_the_service():
    assert _literals("kind") == list(svc.KINDS)
    assert _literals("status") == list(svc.STATUSES)
    assert "chat" in _literals("source")


@pytest.mark.parametrize("column", ["customer_name", "customer_phone", "customer_ref", "channel",
                                    "service_name", "notes"])
def test_text_limits_match_what_the_service_allows(column):
    match = re.search(rf"\b{column}\s+text CHECK \(length\({column}\) <= (\d+)\)", UP)

    assert match, f"no length check for {column}"
    assert int(match.group(1)) == svc._LIMITS[column]


def test_party_size_bounds_match_the_service():
    assert f"party_size     integer CHECK (party_size BETWEEN 1 AND {svc._MAX_PARTY_SIZE})" in UP


def test_the_idempotency_key_is_unique_per_company():
    assert "UNIQUE (company_id, intake_key)" in UP


def test_the_intake_flag_defaults_off():
    assert "ADD COLUMN IF NOT EXISTS booking_intake_enabled boolean NOT NULL DEFAULT false" in " ".join(UP.split())


def test_the_service_always_stamps_the_times_the_table_requires():
    now = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)

    assert "confirmed_at" in svc._normalized_changes({"status": "requested"}, {"status": "confirmed"}, now)
    assert "cancelled_at" in svc._normalized_changes({"status": "requested"}, {"status": "cancelled"}, now)
    assert "cancelled_at" in svc._normalized_changes({"status": "confirmed"}, {"status": "cancelled"}, now)
    assert "status NOT IN ('confirmed','completed') OR confirmed_at IS NOT NULL" in UP
    assert "status <> 'cancelled' OR cancelled_at IS NOT NULL" in UP


def test_the_table_is_closed_to_everyone_but_the_service():
    assert "ALTER TABLE public.service_bookings ENABLE ROW LEVEL SECURITY" in UP
    assert "REVOKE ALL ON public.service_bookings FROM PUBLIC, anon, authenticated, service_role" in UP
    grants = [" ".join(s.split()) for s in _statements(UP) if s.upper().startswith("GRANT")]
    assert grants[0] == "GRANT SELECT, INSERT ON public.service_bookings TO service_role"
    assert len(grants) == 2 and grants[1].startswith("GRANT UPDATE (") and grants[1].endswith("TO service_role")
    assert "DELETE" not in " ".join(grants).upper()


def test_only_the_staff_editable_columns_can_ever_be_updated():
    update = next(s for s in _statements(UP) if s.upper().startswith("GRANT UPDATE ("))
    columns = {name.strip() for name in re.search(r"\((.*?)\)", update, re.S).group(1).split(",")}

    assert columns == set(repo._EDITABLE) | {"version", "updated_at"}
    for identity in ("id", "company_id", "chatbot_id", "conversation_id", "intake_key", "source", "created_at"):
        assert identity not in columns, identity


def test_the_chatbots_lock_is_taken_last_and_personal_data_columns_are_marked():
    statements = _statements(UP)

    assert statements[-2].startswith("ALTER TABLE public.chatbots"), "an exclusive lock on chatbots must be held briefly"
    commented = " ".join(s for s in statements if s.startswith("COMMENT ON COLUMN"))
    for column in ("customer_name", "customer_phone", "customer_ref", "notes"):
        assert f"public.service_bookings.{column}" in commented, column


def test_both_scripts_are_transactional_and_bounded():
    for sql in (UP, DOWN):
        statements = _statements(sql)
        assert statements[0] == "BEGIN" and statements[-1] == "COMMIT"
        assert "SET LOCAL lock_timeout = '3s'" in statements
        assert "SET LOCAL statement_timeout = '30s'" in statements


def test_the_rollback_removes_everything_the_migration_added():
    statements = _statements(DOWN)

    assert "DROP TABLE IF EXISTS public.service_bookings" in statements
    assert "ALTER TABLE public.chatbots DROP COLUMN IF EXISTS booking_intake_enabled" in statements


def test_the_scripts_say_they_are_unapplied_and_what_the_rollback_destroys():
    assert "Apply BEFORE deploying" in UP and "Not yet applied" in UP
    assert "DELETED" in DOWN
