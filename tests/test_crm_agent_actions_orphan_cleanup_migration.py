import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    PROJECT_ROOT / "data" / "028_cleanup_orphan_crm_agent_actions.sql"
)
VERIFICATION_PATH = (
    PROJECT_ROOT / "scripts" / "crm_agent_actions_orphan_cleanup_verification.sql"
)
MIGRATION_027_PATH = PROJECT_ROOT / "data" / "027_harden_crm_agent_actions.sql"
APPROVAL_PATH = (
    PROJECT_ROOT / "docs" / "CRM_AGENT_ACTIONS_ORPHAN_CLEANUP_APPROVAL.md"
)
DISPOSITION_PATH = (
    PROJECT_ROOT / "docs" / "CRM_AGENT_ACTIONS_ORPHAN_DISPOSITION.md"
)

EXPECTED_BATCH_001_ACTIONS = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
    71, 72, 73, 74, 102, 103,
}
EXPECTED_BATCH_002_ACTIONS = {11, 12, 21}
EXPECTED_BATCH_003_ACTIONS = {13, 35, 36, 75}


def _read(path):
    return path.read_text(encoding="utf-8")


def _without_comments(sql):
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", sql)


def _without_strings(sql):
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


def _array_values(sql, variable_name):
    match = re.search(
        rf"{variable_name}\s+bigint\[\]\s*:=\s*ARRAY\[(.*?)\]::bigint\[\]",
        sql,
        flags=re.DOTALL,
    )
    assert match, f"Missing array declaration for {variable_name}"
    return [int(value) for value in re.findall(r"\d+", match.group(1))]


def _top_level_keywords(sql):
    clean = _without_comments(sql)
    return [
        match.group(1).lower()
        for match in re.finditer(
            r"(?:^|;)\s*([a-z_]+)",
            clean,
            flags=re.IGNORECASE,
        )
    ]


def test_028_is_the_next_selected_migration_number():
    numbered = []
    for path in (PROJECT_ROOT / "data").glob("*.sql"):
        match = re.match(r"^(\d+)_", path.name)
        if match:
            numbered.append((int(match.group(1)), path.name))

    assert max(number for number, _ in numbered) == 28
    assert [
        name for number, name in numbered if number == 28
    ] == ["028_cleanup_orphan_crm_agent_actions.sql"]


def test_exact_approved_identifier_arrays_have_no_duplicates():
    migration = _read(MIGRATION_PATH)

    assert _array_values(migration, "batch_001_crm_lead_ids") == [1]
    assert set(_array_values(
        migration, "batch_001_agent_action_ids"
    )) == EXPECTED_BATCH_001_ACTIONS
    assert _array_values(migration, "batch_002_crm_lead_ids") == [2]
    assert set(_array_values(
        migration, "batch_002_agent_action_ids"
    )) == EXPECTED_BATCH_002_ACTIONS
    assert _array_values(migration, "batch_003_crm_lead_ids") == []
    assert set(_array_values(
        migration, "batch_003_agent_action_ids"
    )) == EXPECTED_BATCH_003_ACTIONS

    all_actions = (
        list(EXPECTED_BATCH_001_ACTIONS)
        + list(EXPECTED_BATCH_002_ACTIONS)
        + list(EXPECTED_BATCH_003_ACTIONS)
    )
    assert len(EXPECTED_BATCH_001_ACTIONS) == 29
    assert len(EXPECTED_BATCH_002_ACTIONS) == 3
    assert len(EXPECTED_BATCH_003_ACTIONS) == 4
    assert len(all_actions) == 36
    assert len(set(all_actions)) == 36


def test_migration_has_one_transaction_and_manual_backup_gate():
    migration = _read(MIGRATION_PATH)
    executable = _without_comments(migration)

    assert len(re.findall(r"(?im)^\s*BEGIN\s*;", executable)) == 1
    assert len(re.findall(r"(?im)^\s*COMMIT\s*;", executable)) == 1
    assert "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;" in migration
    assert "STAGING-FIRST" in migration
    for prerequisite in (
        "restorable staging database backup",
        "Export the exact 38 approved records",
        "export manifest identifier",
        "SHA-256 checksum",
        "authorized archive location and restoration owner",
        "does not claim those prerequisites have been completed",
    ):
        assert prerequisite in migration


def test_pre_delete_assertions_are_fail_closed_and_relationship_aware():
    migration = _read(MIGRATION_PATH)

    for required_fragment in (
        "cardinality(batch_001_agent_action_ids) <> 29",
        "cardinality(batch_002_agent_action_ids) <> 3",
        "cardinality(batch_003_agent_action_ids) <> 4",
        "count(DISTINCT manifest.id)",
        "FOR UPDATE",
        "all 36 approved Agent Actions must remain double orphans",
        "all 2 approved CRM leads must remain double orphans",
        "action.chatbot_id = lead.chatbot_id",
        "action.conversation_id = lead.conversation_id",
        "batch 003 expected 4 standalone Agent Actions",
        "orphan Agent Actions are omitted from the approved manifest",
        "orphan CRM leads are omitted from the approved manifest",
        "RAISE EXCEPTION",
    ):
        assert required_fragment in migration


