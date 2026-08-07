import unittest
from pathlib import Path


DOC = Path(__file__).resolve().parents[1] / "docs" / "PLATFORM_ADMIN_SUPPORT_WORKFLOW_CONTRACT.md"


class PlatformAdminSupportWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text(encoding="utf-8")
        cls.normalized = cls.text.lower()

    def test_phase_two_scope_and_lifecycle_are_recorded(self):
        for phrase in [
            "Support Case Operations Phase 2",
            "implemented and verified only in the main shared-testing Supabase",
            "Migration 032 executed successfully",
            "Migration 032",
            "`waiting_for_tenant`",
            "`closed` to `in_progress`",
            "No-op transitions are rejected",
            "normal` remains the safe default",
            "no SLA",
            "Tenant Communication Phase 3",
            "Migration 033 are applied and",
            "verified only in the main shared-testing Supabase with fake/team data",
            "No staging or production readiness is claimed",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.normalized)

    def test_assignment_notes_and_timeline_boundaries_are_present(self):
        for phrase in [
            "assigned_platform_admin_user_id",
            "`platform_admin_users.id`",
            "not a tenant `users.role`",
            "inactive platform-admin mappings",
            "Internal notes are stored as append-only",
            "`event_type = 'note_added'`",
            "must never be serialized through tenant support",
            "created_at ASC, id ASC",
            "server facts only",
            "original tenant request linkage",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.normalized)

    def test_http_rpc_and_manual_verification_contract_are_present(self):
        for phrase in [
            "GET /api/platform-admin/support-case-assignees",
            "GET /api/platform-admin/support-cases/<case_id>/replies",
            "POST /api/platform-admin/support-cases/<case_id>/replies",
            "PATCH /api/platform-admin/support-cases/<case_id>/assignment",
            "PATCH /api/platform-admin/support-cases/<case_id>/status",
            "PATCH /api/platform-admin/support-cases/<case_id>/priority",
            "POST /api/platform-admin/support-cases/<case_id>/notes",
            "assign_platform_support_case",
            "set_platform_support_case_status",
            "set_platform_support_case_priority",
            "add_platform_support_case_note",
            "locks the case row",
            "anon` and `authenticated`",
            "Manual Schema Inspection SQL",
            "Manual Verification SQL",
            "Expected results",
            "create_platform_support_case_reply",
            "tenant_support_replies",
            "tenant_support_reply_notifications",
            "platform_support_case_events(tenant_support_reply_id, case_id)",
            "tenant_support_replies(id, platform_support_case_id)",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.normalized)

    def test_existing_boundaries_remain_present(self):
        for phrase in [
            "Support Cases Phase 1",
            "fake/team data",
            "Main Shared-testing Verification",
            "Migration 033 was applied successfully only in the main shared-testing Supabase",
            "reply `UPDATE`",
            "notification ownership-field update",
            "platform_admin.support_case.reply.create",
            "safe linkage and delivery metadata",
            "Duplicate assignment was rejected with no event or audit row",
            "Seven matching Phase 2 mutation audit events exist",
            "Internal note content was not duplicated into audit metadata",
            "impersonation",
            "billing actions",
            "exports",
            "SLA timers",
            "escalation automation",
            "platform_support_cases",
            "platform_support_case_events",
            "production remains blocked",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.normalized)


if __name__ == "__main__":
    unittest.main()
