import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_ROOT / "data" / "027_harden_crm_agent_actions.sql"
STATUS_MIGRATION_PATH = (
    PROJECT_ROOT / "data" / "047_widen_crm_lead_status_check.sql"
)
PREFLIGHT_PATH = PROJECT_ROOT / "scripts" / "crm_agent_actions_hardening_preflight.sql"
ROLLBACK_PATH = PROJECT_ROOT / "scripts" / "crm_agent_actions_hardening_rollback.sql"
VERIFICATION_PATH = (
    PROJECT_ROOT / "scripts" / "crm_agent_actions_hardening_verification.sql"
)
RUNBOOK_PATH = PROJECT_ROOT / "docs" / "CRM_AGENT_ACTIONS_HARDENING_PHASE_1_5.md"
PERMANENT_DELETE_RPC_PATH = (
    PROJECT_ROOT / "data" / "022_permanently_delete_archived_chatbot_rpc.sql"
)


def _read(path):
    return path.read_text(encoding="utf-8")


def _without_sql_comments(sql):
    without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", without_blocks)


def _top_level_statement_keywords(sql):
    cleaned = _without_sql_comments(sql)
    return [
        match.group(1).lower()
        for match in re.finditer(
            r"(?:^|;)\s*([a-z_]+)",
            cleaned,
            flags=re.IGNORECASE,
        )
    ]


