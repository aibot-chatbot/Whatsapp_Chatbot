"""data/080 on a throwaway local PostgreSQL cluster (opt-in, like the analysis drill).

Runs with RUN_LOCAL_POSTGRES_TESTS=1; on a non-English Windows locale also set
LANG=C LC_ALL=C LC_MESSAGES=C. The cluster binds loopback only and never sees a
real database. The schema is the repo's own migrations where they exist
(060, 063, 072, 073, 075 and the platform / support tables) plus minimal stubs
with the production foreign-key shapes for the tables this repo has no CREATE
TABLE for. That is what lets these tests prove the delete order against real
RESTRICT / NO ACTION foreign keys and the booking_slots trigger.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from tests.test_analysis_postgres import pg  # noqa: F401  (opt-in throwaway cluster)

DATA = Path(__file__).resolve().parents[1] / "data"

# Tables holding rows seeded for each workspace, with the column that ties them to it.
COMPANY_TABLES = [
    ("users", "company_id"), ("chatbots", "company_id"), ("ai_credit_transactions", "company_id"),
    ("company_ai_credit_balances", "company_id"), ("ai_usage_logs", "company_id"),
    ("billing_notifications", "company_id"), ("invites", "company_id"), ("wasender_channels", "company_id"),
    ("agent_actions", "company_id"), ("crm_leads", "company_id"), ("chatbot_web_widgets", "company_id"),
    ("bot_media_attachments", "company_id"), ("booking_packages", "company_id"),
    ("booking_closures", "company_id"), ("booking_schedules", "company_id"), ("booking_slots", "company_id"),
    ("service_bookings", "company_id"), ("conversation_internal_notes", "company_id"),
    ("conversation_handoff_controls", "company_id"), ("analysis_reports", "company_id"),
    ("analysis_schedules", "company_id"), ("geo_analyses", "company_id"), ("company_subscriptions", "company_id"),
    ("automation_events", "company_id"),
]
CHATBOT_TABLES = [
    ("knowledge_chunks", "chatbot_id"), ("knowledge_graph_nodes", "chatbot_id"),
    ("knowledge_graph_edges", "chatbot_id"), ("conversations", "chatbot_id"),
]

STUBS = """
CREATE TABLE subscription_plans(code text, feature_flags jsonb);
INSERT INTO subscription_plans VALUES ('free','{}'),('essential','{}'),('advanced','{}'),('pro','{}');
ALTER TABLE chatbots ADD COLUMN IF NOT EXISTS booking_intake_enabled boolean NOT NULL DEFAULT false;

ALTER TABLE users ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN email text;
-- Keyed by email, no foreign key (production shape).
CREATE TABLE password_reset_otps(email text PRIMARY KEY, otp_code text);
CREATE TABLE pending_registrations(id bigserial PRIMARY KEY, email text, password_hash text);
ALTER TABLE users ADD CONSTRAINT users_company_fk FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE;
ALTER TABLE chatbots ADD CONSTRAINT chatbots_company_fk FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE;
ALTER TABLE conversations ADD CONSTRAINT conversations_chatbot_fk FOREIGN KEY (chatbot_id) REFERENCES chatbots(id) ON DELETE CASCADE;
ALTER TABLE messages ADD CONSTRAINT messages_conversation_fk FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE;

-- Production shapes the repo has no CREATE TABLE for (verified against pg_constraint).
CREATE TABLE company_subscriptions(id bigserial PRIMARY KEY, company_id bigint NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  payment_gateway text, external_subscription_id text);
CREATE TABLE ai_credit_transactions(id bigserial PRIMARY KEY, company_id bigint NOT NULL REFERENCES companies(id),
  subscription_id bigint REFERENCES company_subscriptions(id));
CREATE TABLE company_ai_credit_balances(id bigserial PRIMARY KEY, company_id bigint NOT NULL REFERENCES companies(id),
  subscription_id bigint REFERENCES company_subscriptions(id));
CREATE TABLE ai_credit_topup_orders(id bigserial PRIMARY KEY, company_id bigint NOT NULL REFERENCES companies(id),
  created_by_user_id bigint NOT NULL REFERENCES users(id) ON DELETE RESTRICT);
