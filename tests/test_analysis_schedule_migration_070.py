"""data/070: owner-chosen schedule day/time.

Text assertions always run. The behaviour drill runs only with
RUN_LOCAL_POSTGRES_TESTS=1, on the throwaway loopback cluster that
tests/test_analysis_postgres.py builds; it never touches a real database.
On a non-English Windows locale also set LANG=C LC_ALL=C LC_MESSAGES=C, or
that harness cannot decode initdb's localized output.
"""
import json
from pathlib import Path
import re

import pytest

from tests.test_analysis_postgres import pg  # noqa: F401  (opt-in throwaway cluster)

DATA = Path(__file__).resolve().parents[1] / "data"
MIGRATION = DATA / "070_analysis_schedule_custom_time.sql"
ROLLBACK = DATA / "070_analysis_schedule_custom_time_rollback.sql"
OLD_SIGNATURE = "public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz)"
NEW_SIGNATURE = ("public.analysis_upsert_schedule(bigint,bigint,bigint,text,text,boolean,timestamptz,"
                 "smallint,smallint,time)")


def _sql(path):
    text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    return re.sub(r"\s+", " ", text).lower().replace(" ,", ",").replace(", ", ",").strip()


def _upsert_definition(sql):
    return re.search(r"create function public\.analysis_upsert_schedule\(.*?end \$\$;", sql).group(0)


def test_is_one_transaction_with_lock_limits():
    sql = _sql(MIGRATION)
    assert sql.startswith("begin;") and sql.endswith("commit;")
    assert "set local lock_timeout" in sql and "set local statement_timeout" in sql


def test_adds_the_three_slot_columns_idempotently():
    sql = _sql(MIGRATION)
    for column in ("run_weekday smallint", "run_day smallint", "run_time time"):
        assert f"add column if not exists {column}" in sql


def test_checks_ranges_quarter_hours_and_that_enabled_rows_have_a_slot():
    sql = _sql(MIGRATION)
    assert "check (run_weekday between 0 and 6)" in sql
    assert "check (run_day between 0 and 28)" in sql
    assert "extract(second from run_time) = 0" in sql
    assert "extract(minute from run_time) in (0,15,30,45)" in sql
    assert "and run_time < '24:00'" in sql  # PostgreSQL accepts time '24:00'
    assert ("check (not enabled or (run_time is not null and ((frequency = 'weekly' and run_weekday is not null) "
            "or (frequency = 'monthly' and run_day is not null))))") in sql
    # Validated, so an enabled row without a slot fails the migration loudly.
    assert "not valid" not in sql
    # Re-runs replace the predicate instead of keeping a stale one.
    for name in re.findall(r"add constraint (\w+)", sql):
        assert f"drop constraint if exists {name}" in sql


def test_never_rewrites_existing_rows():
    sql = _sql(MIGRATION)
    assert "update public.analysis_schedules" not in sql
    assert "delete from" not in sql


def test_replaces_the_rpc_instead_of_overloading_it():
    sql = _sql(MIGRATION)
    assert f"drop function if exists {OLD_SIGNATURE};" in sql
    assert sql.count("create function") == 1
    definition = _upsert_definition(sql)
    assert ("p_next_due_at timestamptz default null,p_run_weekday smallint default null,"
            "p_run_day smallint default null,p_run_time time default null)") in definition
    assert "security definer set search_path=''" in definition
    assert "perform public.analysis_require_actor(p_company_id,p_chatbot_id,p_actor_user_id);" in definition


def test_slot_arguments_left_null_keep_the_stored_choice():
    definition = _upsert_definition(_sql(MIGRATION))
    for column in ("run_weekday", "run_day", "run_time"):
        assert f"{column}=coalesce(p_{column},existing.{column},excluded.{column})" in definition


def test_pre_070_fallback_records_one_exact_slot():
    # The derived day and time are used together, as if the caller sent them,
    # never a stored day mixed with the derived 09:00.
    definition = _upsert_definition(_sql(MIGRATION))
    assert "p_run_time := due_local::time;" in definition
    assert "p_run_weekday := extract(isodow from due_local)::smallint-1;" in definition
    assert "p_run_day := extract(day from due_local)::smallint;" in definition
    assert "coalesce(v_" not in definition


