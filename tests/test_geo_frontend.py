import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GeoFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "frontend" / "geo-analysis.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "frontend" / "assets" / "js" / "geo-analysis.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "frontend" / "assets" / "css" / "geo-analysis.css").read_text(encoding="utf-8")
        cls.comparison_page = (ROOT / "frontend" / "geo-provider-comparison.html").read_text(encoding="utf-8")
        cls.comparison_script = (ROOT / "frontend" / "assets" / "js" / "geo-provider-comparison.js").read_text(encoding="utf-8")
        cls.comparison_styles = (ROOT / "frontend" / "assets" / "css" / "geo-provider-comparison.css").read_text(encoding="utf-8")
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

    def test_page_focuses_results_and_actions_on_mentions_by_platform(self):
        for label in ("Mention score", "Current mention rate", "Rolling mention rate", "Average mention rank"):
            self.assertIn(label, self.script)
        for removed in ("Citation rate", "Owned source rate", "Share of voice", "Prompt coverage"):
            self.assertNotIn(f'metric("{removed}"', self.script)
        self.assertIn("mention_rate_confidence_interval", self.script)
        self.assertIn("Mention evidence by prompt and platform", self.page)
        self.assertIn("Four-part GEO improvement plan", self.page)
        self.assertIn("4 action pillars per platform", self.page)
        self.assertIn("Monthly scan budget", self.page)
        self.assertIn("platform_summary", self.script)
        self.assertIn("finding.actions", self.script)
        self.assertIn("finding.action_pillars", self.script)
        for key in ("website", "authority_posts", "local_context", "crawler_technical"):
            self.assertIn(f'"geo.pillar.{key}"', (ROOT / "frontend" / "assets" / "js" / "app-preferences.js").read_text(encoding="utf-8"))
        self.assertIn("mention_rank", self.script)
        self.assertIn("insufficient sample", self.script)
        self.assertIn("rolling_summary", self.script)
        self.assertIn("No rank evidence", self.script)
        self.assertIn("Add 2–5 exact competitor names", self.page)

    def test_scan_builder_is_guided_and_models_have_local_vector_marks(self):
        for step in ("Set your target", "Choose AI search models", "Add customer questions"):
            self.assertIn(step, self.page)
        for provider in ("geo-model-openai", "geo-model-gemini", "geo-model-claude", "geo-model-deepseek",
                         "geo-model-perplexity"):
            self.assertIn(provider, self.page)
        self.assertNotIn("geo-model-google-ai", self.page)
        self.assertNotIn("geo-model-copilot", self.page)
        self.assertGreaterEqual(self.page.count('<svg viewBox="0 0 32 32"'), 5)
        self.assertIn("Improve brand matching", self.page)
        self.assertIn("data-prompt-example", self.page)
        self.assertIn("geo-run-equation", self.script)

    def test_workspace_pages_share_the_same_sidebar_component(self):
        for name in ("bots.html", "geo-analysis.html", "geo-provider-comparison.html", "team.html", "billing.html", "pricing.html"):
            page = (ROOT / "frontend" / name).read_text(encoding="utf-8")
            self.assertIn("<chatbot-sidebar></chatbot-sidebar>", page, name)
            self.assertIn('src="sidebar-component.js"', page, name)
        self.assertNotIn('id="bots-side-rail"', self.bots)
        for name in ("bots.html", "geo-analysis.html", "geo-provider-comparison.html", "team.html", "billing.html", "pricing.html"):
            self.assertIn(f'"{name}"', self.sidebar)
        self.assertIn("const botId = isWorkspacePage ? null : selectedBotId", self.sidebar)

    def test_comparison_page_makes_route_provenance_and_cost_visible(self):
        self.assertIn("Omnexa", self.comparison_page)
        self.assertIn("OpenRouter → OpenAI", self.comparison_page)
        self.assertIn("Two paid API calls", self.comparison_page)
        self.assertIn('json("/api/geo/provider-comparison"', self.comparison_script)
        self.assertIn("citation_domain_overlap_percent", self.comparison_script)
        self.assertIn("provider_output_truncated", self.comparison_script)
        self.assertNotIn("No answer returned. Check the API key, provider billing and model access.", self.comparison_script)
        self.assertIn('rel = "noopener noreferrer"', self.comparison_script)

    def test_geo_pages_use_readable_type_and_theme_aware_contrast(self):
        self.assertIn("--text-dim: color-mix", self.styles)
        self.assertIn('font: 650 28px "JetBrains Mono"', self.styles)
        self.assertIn("#geo-findings article ul", self.styles)
        self.assertIn("font-size: 12px; line-height: 1.6", self.styles)
        self.assertIn("geo-platform-sample-warning", self.styles)
        self.assertIn("geo-finding-observe", self.styles)
        self.assertIn("--route-dim: color-mix", self.comparison_styles)
        self.assertIn(".route-answer p", self.comparison_styles)
        self.assertIn("font-size: 14px; line-height: 1.75", self.comparison_styles)


if __name__ == "__main__":
    unittest.main()
