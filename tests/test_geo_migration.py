import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GeoMigrationTests(unittest.TestCase):
    def test_schema_is_company_scoped_and_paid_plan_gated(self):
        sql = (ROOT / "data" / "075_geo_analysis.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create table public.geo_analyses", sql)
        self.assertIn("create table public.geo_prompt_executions", sql)
        self.assertIn("create table public.geo_execution_citations", sql)
        self.assertIn("foreign key (analysis_id, company_id)", sql)
        self.assertIn("foreign key (execution_id, company_id)", sql)
        self.assertIn("where lower(code) = 'free'", sql)
        self.assertIn("where lower(code) in ('essential','advanced','pro')", sql)
        self.assertIn("'{\"geo_analysis\": false}'", sql)
        self.assertIn("'{\"geo_analysis\": true}'", sql)
        self.assertIn("create or replace function public.reserve_geo_analysis", sql)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn("execution_count smallint", sql)
        self.assertIn("grant execute on function public.reserve_geo_analysis", sql)

    def test_expansion_migration_allows_seven_catalogued_surfaces_and_twenty_checks(self):
        sql = (ROOT / "data" / "078_geo_platform_expansion.sql").read_text(encoding="utf-8").lower()
        for platform in ("chatgpt", "gemini", "claude", "deepseek", "perplexity",
                         "google_ai_mode", "microsoft_copilot"):
            self.assertIn(f"'{platform}'", sql)
        self.assertIn("execution_count between 1 and 20", sql)
        self.assertIn("p_execution_count > 20", sql)


if __name__ == "__main__":
    unittest.main()
