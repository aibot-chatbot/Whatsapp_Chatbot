import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = PROJECT_ROOT / "scripts" / "crm_agent_actions_orphan_review.sql"
RUNBOOK_PATH = PROJECT_ROOT / "docs" / "CRM_AGENT_ACTIONS_ORPHAN_DISPOSITION.md"


def _read(path):
    return path.read_text(encoding="utf-8")


def _without_sql_comments(sql):
    without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", without_blocks)


def _without_sql_strings(sql):
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


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


def test_orphan_review_sql_is_strictly_read_only():
    sql = _read(SQL_PATH)
    keywords = _top_level_statement_keywords(sql)

    assert keywords
    assert set(keywords) <= {"select", "with"}

    executable = _without_sql_strings(_without_sql_comments(sql))
    assert not re.search(
        r"(?im)(?:^|;)\s*"
        r"(delete|update|insert|truncate|alter|drop|create|grant|revoke|do|call)\b",
        executable,
    )


def test_every_required_classification_and_zero_count_dimension_is_present():
    sql = _read(SQL_PATH)
    required = {
        "AA-A": "chatbot_exists_and_conversation_exists",
        "AA-B": "chatbot_exists_but_conversation_missing",
        "AA-C": "chatbot_missing_but_conversation_exists",
        "AA-D": "chatbot_and_conversation_both_missing",
        "AA-E": "conversation_belongs_to_different_chatbot",
        "AA-F": "company_id_can_be_safely_backfilled_from_chatbot",
        "AA-G": "company_id_cannot_be_safely_inferred",
        "CRM-A": "chatbot_exists_and_conversation_exists",
        "CRM-B": "chatbot_exists_but_conversation_missing",
        "CRM-C": "chatbot_missing_but_conversation_exists",
        "CRM-D": "chatbot_and_conversation_both_missing",
        "CRM-E": "conversation_belongs_to_different_chatbot",
        "CRM-F": "company_ownership_mismatch",
    }

    for code, description in required.items():
        assert f"'{code}'" in sql
        assert f"'{description}'" in sql

    assert sql.count("required_classifications") >= 4
    assert sql.count("count(classified.id) AS row_count") == 2


def test_identifier_outputs_exclude_sensitive_row_columns():
    sql = _without_sql_strings(_without_sql_comments(_read(SQL_PATH))).lower()

    forbidden_column_tokens = {
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
    }
    for token in forbidden_column_tokens:
        assert not re.search(rf"\b{re.escape(token)}\b", sql)

    for permitted in (
        "row_id",
        "company_id",
        "chatbot_id",
        "conversation_id",
        "status",
        "intent",
        "lead_type",
        "created_at",
        "classification",
        "recommended_disposition_category",
    ):
        assert permitted in sql


def test_dependency_sections_use_catalogs_and_identifier_only_links():
    sql = _read(SQL_PATH).lower()

    for required_fragment in (
        "from pg_constraint",
        "from information_schema.columns",
        "from pg_views",
        "from pg_matviews",
        "from pg_proc",
        "from pg_trigger",
        "linked_crm_lead_ids",
        "linked_agent_action_ids",
        "does not claim a foreign key",
    ):
        assert required_fragment in sql

    assert "pg_get_functiondef(function_row.oid) as function_definition" in " ".join(
        sql.split()
    )
    assert "function_definition," not in sql


def test_runbook_records_unapproved_non_destructive_dispositions():
    runbook = " ".join(_read(RUNBOOK_PATH).lower().split())

    for required_fragment in (
        "review-only, non-destructive",
        "approved deletion of the exact 38-record manifest",
        "retain unchanged",
        "retain after ownership backfill",
        "retain after clearing optional conversation reference",
        "export and archive outside active tables",
        "export and delete",
        "restorable pre-cleanup backup",
        "separate cleanup migration",
        "not approved",
        "production is unchanged",
    ):
        assert required_fragment in runbook

    assert "| business owner | technical approver | data-retention approver |" in runbook
    assert "| approval status | evidence location | cleanup batch identifier |" in runbook


def test_runbook_has_all_migration_027_readiness_gates():
    runbook = " ".join(_read(RUNBOOK_PATH).lower().split())

    for required_fragment in (
        "missing chatbot references equal zero",
        "missing non-null conversation references equal zero",
        "ownership mismatches equal zero",
        "restorable backup and recorded approvals",
        "cleanup verification and evidence have been preserved",
        "migration preflight passes in staging",
    ):
        assert required_fragment in runbook