def test_grants_match_063():
    sql = _sql(MIGRATION)
    assert f"revoke all on function {NEW_SIGNATURE} from public,anon,authenticated;" in sql
    assert f"grant execute on function {NEW_SIGNATURE} to service_role;" in sql
    assert not re.search(r"grant execute[^;]*to[^;]*\b(anon|authenticated|public)\b", sql)


def test_rollback_restores_the_063_function_and_drops_the_slot():
    sql, original = _sql(ROLLBACK), _sql(DATA / "063_agent_analysis.sql")
    assert f"drop function if exists {NEW_SIGNATURE};" in sql
    assert _upsert_definition(original) in sql
    assert f"revoke all on function {OLD_SIGNATURE} from public,anon,authenticated;" in sql
    assert f"grant execute on function {OLD_SIGNATURE} to service_role;" in sql
    for column in ("run_weekday", "run_day", "run_time"):
        assert f"drop column if exists {column}" in sql
    assert sql.startswith("begin;") and sql.endswith("commit;")


# --- opt-in behaviour drill on a throwaway local cluster ---------------------

def _apply(pg, path, *, check=True):
    return pg(path.read_text(encoding="utf-8"), check=check)


def _upsert(pg, args, *, check=True):
    result = pg(f"SELECT analysis_upsert_schedule({args});", role="service_role", check=check)
    return json.loads(result.stdout) if check else result


OLD_CALL = ("p_company_id=>10,p_chatbot_id=>7,p_actor_user_id=>3,p_frequency=>'{frequency}',"
            "p_timezone=>'Asia/Kuala_Lumpur',p_enabled=>{enabled},p_next_due_at=>{next_due}")


@pytest.fixture(scope="module")
def pg070(pg):  # noqa: F811
    # Pre-070 code enables a schedule: 070 must refuse, not invent a slot.
    _upsert(pg, OLD_CALL.format(frequency="weekly", enabled="true", next_due="'2026-09-28T01:00:00Z'"))
    refused = _apply(pg, MIGRATION, check=False)
    _upsert(pg, OLD_CALL.format(frequency="weekly", enabled="false", next_due="NULL"))
    _apply(pg, MIGRATION)
    _apply(pg, MIGRATION)  # idempotent re-run
    pg("DELETE FROM analysis_schedules;")
    return pg, refused


def test_migration_fails_loudly_over_an_enabled_schedule_without_a_slot(pg070):
    _pg, refused = pg070
    assert refused.returncode != 0 and "analysis_schedules_enabled_has_run_slot" in refused.stderr


def test_one_function_remains_and_anon_cannot_call_it(pg070):
    pg, _ = pg070
    assert pg("SELECT count(*) FROM pg_proc WHERE proname='analysis_upsert_schedule';").stdout.strip() == "1"
    denied = pg("SELECT analysis_upsert_schedule(10,7,3,'weekly','Asia/Kuala_Lumpur',false);", role="anon", check=False)
    assert "42501" in denied.stderr


def test_seven_argument_callers_still_work_and_never_wipe_the_slot(pg070):
    pg, _ = pg070
    # Deploy window: old code enables weekly; its next_due_at (Monday 09:00 MYT) names the slot.
    row = _upsert(pg, OLD_CALL.format(frequency="weekly", enabled="true", next_due="'2026-09-28T01:00:00Z'"))
    assert (row["run_weekday"], row["run_day"], row["run_time"]) == (0, None, "09:00:00")
    # New code: the owner picks the last day of the month at 18:15.
    row = _upsert(pg, "10,7,3,'monthly','Asia/Kuala_Lumpur',true,'2026-09-30T10:15:00Z',NULL,0::smallint,'18:15'")
    assert (row["run_day"], row["run_time"]) == (0, "18:15:00")
    # Tick skip (enabled, new next_due_at) and downgrade disable send no slot.
    skipped = _upsert(pg, OLD_CALL.format(frequency="monthly", enabled="true", next_due="'2026-10-31T10:15:00Z'"))
    disabled = _upsert(pg, OLD_CALL.format(frequency="monthly", enabled="false", next_due="NULL"))
    assert (skipped["run_day"], skipped["run_time"]) == (0, "18:15:00")
    assert (disabled["enabled"], disabled["run_day"], disabled["run_time"]) == (False, 0, "18:15:00")
    # An explicit new choice does overwrite.
    changed = _upsert(pg, "10,7,3,'monthly','Asia/Kuala_Lumpur',true,'2026-10-15T01:00:00Z',NULL,15::smallint,'09:00'")
    assert (changed["run_day"], changed["run_time"]) == (15, "09:00:00")