def _literal_assignment(path, name):
    tree = ast.parse(_read(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def _table_names_in_expression(node):
    names = set()
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Call):
            continue
        if not isinstance(candidate.func, ast.Attribute) or candidate.func.attr != "table":
            continue
        if candidate.args and isinstance(candidate.args[0], ast.Constant):
            names.add(candidate.args[0].value)
    return names


def _direct_table_operations(paths):
    operations = {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            operation = node.func.attr
            if operation not in {"select", "insert", "update", "delete"}:
                continue
            for table_name in _table_names_in_expression(node.func.value):
                operations.setdefault(table_name, set()).add(operation)
    return operations


def test_027_keeps_its_selected_migration_number():
    numbered = []
    for path in (PROJECT_ROOT / "data").glob("*.sql"):
        match = re.match(r"^(\d+)_", path.name)
        if match:
            numbered.append((int(match.group(1)), path.name))

    selected = [name for number, name in numbered if number == 27]
    assert selected == ["027_harden_crm_agent_actions.sql"]


def test_preflight_and_verification_are_read_only_select_scripts():
    for path in (PREFLIGHT_PATH, VERIFICATION_PATH):
        keywords = _top_level_statement_keywords(_read(path))
        assert keywords
        assert set(keywords) <= {"select", "with"}


def test_migration_only_backfills_company_from_the_matching_chatbot():
    sql = _without_sql_comments(_read(MIGRATION_PATH))
    normalized = " ".join(sql.split()).lower()

    assert "update public.agent_actions as aa" in normalized
    assert "set company_id = bot.company_id" in normalized
    assert "from public.chatbots as bot" in normalized
    assert "aa.company_id is null" in normalized
    assert "aa.chatbot_id = bot.id" in normalized
    assert not re.search(r"(?im)^\s*(delete|truncate|insert)\b", sql)


def test_migration_fails_closed_for_orphans_and_integrity_mismatches():
    sql = _read(MIGRATION_PATH).lower()

    for required_fragment in (
        "rows reference missing chatbots",
        "rows reference missing conversations",
        "no automatic nulling is permitted",
        "rows still have null company_id",
        "disagree with chatbot company ownership",
        "conversations belong to another chatbot",
        "duplicate open crm lead keys require review",
        "raise exception",
    ):
        assert required_fragment in sql


def test_foreign_keys_are_staged_and_match_delete_behavior():
    sql = " ".join(_read(MIGRATION_PATH).lower().split())

    expected = {
        "agent_actions_chatbot_id_fkey": "on update no action on delete cascade not valid",
        "agent_actions_conversation_id_fkey": "on update no action on delete set null not valid",
        "crm_leads_chatbot_id_fkey": "on update no action on delete cascade not valid",
        "crm_leads_conversation_id_fkey": "on update no action on delete set null not valid",
    }
    for constraint_name, action_fragment in expected.items():
        assert f"add constraint {constraint_name}" in sql
        assert f"validate constraint {constraint_name}" in sql
        constraint_offset = sql.index(f"add constraint {constraint_name}")
        assert action_fragment in sql[constraint_offset : constraint_offset + 300]

    assert "foreign key (message_id)" not in sql
    assert "foreign key (chatbot_id, company_id)" not in sql


def test_company_foreign_keys_are_deferred_under_option_c():
    migration = _read(MIGRATION_PATH).lower()
    rollback = _read(ROLLBACK_PATH).lower()
    verification = _read(VERIFICATION_PATH).lower()

    assert "references public.companies" not in migration
    for constraint_name in (
        "agent_actions_company_id_fkey",
        "crm_leads_company_id_fkey",
    ):
        assert constraint_name not in migration
        assert constraint_name not in rollback
        assert constraint_name not in verification

    assert "direct company_id foreign keys are intentionally deferred" in migration
    assert "left join public.companies" in migration
    assert "rows reference missing companies" in migration
    assert "disagree with chatbot company ownership" in migration


def test_preflight_inspects_company_deletion_semantics_and_function_grants():
    preflight = _read(PREFLIGHT_PATH).lower()

    for required_fragment in (
        "chatbots.company_id -> companies.id",
        "con.confdeltype",
        "con.confupdtype",
        "candidate_company_delete_functions",
        "pg_get_functiondef",
        "aclexplode",
        "privilege_type",
        "table_class.relname = 'companies'",
        "pg_get_triggerdef",
    ):
        assert required_fragment in preflight


def test_nullable_columns_and_company_not_null_gate_match_the_design():
    sql = " ".join(_read(MIGRATION_PATH).lower().split())

    assert "alter column company_id set not null" in sql
    assert "agent_actions_company_id_not_null_check" in sql
    assert "validate constraint agent_actions_company_id_not_null_check" in sql
    assert "alter column conversation_id set not null" not in sql
    assert "alter column message_id set not null" not in sql


def test_proposed_checks_cover_current_application_and_historical_values():
    # 027 owns the intent, action and priority CHECK constraints.  The status
    # constraint it created was later replaced by 047 when the lead pipeline
    # moved to new/contacted/qualified/won/lost, so status values are checked
    # against 047 and everything else against 027.  Reading both is what keeps
    # this guard honest: it asserts that some live migration covers every value
    # the application can produce, not that one particular file does.
    migration = _read(MIGRATION_PATH)
    status_migration = _read(STATUS_MIGRATION_PATH)
    decision_path = PROJECT_ROOT / "app" / "services" / "agent_decision_service.py"
    crm_repository_path = PROJECT_ROOT / "app" / "database" / "crm_lead_repository.py"

    application_intents = _literal_assignment(decision_path, "ALLOWED_INTENTS")
    application_actions = _literal_assignment(decision_path, "ALLOWED_ACTIONS")
    crm_statuses = _literal_assignment(crm_repository_path, "ALLOWED_CRM_LEAD_STATUSES")
    crm_priorities = _literal_assignment(
        crm_repository_path, "ALLOWED_CRM_LEAD_PRIORITIES"
    )

    for value in (
        *application_intents,
        *application_actions,
        *crm_priorities,
        "general_question",
        "escalate",
        "follow_up",
        "staff_attention",
        "negative_feedback",
    ):
        assert f"'{value}'" in migration

    for value in crm_statuses:
        assert f"'{value}'" in status_migration

    # The retired vocabulary stays in 047's allow-list for one release so an
    # older client cannot trip a constraint violation mid-deploy.
    for retired in ("in_progress", "closed"):
        assert f"'{retired}'" in status_migration

    assert "confidence >= 0 AND confidence <= 1" in migration


def test_indexes_match_pending_signal_and_open_lead_behavior():
    sql = " ".join(_read(MIGRATION_PATH).lower().split())

    assert (
        "create index agent_actions_chatbot_status_created_at_idx "
        "on public.agent_actions (chatbot_id, status, created_at desc)"
    ) in sql
    assert (
        "create unique index crm_leads_one_open_per_conversation_idx "
        "on public.crm_leads (chatbot_id, conversation_id)"
    ) in sql
    assert "conversation_id is not null" in sql
    assert "status in ('new', 'in_progress', 'contacted')" in sql
    status_sql = " ".join(_read(STATUS_MIGRATION_PATH).lower().split())
    assert "status in ('new', 'in_progress', 'contacted', 'qualified')" in status_sql
    assert "unique index" not in sql[sql.index("agent_actions_chatbot_status_created_at_idx") - 20 :
                                     sql.index("agent_actions_chatbot_status_created_at_idx")]


def test_rls_and_grants_enforce_service_role_only_without_force():
    sql = " ".join(_read(MIGRATION_PATH).lower().split())

    assert "alter table public.agent_actions enable row level security" in sql
    assert "alter table public.crm_leads enable row level security" in sql
    assert "force row level security" not in sql
    assert "create policy" not in sql
    assert "rolbypassrls or rolsuper" in sql
    assert (
        "revoke all privileges on table public.agent_actions "
        "from public, anon, authenticated"
    ) in sql
    assert (
        "revoke all privileges on table public.crm_leads "
        "from public, anon, authenticated"
    ) in sql
    assert (
        "grant select, insert, update on table public.agent_actions to service_role"
    ) in sql
    assert (
        "grant select, insert, update on table public.crm_leads to service_role"
    ) in sql


def test_service_role_table_grants_match_repository_operations():
    repository_paths = (
        PROJECT_ROOT / "app" / "database" / "agent_action_repository.py",
        PROJECT_ROOT / "app" / "database" / "crm_lead_repository.py",
    )
    operations = _direct_table_operations(repository_paths)
    migration = _read(MIGRATION_PATH)

    # Publishing tests use the existing UPDATE grant to compare-and-swap a run.
    # Escalation resolution still goes through the SECURITY INVOKER RPC in 058.
    direct_operations = {
        "agent_actions": {"select", "insert", "update"},
        "crm_leads": {"select", "insert", "update"},
    }

    for table_name in ("agent_actions", "crm_leads"):
        assert operations[table_name] == direct_operations[table_name]
        grant_match = re.search(
            rf"GRANT\s+([A-Z,\s]+)\s+ON TABLE public\.{table_name}\s+TO service_role",
            migration,
        )
        assert grant_match
        granted = {
            privilege.strip().lower()
            for privilege in grant_match.group(1).split(",")
        }
        assert operations[table_name] <= granted
        assert granted == {"select", "insert", "update"}


def test_rollback_never_changes_or_deletes_row_data():
    sql = _without_sql_comments(_read(ROLLBACK_PATH))
    assert not re.search(r"(?im)^\s*(delete|update|insert|truncate)\b", sql)
    assert "ALTER COLUMN company_id DROP NOT NULL" in sql
    assert "DISABLE ROW LEVEL SECURITY" in sql
    assert "authoritative company_id backfill is intentionally not reversed" in _read(
        ROLLBACK_PATH
    )


def test_rollback_and_verification_match_the_exact_added_schema_objects():
    migration = _read(MIGRATION_PATH)
    rollback = _read(ROLLBACK_PATH)
    verification = _read(VERIFICATION_PATH)

    added_constraints = set(re.findall(r"ADD CONSTRAINT\s+(\w+)", migration))
    rollback_constraints = set(
        re.findall(r"DROP CONSTRAINT IF EXISTS\s+(\w+)", rollback)
    )
    assert rollback_constraints == added_constraints

    added_indexes = set(
        re.findall(r"CREATE (?:UNIQUE )?INDEX\s+(\w+)", migration)
    )
    rollback_indexes = set(
        re.findall(r"DROP INDEX IF EXISTS public\.(\w+)", rollback)
    )
    assert rollback_indexes == added_indexes

    final_constraints = added_constraints - {"agent_actions_company_id_not_null_check"}
    verification_constraint_block = re.search(
        r"WITH expected_constraints\(table_name, constraint_name\) AS \("
        r"\s*VALUES(.*?)\)\s*SELECT",
        verification,
        flags=re.DOTALL,
    )
    assert verification_constraint_block
    verified_constraints = set(
        re.findall(
            r"\('(?:agent_actions|crm_leads)',\s*'([^']+)'\)",
            verification_constraint_block.group(1),
        )
    )
    assert verified_constraints == final_constraints


def test_permanent_delete_rpc_keeps_dependents_before_chatbot():
    rpc_sql = _read(PERMANENT_DELETE_RPC_PATH)
    normalized_rpc_sql = " ".join(rpc_sql.split())

    crm_delete = rpc_sql.index("DELETE FROM public.crm_leads")
    action_delete = rpc_sql.index("DELETE FROM public.agent_actions")
    chatbot_delete = rpc_sql.index("DELETE FROM public.chatbots")
    assert crm_delete < chatbot_delete
    assert action_delete < chatbot_delete
    assert (
        "GRANT EXECUTE ON FUNCTION public.permanently_delete_archived_chatbot"
        in normalized_rpc_sql
    )


def test_no_application_code_directly_deletes_target_table_rows():
    application_paths = tuple((PROJECT_ROOT / "app").rglob("*.py"))
    operations = _direct_table_operations(application_paths)

    assert "delete" not in operations.get("agent_actions", set())
    assert "delete" not in operations.get("crm_leads", set())

    rpc_sql = _read(PERMANENT_DELETE_RPC_PATH)
    assert rpc_sql.count("DELETE FROM public.agent_actions") == 1
    assert rpc_sql.count("DELETE FROM public.crm_leads") == 1

    bot_repository = _read(PROJECT_ROOT / "app" / "database" / "bot_repository.py")
    assert 'supabase.rpc(\n        "permanently_delete_archived_chatbot"' in bot_repository


def test_runbook_records_staging_verification_and_production_hold():
    runbook = _read(RUNBOOK_PATH).lower()

    assert "applied and verified successfully in staging" in runbook
    assert "production has not been updated" in runbook
    assert "staging verification result" in runbook
    assert "backup" in runbook
    assert "orphan disposition" in runbook
    assert "service-role-only" in runbook
    assert "remain deferred" in runbook
    assert "adopts **option c**" in runbook
    assert "zero orphan failures" in runbook


def test_migration_has_both_corrected_plpgsql_block_terminators():
    migration = _read(MIGRATION_PATH)

    assert "END;\n$preconditions$;" in migration
    assert "END;\n$sequence_grants$;" in migration
