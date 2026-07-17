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


if __name__ == "__main__":
    unittest.main()