CREATE TABLE company_subscription_orders(id bigserial PRIMARY KEY, company_id bigint, created_by_user_id bigint);
CREATE TABLE ai_usage_logs(id bigserial PRIMARY KEY, company_id bigint, chatbot_id bigint, user_id bigint);
CREATE TABLE billing_notifications(id bigserial PRIMARY KEY, company_id bigint);
CREATE TABLE invites(id bigserial PRIMARY KEY, company_id bigint);
CREATE TABLE wasender_channels(id bigserial PRIMARY KEY, company_id bigint, chatbot_id bigint);
CREATE TABLE agent_actions(id bigserial PRIMARY KEY, company_id bigint, chatbot_id bigint);
CREATE TABLE crm_leads(id bigserial PRIMARY KEY, company_id bigint, chatbot_id bigint);
CREATE TABLE chatbot_web_widgets(id bigserial PRIMARY KEY, company_id bigint, chatbot_id bigint REFERENCES chatbots(id) ON DELETE CASCADE);
CREATE TABLE bot_media_attachments(id bigserial PRIMARY KEY, company_id bigint, chatbot_id bigint REFERENCES chatbots(id) ON DELETE CASCADE);
CREATE TABLE knowledge_chunks(id bigserial PRIMARY KEY, chatbot_id bigint);
CREATE TABLE knowledge_graph_nodes(id bigserial PRIMARY KEY, chatbot_id bigint);
CREATE TABLE knowledge_graph_edges(id bigserial PRIMARY KEY, chatbot_id bigint);
"""

PLATFORM = """
CREATE TABLE platform_admin_users(id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  user_id bigint NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
  created_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL);