def test_exact_id_deletes_are_child_first_and_have_no_broad_predicate():
    migration = _without_comments(_read(MIGRATION_PATH))
    delete_statements = re.findall(
        r"DELETE\s+FROM\s+public\.(agent_actions|crm_leads).*?;",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert delete_statements == ["agent_actions", "crm_leads"]

    action_delete = re.search(
        r"DELETE FROM public\.agent_actions AS action\s+"
        r"WHERE action\.id = ANY\(approved_agent_action_ids\);",
        migration,
    )
    lead_delete = re.search(
        r"DELETE FROM public\.crm_leads AS lead\s+"
        r"WHERE lead\.id = ANY\(approved_crm_lead_ids\);",
        migration,
    )
    assert action_delete
    assert lead_delete
    assert action_delete.start() < lead_delete.start()

    for statement in re.findall(
        r"DELETE\s+FROM\s+public\..*?;",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        assert ".id = ANY(approved_" in statement
        assert "chatbot_id IS NULL" not in statement
        assert "conversation.id IS NULL" not in statement


def test_exact_delete_counts_and_post_delete_assertions_are_present():
    migration = _read(MIGRATION_PATH)

    for required_fragment in (
        "deleted_agent_action_count <> 36",
        "deleted_crm_lead_count <> 2",
        "approved Agent Action identifiers remain",
        "approved CRM lead identifiers remain",
        "Agent Actions still reference missing chatbots",
        "Agent Actions still reference missing conversations",
        "CRM leads still reference missing chatbots",
        "CRM leads still reference missing conversations",
        "valid Agent Action count changed",
        "valid CRM lead count changed",
    ):
        assert required_fragment in migration

    assert "valid_agent_action_count_before = 0" not in migration
    assert "valid_crm_lead_count_before = 0" not in migration
    assert "no valid Agent Actions remain before cleanup" not in migration
    assert "no valid CRM lead remains before cleanup" not in migration
    assert (
        "valid_agent_action_count_after <> valid_agent_action_count_before"
        in migration
    )
    assert "valid_crm_lead_count_after <> valid_crm_lead_count_before" in migration


def test_verification_is_read_only_and_covers_required_outcomes():
    verification = _read(VERIFICATION_PATH)
    keywords = _top_level_keywords(verification)
    assert keywords
    assert set(keywords) <= {"select", "with"}

    executable = _without_strings(_without_comments(verification))
    assert not re.search(
        r"(?im)(?:^|;)\s*"
        r"(delete|update|insert|truncate|alter|drop|create|grant|revoke|do|call)\b",
        executable,
    )

    for required_fragment in (
        "remaining_approved_agent_action_count",
        "remaining_approved_crm_lead_count",
        "agent_actions_missing_chatbot",
        "agent_actions_missing_non_null_conversation",
        "crm_leads_missing_chatbot",
        "crm_leads_missing_non_null_conversation",
        "valid_agent_actions_remain",
        "valid_crm_lead_remains",
        "agent_actions_company_vs_chatbot",
        "agent_actions_conversation_vs_chatbot",
        "crm_leads_company_vs_chatbot",
        "crm_leads_conversation_vs_chatbot",
        "migration_027_orphan_gates_ready",
    ):
        assert required_fragment in verification


def test_verification_contains_the_same_exact_identifier_manifest():
    verification = _read(VERIFICATION_PATH)
    action_block = re.search(
        r"WITH approved_agent_action_ids\(id\) AS \(\s*VALUES(.*?)\)\s*SELECT",
        verification,
        flags=re.DOTALL,
    )
    lead_block = re.search(
        r"WITH approved_crm_lead_ids\(id\) AS \(\s*VALUES(.*?)\)\s*SELECT",
        verification,
        flags=re.DOTALL,
    )
    assert action_block
    assert lead_block

    action_ids = {
        int(value)
        for value in re.findall(r"\((\d+)(?:::\w+)?\)", action_block.group(1))
    }
    lead_ids = {
        int(value)
        for value in re.findall(r"\((\d+)(?:::\w+)?\)", lead_block.group(1))
    }
    assert action_ids == (
        EXPECTED_BATCH_001_ACTIONS
        | EXPECTED_BATCH_002_ACTIONS
        | EXPECTED_BATCH_003_ACTIONS
    )
    assert lead_ids == {1, 2}


def test_migration_027_remains_separate_and_production_unapplied():
    migration_027 = _read(MIGRATION_027_PATH)
    executable = _without_strings(_without_comments(migration_027))

    assert "STAGING-VERIFIED MIGRATION - PRODUCTION NOT APPLIED" in migration_027
    assert not re.search(r"(?im)(?:^|;)\s*DELETE\b", executable)
    assert "CRM-ORPHAN-BATCH-001" not in migration_027
    assert "028_cleanup_orphan_crm_agent_actions" not in migration_027


def test_documents_record_staging_application_but_no_production_application():
    approval = _read(APPROVAL_PATH)
    disposition = _read(DISPOSITION_PATH)
    combined = approval + "\n" + disposition

    for required_fragment in (
        "approved by the user on 2026-07-25",
        "migration `028` was applied successfully in staging",
        "Production has not",
        "restorable backup",
        "Export manifest identifier",
        "SHA-256 checksum",
        "CRM lead: `1`",
        "CRM lead: `2`",
        "Agent Actions: `13, 35, 36, 75`",
    ):
        assert required_fragment in combined
