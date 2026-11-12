"""data/080: the confirmation-code table and the whole-workspace deletion functions.

Text assertions only; tests/test_account_deletion_postgres.py runs the same SQL
on a throwaway local cluster (opt-in). These pin the properties that cannot be
allowed to drift: the lock-down of the new objects, every guard, the delete
list and its order, and the post-delete orphan check.
"""

from pathlib import Path
import re

DATA = Path(__file__).resolve().parents[1] / "data"
MIGRATION = DATA / "080_self_service_account_deletion.sql"
ROLLBACK = DATA / "080_self_service_account_deletion_rollback.sql"

# Public tables that, in production, carry company_id / chatbot_id with NO
# foreign key (verified against pg_constraint on 2026-10-17). A cascade from
# companies/chatbots never reaches them, so the function must delete them.
NO_FK_COMPANY_TABLES = {
    "agent_actions", "ai_usage_logs", "billing_notifications", "booking_closures", "booking_schedules",
    "booking_slots", "bot_media_attachments", "chatbot_web_widgets", "company_subscription_orders",
    "crm_leads", "invites", "wasender_channels",
}
NO_FK_CHATBOT_TABLES = {
    "ai_usage_logs", "booking_schedules", "booking_slots", "knowledge_chunks", "knowledge_graph_edges",
    "knowledge_graph_nodes", "wasender_channels",
}
# NO ACTION foreign keys to companies/company_subscriptions: they block the final delete.
CREDIT_TABLES = ["ai_credit_transactions", "company_ai_credit_balances"]
# Company-scoped rows whose foreign key to users is ON DELETE RESTRICT (checked immediately).
RESTRICT_TO_USERS_TABLES = [
    "conversation_internal_notes", "conversation_handoff_controls", "analysis_reports",
    "analysis_schedules", "geo_analyses",
]
# Payment history is refused, never deleted (see test_payment_tables_are_never_deleted...).
PAYMENT_TABLES = {"ai_credit_topup_orders", "company_subscription_orders"}
# Retained platform records: a workspace holding any of them is never deleted, and never has them deleted.
RETAINED_TABLES = [
    "platform_approval_requests", "platform_support_cases", "tenant_support_requests", "tenant_support_replies",
    "tenant_support_reply_notifications", "tenant_support_audit_events", "tenant_support_request_events",
]
USER_REFERENCE_COLUMNS = [
    "user_id", "actor_user_id", "author_user_id", "assignee_user_id", "requester_user_id", "created_by_user_id",
]


def _sql(path):
    text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    return re.sub(r"\s+", " ", text).lower().replace(" ,", ",").replace(", ", ",").replace("( ", "(").replace(" )", ")").strip()


def _function(sql, name):
    match = re.search(r"create or replace function public\.%s\(.*?\$function\$;" % name, sql)
    assert match, name
    return match.group(0)


def _deletes(body):
    """(table, where-clause) for every DELETE in a function body, in order."""
    return re.findall(r"delete from public\.(\w+) where ([^;]+);", body)


def _delete_order(body, table, column=None):
    for index, (name, clause) in enumerate(_deletes(body)):
        if name == table and (column is None or clause.startswith(column)):
            return index
    raise AssertionError(f"no delete of {table} by {column}")


def test_migration_and_rollback_exist_and_are_single_transactions():
    for path in (MIGRATION, ROLLBACK):
        sql = _sql(path)
        assert sql.startswith("begin;") and sql.endswith("commit;"), path.name
        assert "set local lock_timeout" in sql and "set local statement_timeout" in sql, path.name


def test_it_does_nothing_to_existing_rows_when_applied():
    sql = _sql(MIGRATION)
    outside_functions = re.sub(r"\$function\$.*?\$function\$", "", sql)

    for verb in ("delete from", "insert into", "update public.", "truncate", "drop table"):
        assert verb not in outside_functions, verb


# ------------------------------------------------------------------ code table

