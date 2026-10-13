import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ProChannelLimitTests(unittest.TestCase):
    def test_migration_promotes_only_pro_to_four_channels(self):
        sql = (ROOT / "data" / "076_pro_four_channels.sql").read_text(encoding="utf-8").lower()
        self.assertIn("set channel_limit = 4", sql)
        self.assertIn("where lower(code) = 'pro'", sql)
        self.assertNotIn("where lower(code) = 'advanced'", sql)

    def test_authenticated_plan_catalog_exposes_four_pro_channels(self):
        source = (ROOT / "frontend" / "assets" / "js" / "plan-catalog.js").read_text(encoding="utf-8")
        pro = source.split('code: "pro"', 1)[1]
        self.assertIn("channel_limit: 4", pro)

    def test_base_plan_seed_no_longer_restores_pro_to_two_channels(self):
        sql = (ROOT / "data" / "003_upsert_subscription_plans.sql").read_text(encoding="utf-8").lower()
        advanced = sql.split("-- advanced", 1)[1].split("-- pro", 1)[0]
        pro = sql.split("-- pro", 1)[1]
        statements = sql.split(";")
        advanced_update = next(item for item in statements
                               if "update subscription_plans" in item and "where lower(code) = 'advanced'" in item)
        pro_update = next(item for item in statements
                          if "update subscription_plans" in item and "where lower(code) = 'pro'" in item)
        self.assertIn("2 channels", advanced)
        self.assertIn("4 channels", pro)
        self.assertIn("channel_limit = 2", advanced_update)
        self.assertIn("channel_limit = 4", pro_update)

    def test_runtime_plan_reader_upgrades_a_stale_pro_row(self):
        from app.database import subscription_plan_repository as repository

        query = SimpleNamespace(
            select=lambda *_: query,
            eq=lambda *_: query,
            limit=lambda *_: query,
            execute=lambda: SimpleNamespace(data=[{
                "id": 3, "code": "pro", "channel_limit": 2,
                "description": "Pro plan - 3 chatbots, 2 channels",
            }]),
        )
        with patch.object(repository, "supabase", SimpleNamespace(table=lambda *_: query)):
            plan = repository._select_plan(3)

        self.assertEqual(plan["channel_limit"], 4)
        self.assertIn("4 channels", plan["description"])


if __name__ == "__main__":
    unittest.main()