CREATE TABLE platform_admin_protected_companies(company_id bigint PRIMARY KEY REFERENCES companies(id) ON DELETE RESTRICT);
CREATE TABLE platform_approval_requests(id bigserial PRIMARY KEY, company_id bigint NOT NULL REFERENCES companies(id) ON DELETE RESTRICT);
"""


@pytest.fixture(scope="module")
def db(pg):
    """The shared cluster plus the production-shaped schema this drill needs."""
    pg(STUBS)
    for name in ("060_handoff_control_persistence.sql", "072_service_bookings.sql", "073_availability_booking.sql",
                 "075_geo_analysis.sql"):
        pg((DATA / name).read_text(encoding="utf-8"))
    pg(PLATFORM)
    # Support tables: the repo's own DDL needs platform_admin_users (above) and the cases table.
    for name in ("029_create_platform_admin_support_cases.sql", "030_create_tenant_support_requests.sql",
                 "031_tenant_support_review_conversion.sql", "033_platform_admin_tenant_communication.sql"):
        pg((DATA / name).read_text(encoding="utf-8"))
    pg((DATA / "080_self_service_account_deletion.sql").read_text(encoding="utf-8"))
    return pg


def seed(company, tag=""):
    """One complete workspace: ids derive from the company id so workspaces never collide."""
    c = company
    owner, member = c * 100 + 1, c * 100 + 2
    bot1, bot2 = c * 100 + 11, c * 100 + 12
    return f"""
    INSERT INTO companies(id) VALUES ({c});
    INSERT INTO users(id, company_id, status, role, created_at, email) VALUES
      ({owner}, {c}, 'active', 'admin', now() - interval '3 days', 'owner{c}@example.test'),
      ({member}, {c}, 'active', 'member', now() - interval '1 day', 'member{c}@example.test');
    -- email-keyed leftovers; mixed case and padding must still match
    INSERT INTO password_reset_otps(email, otp_code) VALUES (' Owner{c}@Example.TEST', '111111');
    INSERT INTO pending_registrations(email, password_hash) VALUES ('member{c}@example.test', 'h');
    -- company-level rows with no chatbot: only the company_id deletes can reach them
    INSERT INTO ai_usage_logs(company_id, chatbot_id) VALUES ({c}, NULL);
    INSERT INTO wasender_channels(company_id, chatbot_id) VALUES ({c}, NULL);
    INSERT INTO chatbots(id, company_id, status) VALUES ({bot1}, {c}, 'active'), ({bot2}, {c}, 'archived');
    INSERT INTO conversations(id, chatbot_id) VALUES ({c * 100 + 21}, {bot1}), ({c * 100 + 22}, {bot2});
    INSERT INTO messages(id, conversation_id, actor_user_id) VALUES ({c * 100 + 31}, {c * 100 + 21}, {member});
    INSERT INTO company_subscriptions(id, company_id) VALUES ({c}, {c});
    INSERT INTO ai_credit_transactions(company_id, subscription_id) VALUES ({c}, {c});
    INSERT INTO company_ai_credit_balances(company_id, subscription_id) VALUES ({c}, {c});
    INSERT INTO ai_usage_logs(company_id, chatbot_id, user_id) VALUES ({c}, {bot1}, {member}), (NULL, {bot2}, NULL);
    INSERT INTO billing_notifications(company_id) VALUES ({c});
    INSERT INTO invites(company_id) VALUES ({c});
    INSERT INTO wasender_channels(company_id, chatbot_id) VALUES ({c}, {bot1}), (NULL, {bot2});
    INSERT INTO agent_actions(company_id, chatbot_id) VALUES ({c}, {bot1});
    INSERT INTO crm_leads(company_id, chatbot_id) VALUES ({c}, {bot1});
    INSERT INTO chatbot_web_widgets(company_id, chatbot_id) VALUES ({c}, {bot1});
    INSERT INTO bot_media_attachments(company_id, chatbot_id) VALUES ({c}, {bot1});
    INSERT INTO knowledge_chunks(chatbot_id) VALUES ({bot1}), ({bot2});
    INSERT INTO knowledge_graph_nodes(chatbot_id) VALUES ({bot1});
    INSERT INTO knowledge_graph_edges(chatbot_id) VALUES ({bot1});
    -- availability booking, with a slot that already holds seats (its trigger refuses a direct delete)
    INSERT INTO booking_packages(id, company_id, chatbot_id, name, duration_minutes) VALUES ({c}, {c}, {bot1}, 'Cut', 30);
    INSERT INTO booking_schedules(company_id, chatbot_id, package_id, weekday, start_time, end_time, interval_minutes)
      VALUES ({c}, {bot1}, {c}, 1, '09:00', '17:00', 30);
    INSERT INTO booking_closures(company_id, chatbot_id, package_id, closed_on) VALUES ({c}, {bot1}, {c}, '2030-01-01');
    INSERT INTO booking_slots(id, company_id, chatbot_id, package_id, starts_at, ends_at, capacity)
      VALUES ({c}, {c}, {bot1}, {c}, now() + interval '1 day', now() + interval '1 day 30 minutes', 4);
    UPDATE booking_slots SET booked_seats = 2 WHERE id = {c};
    INSERT INTO service_bookings(company_id, chatbot_id, conversation_id, intake_key, package_id, slot_id, seats)
      VALUES ({c}, {bot1}, {c * 100 + 21}, 'k{c}', {c}, {c}, 2);
    -- the RESTRICT-to-users tables
    INSERT INTO conversation_internal_notes(conversation_id, company_id, author_user_id, note_text)
      VALUES ({c * 100 + 21}, {c}, {member}, 'note');
    INSERT INTO conversation_handoff_controls(conversation_id, company_id, chatbot_id, handling_mode, assignee_user_id)
      VALUES ({c * 100 + 21}, {c}, {bot1}, 'human_active', {member});
    INSERT INTO automation_events(id, company_id, chatbot_id, event_type, idempotency_key)
      VALUES ({c}, {c}, {bot1}, 'knowledge_document_follow_up', 'e{c}');
    INSERT INTO analysis_reports(company_id, chatbot_id, actor_user_id, client_message_id, request_text, automation_event_id)
      VALUES ({c}, {bot1}, {member}, 'm{c}', 'how are sales', {c});
    INSERT INTO analysis_schedules(company_id, chatbot_id, actor_user_id, frequency) VALUES ({c}, {bot1}, {member}, 'weekly');
    INSERT INTO geo_analyses(company_id, actor_user_id, plan_code, execution_count, brand_name, country, language,
        platforms, prompts, samples_per_prompt)
      VALUES ({c}, {member}, 'pro', 1, 'Acme', 'MY', 'en', '[]', '[]', 1);
    INSERT INTO account_deletion_codes(user_id, code_hash, expires_at) VALUES ({owner}, 'h', now() + interval '10 minutes');
    {tag}
    """


def call(db, company, user, *, role="service_role", check=True):
    result = db(f"SELECT public.delete_company_account({company}, {user});", role=role, check=check)
    return json.loads(result.stdout.strip()) if check else result


def count(db, table, column, values):
    ids = ",".join(str(v) for v in values)
    return int(db(f"SELECT count(*) FROM {table} WHERE {column} IN ({ids});").stdout.strip())


def snapshot(db, company):
    """Row counts for one workspace across every seeded table, in a single round trip."""
    bots = f"{company * 100 + 11},{company * 100 + 12}"
    users = f"{company * 100 + 1},{company * 100 + 2}"
    counts = {f"{t}": f"SELECT count(*) FROM {t} WHERE {c} IN ({company})" for t, c in COMPANY_TABLES}
    counts.update({t: f"SELECT count(*) FROM {t} WHERE {c} IN ({bots})" for t, c in CHATBOT_TABLES})
    emails = f"'owner{company}@example.test','member{company}@example.test'"
    counts.update({
        "reset_codes": f"SELECT count(*) FROM password_reset_otps WHERE lower(btrim(email)) IN ({emails})",
        "pending_signups": f"SELECT count(*) FROM pending_registrations WHERE lower(btrim(email)) IN ({emails})",
        "messages": f"SELECT count(*) FROM messages WHERE actor_user_id IN ({users})",
        "ai_usage_logs_by_bot": f"SELECT count(*) FROM ai_usage_logs WHERE chatbot_id IN ({bots})",
        "wasender_by_bot": f"SELECT count(*) FROM wasender_channels WHERE chatbot_id IN ({bots})",
        "codes": f"SELECT count(*) FROM account_deletion_codes WHERE user_id IN ({users})",
        "company": f"SELECT count(*) FROM companies WHERE id = {company}",
    })
    body = ", ".join(f"'{name}', ({query})" for name, query in counts.items())
    return json.loads(db(f"SELECT json_build_object({body});").stdout.strip())


def test_the_owner_deletes_the_whole_workspace_and_only_that_workspace(db):
    db(seed(1) + seed(2))
    before_other = snapshot(db, 2)
    assert all(before_other.values()), before_other
    assert snapshot(db, 1)["booking_slots"] == 1

    result = call(db, 1, 101)

    assert result["status"] == "success" and result["code"] == "deleted"
    assert result["deleted_counts"] == {"users": 2, "chatbots": 2}
    assert sorted(result["chatbot_ids"]) == [111, 112]
    assert not any(snapshot(db, 1).values()), snapshot(db, 1)
    assert snapshot(db, 2) == before_other, "another workspace must be untouched"


def test_a_slot_that_holds_seats_is_the_reason_packages_go_first(db):
    db(seed(3))
    refused = db("DELETE FROM booking_slots WHERE id = 3;", check=False)
    assert refused.returncode != 0 and "booking_slot_has_bookings" in refused.stderr

    assert call(db, 3, 301)["status"] == "success"
    assert snapshot(db, 3)["booking_slots"] == 0


def test_a_member_cannot_delete_and_nothing_changes(db):
    db(seed(4))
    before = snapshot(db, 4)

    result = call(db, 4, 402)

    assert result == {"status": "error", "code": "not_owner", "message": "Workspace cannot be deleted (not_owner)"}
    assert snapshot(db, 4) == before


def test_the_owner_is_the_registrant_and_another_admin_cannot_take_over(db):
    db(seed(5, "UPDATE users SET role = 'admin' WHERE id = 502;"))
    assert call(db, 5, 502)["code"] == "not_owner", "a second admin is not the owner"

    # The takeover: the second admin deactivates, then demotes, the registrant.
    db("UPDATE users SET status = 'inactive' WHERE id = 501;")
    assert call(db, 5, 502)["code"] == "not_owner", "deactivating the registrant must not hand over the right"
    assert call(db, 5, 501)["code"] == "not_owner", "an inactive registrant cannot delete either"
    db("UPDATE users SET status = 'active', role = 'member' WHERE id = 501;")
    assert call(db, 5, 502)["code"] == "not_owner", "nor must demoting the registrant"
    assert call(db, 5, 501)["code"] == "not_owner", "a demoted registrant cannot delete"
    assert snapshot(db, 5)["company"] == 1

    db("UPDATE users SET role = 'admin' WHERE id = 501;")
    assert call(db, 5, 501)["status"] == "success", "restored to admin, the registrant can delete again"


def test_a_user_from_another_company_or_a_missing_company_is_not_found(db):
    db(seed(6) + seed(7))

    assert call(db, 6, 701)["code"] == "not_found"
    assert call(db, 999, 701)["code"] == "not_found"
    assert call(db, 6, 424242)["code"] == "not_found"
    assert snapshot(db, 6)["company"] == 1


def test_null_arguments_are_an_error_result(db):
    assert json.loads(db("SELECT public.delete_company_account(NULL, 1);", role="service_role").stdout)["code"] == "invalid_request"
    assert json.loads(db("SELECT public.delete_company_account(1, NULL);", role="service_role").stdout)["code"] == "invalid_request"


BLOCKS = [
    ("payment_history", lambda c, o, m: f"INSERT INTO ai_credit_topup_orders(company_id, created_by_user_id) VALUES ({c}, {o});"),
    ("payment_history", lambda c, o, m: f"INSERT INTO company_subscription_orders(company_id, created_by_user_id) VALUES ({c}, {o});"),
    ("payment_history", lambda c, o, m: f"UPDATE company_subscriptions SET payment_gateway = 'chip' WHERE company_id = {c};"),
    ("payment_history", lambda c, o, m: f"UPDATE company_subscriptions SET external_subscription_id = 'sub_1' WHERE company_id = {c};"),
    ("protected", lambda c, o, m: f"INSERT INTO platform_admin_protected_companies(company_id) VALUES ({c});"),
    ("protected", lambda c, o, m: f"INSERT INTO platform_admin_users(user_id) VALUES ({m});"),
    ("support_records", lambda c, o, m: f"INSERT INTO platform_approval_requests(company_id) VALUES ({c});"),
    ("support_records", lambda c, o, m: "INSERT INTO tenant_support_requests(company_id, requester_user_id, category, title, "
                                       f"redacted_description) VALUES ({c}, {m}, 'other', 't', 'd');"),
    ("support_records", lambda c, o, m: "INSERT INTO tenant_support_audit_events(company_id, requester_user_id, action, outcome) "
                                       f"VALUES ({c}, {o}, 'support.request', 'denied');"),
]


@pytest.mark.parametrize("index", range(len(BLOCKS)))
def test_every_block_reason_refuses_and_deletes_nothing(db, index):
    reason, extra = BLOCKS[index]
    company = 60 + index
    owner, member = company * 100 + 1, company * 100 + 2
    db(seed(company, extra(company, owner, member)))
    before = snapshot(db, company)

    result = call(db, company, owner)

    assert result["status"] == "error" and result["code"] == reason, result
    assert snapshot(db, company) == before


def test_support_events_alone_also_block(db):
    db(seed(75) + seed(76))
    # The request belongs to another workspace, but this workspace's member wrote an event on it.
    db("INSERT INTO tenant_support_requests(id, company_id, requester_user_id, category, title, redacted_description) "
       "VALUES (9001, 76, 7601, 'other', 't', 'd');"
       "INSERT INTO tenant_support_request_events(request_id, event_type, actor_user_id, actor_type) "
       "VALUES (9001, 'created', 7502, 'tenant');")

    assert call(db, 75, 7501)["code"] == "support_records"


def test_a_future_table_without_a_foreign_key_makes_the_deletion_fail_safe(db):
    db(seed(30))
    db("CREATE TABLE future_by_company(company_id integer); CREATE TABLE future_by_bot(chatbot_id bigint);"
       "CREATE TABLE future_by_user(author_user_id bigint); CREATE TABLE future_by_name(user_id text);"
       "INSERT INTO future_by_company VALUES (30);")
    before = snapshot(db, 30)
    try:
        failed = call(db, 30, 3001, check=False)
        assert failed.returncode != 0
        assert "account_deletion_incomplete" in failed.stderr and "future_by_company.company_id" in failed.stderr
        assert snapshot(db, 30) == before, "the whole deletion rolls back"

        db("DELETE FROM future_by_company; INSERT INTO future_by_bot VALUES (3011);")
        assert "future_by_bot.chatbot_id" in call(db, 30, 3001, check=False).stderr
        db("DELETE FROM future_by_bot; INSERT INTO future_by_user VALUES (3002);")
        assert "future_by_user.author_user_id" in call(db, 30, 3001, check=False).stderr
        assert snapshot(db, 30) == before

        # A text column that merely shares a name is not an id and must not block anyone.
        db("DELETE FROM future_by_user; INSERT INTO future_by_name VALUES ('3002');")
        assert call(db, 30, 3001)["status"] == "success"
    finally:
        db("DROP TABLE future_by_company, future_by_bot, future_by_user, future_by_name;")


def test_payment_rows_that_appear_after_the_guard_are_never_deleted(db):
    """company_subscription_orders has no foreign key: a checkout can land after the guard.
    The function must roll back rather than delete it. Simulated by making the row appear
    mid-call through a trigger on the table the function deletes just before."""
    db(seed(31))
    db("""
    CREATE FUNCTION race_payment() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN INSERT INTO company_subscription_orders(company_id, created_by_user_id) VALUES (31, 3101); RETURN OLD; END $$;
    CREATE TRIGGER race_payment AFTER DELETE ON billing_notifications FOR EACH ROW EXECUTE FUNCTION race_payment();
    """)
    before = snapshot(db, 31)
    try:
        failed = call(db, 31, 3101, check=False)
        assert failed.returncode != 0 and "company_subscription_orders.company_id" in failed.stderr
        assert snapshot(db, 31) == before
        assert count(db, "company_subscription_orders", "company_id", [31]) == 0, "rolled back with the rest"
    finally:
        db("DROP TRIGGER race_payment ON billing_notifications; DROP FUNCTION race_payment();")


def test_two_simultaneous_deletions_delete_once(db):
    db(seed(40))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(db, 40, 4001), range(2)))

    assert sorted(r["code"] for r in results) == ["deleted", "not_found"]
    assert snapshot(db, 40)["company"] == 0


def test_the_blocker_is_readable_on_its_own(db):
    db(seed(41))

    def blocker(company, user):
        return db(f"SELECT coalesce(public.account_deletion_blocker({company}, {user}), 'ELIGIBLE');",
                  role="service_role").stdout.strip()

    assert blocker(41, 4101) == "ELIGIBLE"
    assert blocker(41, 4102) == "not_owner"
    assert blocker(41, 1) == "not_found"


def test_only_the_service_role_can_run_or_read_any_of_it(db):
    db(seed(50))
    for role in ("anon", "authenticated"):
        for statement in (
            "SELECT public.delete_company_account(50, 5001);",
            "SELECT public.account_deletion_blocker(50, 5001);",
            "SELECT * FROM public.account_deletion_codes;",
            "INSERT INTO public.account_deletion_codes(user_id, code_hash, expires_at) VALUES (5002, 'x', now());",
            "DELETE FROM public.account_deletion_codes;",
        ):
            denied = db(statement, role=role, check=False)
            assert denied.returncode != 0 and "permission denied" in denied.stderr, (role, statement, denied.stderr)
    assert snapshot(db, 50)["company"] == 1

    ok = db("SELECT count(*) FROM public.account_deletion_codes WHERE user_id = 5001;", role="service_role")
    assert ok.stdout.strip() == "1"
    assert db("UPDATE public.account_deletion_codes SET attempts = attempts + 1 WHERE user_id = 5001;",
              role="service_role").returncode == 0


def test_the_code_row_goes_with_its_user_and_the_table_rejects_negative_attempts(db):
    db(seed(51))
    bad = db("UPDATE account_deletion_codes SET attempts = -1 WHERE user_id = 5101;", check=False)
    assert bad.returncode != 0

    assert call(db, 51, 5101)["status"] == "success"
    assert count(db, "account_deletion_codes", "user_id", [5101, 5102]) == 0
