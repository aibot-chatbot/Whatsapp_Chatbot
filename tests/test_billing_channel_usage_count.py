"""Billing channel usage regressions for orphaned and archived bot channels."""

import unittest
from unittest.mock import patch


class _Response:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)
        self.count_requested = False

    def select(self, *args, **kwargs):
        self.count_requested = kwargs.get("count") == "exact"
        return self

    def eq(self, field, value):
        self.rows = [row for row in self.rows if row.get(field) == value]
        return self

    def neq(self, field, value):
        self.rows = [row for row in self.rows if row.get(field) != value]
        return self

    def is_(self, field, value):
        if value == "null":
            self.rows = [row for row in self.rows if row.get(field) is None]
        return self

    def in_(self, field, values):
        allowed = set(values or [])
        self.rows = [row for row in self.rows if row.get(field) in allowed]
        return self

    def execute(self):
        count = len(self.rows) if self.count_requested else None
        return _Response(data=self.rows, count=count)


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, table_name):
        return _Query(self.tables.get(table_name, []))


class TestBillingChannelUsageCount(unittest.TestCase):
    def _count_channels(self, tables):
        from app.database import billing_usage_repository

        with patch.object(billing_usage_repository, "supabase", _FakeSupabase(tables)):
            return billing_usage_repository.count_company_channels(1)

    def test_connected_channel_linked_to_active_bot_counts(self):
        count = self._count_channels({
            "chatbots": [
                {"id": 10, "company_id": 1, "status": "active", "deleted_at": None},
            ],
            "wasender_channels": [
                {
                    "id": 1,
                    "company_id": 1,
                    "chatbot_id": 10,
                    "is_active": True,
                    "connection_status": "connected",
                },
            ],
        })

        self.assertEqual(count, 1)

    def test_connected_channel_linked_to_archived_bot_does_not_count(self):
        count = self._count_channels({
            "chatbots": [
                {"id": 10, "company_id": 1, "status": "archived", "deleted_at": None},
            ],
            "telegram_channels": [
                {
                    "id": 1,
                    "company_id": 1,
                    "chatbot_id": 10,
                    "is_active": True,
                    "connection_status": "connected",
                },
            ],
        })

        self.assertEqual(count, 0)

    def test_connected_channel_linked_to_deleted_missing_bot_does_not_count(self):
        count = self._count_channels({
            "chatbots": [
                {"id": 10, "company_id": 1, "status": "active", "deleted_at": None},
            ],
            "whatsapp_channels": [
                {
                    "id": 1,
                    "company_id": 1,
                    "chatbot_id": 999,
                    "is_active": True,
                    "connection_status": "connected",
                },
            ],
        })

        self.assertEqual(count, 0)

    def test_disconnected_or_inactive_channels_do_not_count(self):
        count = self._count_channels({
            "chatbots": [
                {"id": 10, "company_id": 1, "status": "active", "deleted_at": None},
                {"id": 11, "company_id": 1, "status": "active", "deleted_at": None},
            ],
            "telegram_channels": [
                {
                    "id": 1,
                    "company_id": 1,
                    "chatbot_id": 10,
                    "is_active": False,
                    "connection_status": "connected",
                },
            ],
            "wasender_channels": [
                {
                    "id": 2,
                    "company_id": 1,
                    "chatbot_id": 11,
                    "is_active": True,
                    "connection_status": "disconnected",
                },
            ],
        })

        self.assertEqual(count, 0)


class TestCompanyChannelSlots(unittest.TestCase):
    """Slots are a company-wide pool shown on a per-bot page, so the usage
    must say which bot holds each one. Without it a bot with one channel
    reads as "Plan full" with no visible reason."""

    TABLES = {
        "chatbots": [
            {"id": 53, "company_id": 1, "status": "active", "deleted_at": None,
             "bot_name": "OlympicEdu Assistant"},
            {"id": 60, "company_id": 1, "status": "active", "deleted_at": None,
             "bot_name": "Travel Assistant"},
        ],
        "telegram_channels": [
            {"id": 8, "company_id": 1, "chatbot_id": 53, "is_active": True,
             "connection_status": "connected"},
            {"id": 9, "company_id": 1, "chatbot_id": 53, "is_active": False,
             "connection_status": "disconnected"},
            {"id": 12, "company_id": 1, "chatbot_id": 60, "is_active": True,
             "connection_status": "connected"},
        ],
        "wasender_channels": [
            # Orphan of a deleted bot: holds no slot.
            {"id": 1, "company_id": 1, "chatbot_id": 1, "is_active": True,
             "connection_status": "connected"},
        ],
    }

    def test_each_slot_names_the_bot_holding_it(self):
        from app.database import billing_usage_repository

        with patch.object(billing_usage_repository, "supabase", _FakeSupabase(self.TABLES)):
            slots = billing_usage_repository.list_company_channel_slots(1)
            count = billing_usage_repository.count_company_channels(1)

        self.assertEqual(slots, [
            {"provider": "telegram", "chatbot_id": 53, "bot_name": "OlympicEdu Assistant"},
            {"provider": "telegram", "chatbot_id": 60, "bot_name": "Travel Assistant"},
        ])
        # The count and the explanation can never disagree.
        self.assertEqual(count, len(slots))

    def test_usage_reports_the_slot_holders_with_the_count(self):
        from app.services import billing_service

        slots = [{"provider": "telegram", "chatbot_id": 53, "bot_name": "OlympicEdu Assistant"}]
        with patch.multiple(
            billing_service,
            _get_company_subscription=lambda _id: {"plan_id": 2,
                                                   "current_period_start": "2026-10-01T00:00:00+00:00",
                                                   "current_period_end": "2026-11-01T00:00:00+00:00"},
            get_plan_by_id=lambda _id: {"id": 2, "code": "pro", "channel_limit": 2},
            log_current_period_anomaly=lambda *a, **k: None,
            count_company_chatbots=lambda _id: 2,
            count_active_company_members=lambda _id: 1,
            count_pending_company_invitations=lambda _id: 0,
            list_company_channel_slots=lambda _id: slots,
            count_company_knowledge_files=lambda _id: 0,
            sum_company_knowledge_storage=lambda _id: 0,
            sum_company_ai_usage_tokens=lambda *a: {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        ):
            usage = billing_service.get_company_usage(1)

        self.assertEqual(usage["usage"]["channels"], {"used": 1, "limit": 2, "slots": slots})


if __name__ == "__main__":
    unittest.main()
