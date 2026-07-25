import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = (
    PROJECT_ROOT / "scripts" / "crm_agent_actions_orphan_cleanup_candidates.sql"
)
RUNBOOK_PATH = (
    PROJECT_ROOT / "docs" / "CRM_AGENT_ACTIONS_ORPHAN_CLEANUP_APPROVAL.md"
)
MIGRATION_PATH = PROJECT_ROOT / "data" / "027_harden_crm_agent_actions.sql"


def _read(path):
    return path.read_text(encoding="utf-8")


def _without_comments(sql):
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", sql)


def _without_strings(sql):
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


def _statement_keywords(sql):
    cleaned = _without_comments(sql)
    return [
        match.group(1).lower()
        for match in re.finditer(
            r"(?:^|;)\s*([a-z_]+)",
            cleaned,
            flags=re.IGNORECASE,
        )
    ]


def test_candidate_sql_is_strictly_read_only():
    sql = _read(SQL_PATH)
    keywords = _statement_keywords(sql)

    assert keywords
    assert set(keywords) <= {"select", "with"}

    executable = _without_strings(_without_comments(sql))
    assert not re.search(
        r"(?im)(?:^|;)\s*"
        r"(delete|update|insert|truncate|alter|drop|create|grant|revoke|do|call)\b",
        executable,
    )


def test_all_three_relationship_derived_batch_definitions_are_present():
    sql = _read(SQL_PATH)

    for batch_id in (
        "CRM-ORPHAN-BATCH-001",
        "CRM-ORPHAN-BATCH-002",
        "CRM-ORPHAN-BATCH-003",
    ):
        assert batch_id in sql

    assert "lead.id = 1" in sql
    assert "lead.id = 2" in sql
    assert "action.chatbot_id = lead.chatbot_id" in sql
    assert "action.conversation_id = lead.conversation_id" in sql
    assert "WHERE NOT EXISTS" in sql


def test_expected_counts_exclusivity_and_completeness_gates_are_present():
    sql = _read(SQL_PATH)

    for expected_fragment in (
        "('CRM-ORPHAN-BATCH-001', 1::bigint, 29::bigint)",
        "('CRM-ORPHAN-BATCH-002', 1::bigint, 3::bigint)",
        "('CRM-ORPHAN-BATCH-003', 0::bigint, 4::bigint)",
        "is_expected_count",
        "overlapping_record_count",
        "all_proposed_rows_remain_double_orphans",
        "omitted_orphan_crm_lead_count",
        "omitted_orphan_agent_action_count",
        "matches_confirmed_ownership_counts",
    ):
        assert expected_fragment in sql


def test_candidate_projections_exclude_sensitive_columns():
    executable = _without_strings(_without_comments(_read(SQL_PATH))).lower()

    for forbidden in (
        "payload",
        "message_content",
        "message_text",
        "notes",
        "reason",
        "phone",
        "customer_name",
        "username",
        "email",
        "channel_id",
        "source_channel",
    ):
        assert not re.search(rf"\b{re.escape(forbidden)}\b", executable)

    for permitted in (
        "row_id",
        "company_id",
        "chatbot_id",
        "conversation_id",
        "status",
        "intent_or_lead_type",
        "created_at",
        "proposed_batch_identifier",
    ):
        assert permitted in executable


def test_approval_record_records_staging_completion_and_production_hold():
    runbook = " ".join(_read(RUNBOOK_PATH).split())

    assert runbook.count("Staging deletion complete; production not approved") == 3
    assert "Staging-first migration `028` was applied successfully in staging" in runbook
    for required_field in (
        "Business owner",
        "Technical approver",
        "Data-retention approver",
        "Backup identifier",
        "Export manifest identifier",
        "SHA-256 checksum",
        "Authorized archive location",
        "Retention period",
        "Restoration owner",
        "Staging rehearsal status",
        "Business approval timestamp",
        "Technical approval timestamp",
        "Data-retention approval timestamp",
    ):
        assert required_field in runbook


def test_future_cleanup_safety_and_separation_are_documented():
    runbook = _read(RUNBOOK_PATH)

    for required_fragment in (
        "Use the exact approved CRM lead and Agent Action identifiers.",
        "Fail closed if any expected batch count differs.",
        "regained a valid chatbot or conversation",
        "linked relationship differs from the approved evidence",
        "Use one transaction.",
        "Delete no unrelated row.",
        "Never use broad predicates",
        "Never infer eligibility from aggregate row counts alone.",
        "separate SQL migrations",
        "separate production deployment steps",
        "one atomic Git commit",
    ):
        assert required_fragment in runbook


def test_migration_027_remains_separate_and_contains_no_orphan_cleanup():
    migration = _read(MIGRATION_PATH)
    executable = _without_strings(_without_comments(migration))

    assert "STAGING-VERIFIED MIGRATION - PRODUCTION NOT APPLIED" in migration
    assert not re.search(r"(?im)(?:^|;)\s*DELETE\b", executable)
    assert "CRM-ORPHAN-BATCH-001" not in migration
    assert "CRM-ORPHAN-BATCH-002" not in migration
    assert "CRM-ORPHAN-BATCH-003" not in migration