def test_the_code_table_is_its_own_table_keyed_by_user_and_cascading():
    sql = _sql(MIGRATION)

    assert "create table if not exists public.account_deletion_codes(" in sql
    for column in (
        "user_id bigint primary key references public.users(id) on delete cascade",
        "code_hash text not null",
        "expires_at timestamptz not null",
        "attempts integer not null default 0",
        "created_at timestamptz not null default now()",
    ):
        assert column in sql, column


def test_the_code_table_never_stores_a_plain_code_and_is_not_a_login_or_reset_code():
    sql = _sql(MIGRATION)
    table = re.search(r"create table if not exists public\.account_deletion_codes\(.*?\);", sql).group(0)

    assert "code_hash" in table
    for forbidden in ("otp_code", "password_reset_otps", " code text", "plain"):
        assert forbidden not in table, forbidden
    assert "users.otp_code" not in sql
    # password_reset_otps is only ever deleted from (the deleted people's leftovers), never read as a code.
    assert re.findall(r"public\.password_reset_otps\b[^;]*", _function(sql, "delete_company_account")) == [
        "public.password_reset_otps where lower(btrim(email)) = any(v_emails)"]


def test_the_code_table_is_locked_to_the_service_role():
    sql = _sql(MIGRATION)

    assert "alter table public.account_deletion_codes enable row level security;" in sql
    assert "revoke all on public.account_deletion_codes from public,anon,authenticated,service_role;" in sql
    assert "grant select,insert,update,delete on public.account_deletion_codes to service_role;" in sql
    assert not re.search(r"grant [^;]* to [^;]*\b(anon|authenticated|public)\b", sql)


# -------------------------------------------------------------------- functions

def test_both_functions_are_security_definer_with_a_pinned_search_path():
    sql = _sql(MIGRATION)

    delete = _function(sql, "delete_company_account")
    blocker = _function(sql, "account_deletion_blocker")
    assert "(p_company_id bigint,p_user_id bigint) returns jsonb" in delete
    assert "(p_company_id bigint,p_user_id bigint) returns text" in blocker
    for body in (delete, blocker):
        assert "security definer" in body
        assert "set search_path to 'public'" in body


def test_both_functions_are_executable_by_the_service_role_only():
    sql = _sql(MIGRATION)

    for name in ("delete_company_account", "account_deletion_blocker"):
        signature = f"public.{name}(bigint,bigint)"
        assert f"revoke all on function {signature} from public,anon,authenticated;" in sql
        assert f"grant execute on function {signature} to service_role;" in sql
    assert not re.search(r"grant execute[^;]* to [^;]*\b(anon|authenticated|public)\b", sql)


# ----------------------------------------------------------------------- guards

def test_the_owner_is_the_registrant_and_only_while_still_an_active_admin():
    blocker = _function(_sql(MIGRATION), "account_deletion_blocker")

    assert "'not_found'" in blocker and "'not_owner'" in blocker
    # The registrant query must not filter by role or status: with "earliest ACTIVE admin" a second
    # admin could deactivate or demote the registrant and become the one allowed to delete.
    assert ("select u.id from public.users u where u.company_id = p_company_id "
            "order by u.created_at asc,u.id asc limit 1") in blocker
    assert ("from public.users u where u.id = p_user_id and u.role in ('admin','owner') "
            "and u.status = 'active'") in blocker
    assert blocker.index("'not_found'") < blocker.index("'not_owner'") < blocker.index("'protected'")


def test_the_blocker_refuses_protected_companies_and_platform_staff():
    blocker = _function(_sql(MIGRATION), "account_deletion_blocker")

    assert "from public.platform_admin_protected_companies where company_id = p_company_id" in blocker
    assert "from public.platform_admin_users where user_id = any(v_user_ids)" in blocker
    assert blocker.index("'protected'") < blocker.index("'payment_history'") < blocker.index("'support_records'")


def test_the_blocker_refuses_any_payment_history():
    blocker = _function(_sql(MIGRATION), "account_deletion_blocker")

    assert "from public.ai_credit_topup_orders where company_id = p_company_id" in blocker
    assert "from public.company_subscription_orders where company_id = p_company_id" in blocker
    assert ("from public.company_subscriptions where company_id = p_company_id and "
            "(payment_gateway is not null or external_subscription_id is not null)") in blocker


