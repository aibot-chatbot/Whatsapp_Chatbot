import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GeoFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "frontend" / "geo-analysis.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "frontend" / "assets" / "js" / "geo-analysis.js").read_text(encoding="utf-8")
        cls.sidebar = (ROOT / "frontend" / "sidebar-component.js").read_text(encoding="utf-8")
        cls.bots = (ROOT / "frontend" / "bots.html").read_text(encoding="utf-8")

    def test_geo_navigation_is_after_my_bots_and_before_team(self):
        self.assertLess(self.sidebar.index("My bots"), self.sidebar.index("GEO Analysis"))
        self.assertLess(self.sidebar.index("GEO Analysis"), self.sidebar.index("Team"))

    def test_workspace_and_bot_context_use_the_right_my_bots_icon(self):
        self.assertIn("${botId ? 'arrow-left' : 'bot'}", self.sidebar)
        self.assertIn("${!botId ? `<a href=\"geo-analysis.html\"", self.sidebar)
        self.assertIn("${botId ? `\n                <a href=\"geo-analysis.html\" class=\"profile-link\"", self.sidebar)

    def test_page_requires_login_and_uses_company_scoped_api(self):
        self.assertIn("requireLogin();", self.page)
        self.assertIn('json("/api/geo/capabilities")', self.script)
        self.assertIn('json(`/api/geo/analyses?limit=${limit}`)', self.script)
        self.assertNotIn("company_id", self.script)
        self.assertIn('integrity="sha384-', self.page)
        self.assertIn("script.integrity = 'sha384-", self.sidebar)

    def test_page_exposes_evidence_and_transparent_metrics(self):
        for label in ("Mention rate", "Citation rate", "Owned source rate", "Recommendation", "Share of voice", "Prompt coverage"):
            self.assertIn(label, self.script)
        self.assertIn("mention_rate_confidence_interval", self.script)
        self.assertIn("Prompt × platform evidence matrix", self.page)
        self.assertIn("Evidence-backed improvement plan", self.page)
        self.assertIn("Monthly scan budget", self.page)
        self.assertIn("platform_summary", self.script)
        self.assertIn("finding.actions", self.script)
        self.assertIn("score_breakdown", self.script)

    def test_scan_builder_is_guided_and_models_have_local_vector_marks(self):
        for step in ("Set your target", "Choose AI search models", "Add customer questions"):
            self.assertIn(step, self.page)
        for provider in ("geo-model-openai", "geo-model-gemini", "geo-model-perplexity"):
            self.assertIn(provider, self.page)
        self.assertGreaterEqual(self.page.count('<svg viewBox="0 0 32 32"'), 3)
        self.assertIn("Improve brand matching", self.page)
        self.assertIn("data-prompt-example", self.page)
        self.assertIn("geo-run-equation", self.script)

    def test_workspace_pages_share_the_same_sidebar_component(self):
        for name in ("bots.html", "geo-analysis.html", "team.html", "billing.html", "pricing.html"):
            page = (ROOT / "frontend" / name).read_text(encoding="utf-8")
            self.assertIn("<chatbot-sidebar></chatbot-sidebar>", page, name)
            self.assertIn('src="sidebar-component.js"', page, name)
        self.assertNotIn('id="bots-side-rail"', self.bots)
        for name in ("bots.html", "geo-analysis.html", "team.html", "billing.html", "pricing.html"):
            self.assertIn(f'"{name}"', self.sidebar)
        self.assertIn("const botId = isWorkspacePage ? null : selectedBotId", self.sidebar)


if __name__ == "__main__":
    unittest.main()