def test_pre_070_enable_over_a_partial_choice_records_its_own_exact_slot(pg070):
    pg, _ = pg070
    # A disabled row may hold a day without a time (Thursday, no time).
    _upsert(pg, "10,9,3,'weekly','Asia/Kuala_Lumpur',false,NULL,3::smallint,NULL,NULL")
    # Old code enables it for Monday 09:00 MYT: the slot is that Monday 09:00,
    # not Thursday 09:00.
    row = _upsert(pg, OLD_CALL.replace("p_chatbot_id=>7", "p_chatbot_id=>9").format(
        frequency="weekly", enabled="true", next_due="'2026-09-28T01:00:00Z'"))
    assert (row["run_weekday"], row["run_time"]) == (0, "09:00:00")
    pg("DELETE FROM analysis_schedules WHERE chatbot_id=9;")


def test_due_schedule_with_a_slot_still_enqueues_once(pg070):
    pg, _ = pg070
    row = _upsert(pg, "10,9,3,'weekly','Asia/Kuala_Lumpur',true,now()-interval '1 minute',3::smallint,NULL,'18:15'")
    call = (f"SELECT analysis_enqueue_schedule(10,9,'{row['id']}','weekly:2026-09-17:2026-09-24',"
            "'{}',now()+interval '7 days');")
    assert json.loads(pg(call, role="service_role").stdout)["enqueued"] is True
    assert json.loads(pg(call, role="service_role").stdout)["enqueued"] is False
    pg("DELETE FROM analysis_schedules WHERE chatbot_id=9;")


@pytest.mark.parametrize("args", [
    "10,9,3,'weekly','Asia/Kuala_Lumpur',true,NULL,3::smallint,NULL,'18:10'",   # not a quarter hour
    "10,9,3,'weekly','Asia/Kuala_Lumpur',true,NULL,3::smallint,NULL,'18:15:30'",
    "10,9,3,'weekly','Asia/Kuala_Lumpur',true,NULL,3::smallint,NULL,'24:00'",   # valid PostgreSQL time
    "10,9,3,'weekly','Asia/Kuala_Lumpur',true,NULL,7::smallint,NULL,'18:15'",   # no eighth weekday
    "10,9,3,'monthly','Asia/Kuala_Lumpur',true,NULL,NULL,29::smallint,'18:15'",
    "10,9,3,'weekly','Asia/Kuala_Lumpur',false,NULL,NULL,15::smallint,NULL",    # day on a weekly row
    "10,9,3,'monthly','Asia/Kuala_Lumpur',true,NULL,NULL,NULL,NULL",            # enabled, no slot
])
def test_bad_slots_are_rejected(pg070, args):
    pg, _ = pg070
    assert "23514" in _upsert(pg, args, check=False).stderr


def test_rollback_restores_063_and_070_reapplies(pg070):
    pg, _ = pg070
    _apply(pg, ROLLBACK)
    assert pg("SELECT count(*) FROM information_schema.columns WHERE table_name='analysis_schedules' "
              "AND column_name LIKE 'run_%';").stdout.strip() == "0"
    assert pg("SELECT pronargs FROM pg_proc WHERE proname='analysis_upsert_schedule';").stdout.strip() == "7"
    # The slot is gone, so enabled rows would (rightly) block 070: disable them
    # through the restored 063 function first.
    for frequency in ("weekly", "monthly"):
        _upsert(pg, OLD_CALL.format(frequency=frequency, enabled="false", next_due="NULL"))
    _apply(pg, MIGRATION)
    assert pg("SELECT pronargs FROM pg_proc WHERE proname='analysis_upsert_schedule';").stdout.strip() == "10"