def test_the_blocker_refuses_every_retained_platform_record():
    blocker = _function(_sql(MIGRATION), "account_deletion_blocker")

    for table in RETAINED_TABLES:
        assert f"public.{table}" in blocker, table
    # Events carry no company_id; they are matched through the people being deleted.
    assert "public.tenant_support_request_events where actor_user_id = any(v_user_ids)" in blocker
    assert "public.tenant_support_audit_events where company_id = p_company_id or requester_user_id = any(v_user_ids)" in blocker


def test_the_delete_function_rechecks_every_guard_under_a_company_lock():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    lock = delete.index("from public.companies where id = p_company_id for update")
    people = delete.index("from public.users where company_id = p_company_id order by id for update")
    check = delete.index("public.account_deletion_blocker(p_company_id,p_user_id)")
    first_delete = delete.index("delete from")
    assert lock < people < check < first_delete, "lock the company and its people, then re-check, then delete"
    assert "v_blocker is not null" in delete
    assert "'status','error'" in delete and "'code',v_blocker" in delete


def test_missing_arguments_are_an_error_not_an_exception():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    assert "p_company_id is null or p_user_id is null" in delete
    assert "'invalid_request'" in delete


# ------------------------------------------------------------------ delete list

def test_every_no_fk_table_is_deleted_by_company_id_and_by_chatbot_id():
    delete = _function(_sql(MIGRATION), "delete_company_account")
    by_company = {t for t, clause in _deletes(delete) if clause.startswith("company_id = p_company_id")}
    by_chatbot = {t for t, clause in _deletes(delete) if clause.startswith("chatbot_id = any(v_chatbot_ids)")}

    assert NO_FK_COMPANY_TABLES - PAYMENT_TABLES <= by_company
    assert NO_FK_CHATBOT_TABLES <= by_chatbot


def test_payment_tables_are_never_deleted_the_orphan_check_guards_them_instead():
    """company_subscription_orders has no foreign key, so a checkout inserted after the guard
    ran is not serialised by the company lock. Deleting it would destroy a payment record;
    leaving it makes the orphan check roll the deletion back."""
    delete = _function(_sql(MIGRATION), "delete_company_account")

    assert {t for t, _ in _deletes(delete)}.isdisjoint(PAYMENT_TABLES)
    assert "company_subscription_orders" in NO_FK_COMPANY_TABLES, "still covered by the orphan check"


def test_the_apply_time_table_check_lists_every_table_the_functions_touch():
    sql = _sql(MIGRATION)
    functions = _function(sql, "account_deletion_blocker") + _function(sql, "delete_company_account")
    touched = set(re.findall(r"(?:from|join) public\.(\w+)", functions)) - {"account_deletion_codes"}
    declared = set(re.findall(r"'(\w+)'", re.search(r"unnest\(array\[(.*?)\]\)", sql).group(1)))

    assert touched == declared, (touched ^ declared)
    assert "to_regclass('public.' || t) is null" in sql


def test_credit_tables_go_first_because_their_foreign_keys_block_the_company_delete():
    delete = _function(_sql(MIGRATION), "delete_company_account")
    order = [t for t, _ in _deletes(delete)]

    assert order[:2] == CREDIT_TABLES


def test_graph_edges_go_before_graph_nodes():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    assert _delete_order(delete, "knowledge_graph_edges") < _delete_order(delete, "knowledge_graph_nodes")


def test_booked_slots_are_deleted_through_their_packages_never_directly_first():
    """booking_slots_keep_booked refuses a direct DELETE of a slot holding seats
    (trigger depth 1); a cascade from booking_packages runs at depth 2 and is allowed."""
    delete = _function(_sql(MIGRATION), "delete_company_account")

    packages = _delete_order(delete, "booking_packages", "company_id")
    for index, (table, _) in enumerate(_deletes(delete)):
        if table == "booking_slots":
            assert packages < index


def test_restrict_to_users_tables_are_deleted_explicitly_before_the_company():
    delete = _function(_sql(MIGRATION), "delete_company_account")
    company = _delete_order(delete, "companies")

    for table in RESTRICT_TO_USERS_TABLES:
        assert _delete_order(delete, table, "company_id = p_company_id") < company, table


def test_chatbots_then_company_are_the_last_deletes():
    delete = _function(_sql(MIGRATION), "delete_company_account")
    order = [(t, c) for t, c in _deletes(delete)]

    assert order[-2][0] == "chatbots" and order[-2][1].startswith("company_id = p_company_id")
    assert order[-1] == ("companies", "id = p_company_id")


def test_retained_platform_records_are_never_deleted():
    delete = _function(_sql(MIGRATION), "delete_company_account")
    deleted = {t for t, _ in _deletes(delete)}

    assert deleted.isdisjoint(RETAINED_TABLES)
    assert deleted.isdisjoint({"platform_admin_users", "platform_admin_protected_companies",
                               "platform_admin_audit_events", "ai_credit_topup_orders"})
    assert " cascade" not in delete and "truncate" not in delete


# -------------------------------------------------------------------- post-check

def test_a_dynamic_orphan_check_runs_after_the_last_delete_and_aborts_the_transaction():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    assert delete.index("delete from public.companies") < delete.index("pg_catalog.pg_attribute")
    assert "cls.relkind in ('r','p')" in delete
    assert "cls.relnamespace = 'public'::regnamespace" in delete
    assert "raise exception 'account_deletion_incomplete" in delete
    assert delete.index("raise exception 'account_deletion_incomplete") < delete.rindex("'status','success'")


def test_the_orphan_check_covers_company_chatbot_and_user_reference_columns():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    for column in ["company_id", "chatbot_id", *USER_REFERENCE_COLUMNS]:
        assert f"'{column}'" in delete, column
    # Ids are bigint; an int[] parameter would raise "operator does not exist: bigint = integer".
    assert "v_chatbot_ids bigint[]" in delete and "v_user_ids bigint[]" in delete
    assert "array[p_company_id]::bigint[]" in delete
    assert "att.atttypid in ('int8'::regtype,'int4'::regtype,'int2'::regtype)" in delete
    assert "= any($1)" in delete


def test_the_orphan_check_skips_only_columns_already_guarded_by_a_foreign_key():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    assert "and not exists (select 1 from pg_catalog.pg_constraint k where k.contype = 'f'" in delete
    assert ("k.confrelid in ('public.companies'::regclass,'public.chatbots'::regclass,"
            "'public.users'::regclass)") in delete


def test_the_deleted_peoples_email_keyed_rows_go_too():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    assert "array_agg(lower(btrim(email))) filter (where email is not null)" in delete
    for table in ("password_reset_otps", "pending_registrations"):
        assert _delete_order(delete, table, "lower(btrim(email)) = any(v_emails)") < _delete_order(delete, "chatbots")


def test_messages_actor_user_id_is_indexed_for_the_restrict_check():
    sql = _sql(MIGRATION)

    assert ("create index if not exists messages_actor_user_id_idx on public.messages (actor_user_id) "
            "where actor_user_id is not null;") in sql


def test_success_reports_what_was_removed():
    delete = _function(_sql(MIGRATION), "delete_company_account")

    assert "'status','success'" in delete and "'code','deleted'" in delete
    assert "'deleted_counts'" in delete
    assert "'chatbot_ids',to_jsonb(v_chatbot_ids)" in delete


# ---------------------------------------------------------------------- rollback

def test_rollback_removes_exactly_what_the_migration_adds():
    sql = _sql(ROLLBACK)

    assert "drop function if exists public.delete_company_account(bigint,bigint);" in sql
    assert "drop function if exists public.account_deletion_blocker(bigint,bigint);" in sql
    assert "drop table if exists public.account_deletion_codes;" in sql
    assert "drop index if exists public.messages_actor_user_id_idx;" in sql
    assert "delete from" not in sql and "cascade" not in sql
    assert sql.index("drop function if exists public.delete_company_account") < sql.index(
        "drop function if exists public.account_deletion_blocker")
