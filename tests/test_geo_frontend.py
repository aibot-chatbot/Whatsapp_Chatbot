import unittest
from pathlib import Path

from tests.frontend_pages import page_source_path


ROOT = Path(__file__).resolve().parents[1]


class GeoFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = page_source_path("geo-analysis.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "frontend" / "assets" / "js" / "geo-analysis.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "frontend" / "assets" / "css" / "geo-analysis.css").read_text(encoding="utf-8")
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
        # The sign-in gate and the SRI-pinned lucide tag come from AppLayout now, so they are checked as
        # served: tests/browser/geo-keywords.spec.js ("a signed-out visitor is sent to the sign-in page")
        # and page-smoke.spec.js ("pages on AppLayout load the shared shell in the fixed order").
        self.assertIn('json("/api/geo/capabilities")', self.script)
        self.assertIn('json(`/api/geo/analyses?limit=${limit}`)', self.script)
        self.assertNotIn("company_id", self.script)
        self.assertIn("script.integrity = 'sha384-", self.sidebar)

    def test_page_focuses_results_and_actions_on_mentions_by_platform(self):
        for label in ("Mention score", "Current mention rate", "Rolling mention rate", "Average mention rank"):
            self.assertIn(label, self.script)
        for removed in ("Citation rate", "Owned source rate", "Share of voice", "Prompt coverage"):
            self.assertNotIn(f'metric("{removed}"', self.script)
        self.assertIn("mention_rate_confidence_interval", self.script)
        # Copy pins follow the live GEO restore (6319ae4, Fly v89): each keyword is one buyer question per model.
        self.assertIn("Mention evidence by buyer question and platform", self.page)
        self.assertIn("Evidence-based improvement plan", self.page)
        self.assertIn("Prompt, competitor and source evidence", self.page)
        self.assertIn("Monthly scan budget", self.page)
        self.assertIn("platform_summary", self.script)
        self.assertIn("finding.actions", self.script)
        self.assertIn("finding.action_pillars", self.script)
        for key in ("website", "authority_posts", "local_context", "crawler_technical"):
            self.assertIn(f'"geo.pillar.{key}"', (ROOT / "frontend" / "assets" / "js" / "app-preferences.js").read_text(encoding="utf-8"))
        self.assertIn("mention_rank", self.script)
        self.assertIn("single-run evidence", self.script)
        self.assertIn("rolling_summary", self.script)
        self.assertIn("No rank evidence", self.script)
        self.assertIn("Add 2–5 exact competitor names", self.page)

    def test_scan_builder_is_guided_and_models_have_local_vector_marks(self):
        for step in ("Set your target", "Choose AI search models", "Add buyer keywords"):
            self.assertIn(step, self.page)
        for provider in ("geo-model-openai", "geo-model-gemini", "geo-model-claude", "geo-model-deepseek",
                         "geo-model-perplexity"):
            self.assertIn(provider, self.page)
        self.assertNotIn("geo-model-google-ai", self.page)
        self.assertNotIn("geo-model-copilot", self.page)
        self.assertGreaterEqual(self.page.count('<svg viewBox="0 0 32 32"'), 5)
        self.assertIn("Improve brand matching", self.page)
        self.assertIn("data-keyword-example", self.page)
        self.assertIn('id="geo-keyword-input"', self.page)
        self.assertIn('id="geo-keyword-list"', self.page)
        self.assertIn("geo-keyword-chip", self.script)
        self.assertIn('event.key === "Enter"', self.script)
        self.assertIn('event.key === "Backspace"', self.script)
        self.assertIn("state.keywords.length >= limit", self.script)
        self.assertIn("keywords: [...state.keywords]", self.script)
        self.assertNotIn('id="geo-prompts"', self.page)
        self.assertIn("geo-run-equation", self.script)
        self.assertIn("Each keyword is measured independently on every selected model", self.script)
        self.assertIn("samples_per_prompt: 1", self.script)

    def test_keyword_ui_and_dynamic_messages_are_translatable(self):
        preferences = (ROOT / "frontend" / "assets" / "js" / "app-preferences.js").read_text(encoding="utf-8")
        for key in ("geo.keyword.remove", "geo.keyword.duplicate", "geo.keyword.limit",
                    "geo.keyword.brand_bias", "geo.keyword.required", "geo.keyword.help",
                    "geo.keyword.equation", "geo.keyword.remaining"):
            self.assertEqual(preferences.count(f'"{key}"'), 3)
        self.assertIn("Mention evidence by buyer question and platform", self.page)
        self.assertIn("Buyer questions × selected live APIs", self.page)

    def test_public_pricing_describes_ten_keyword_geo_scans(self):
        landing = page_source_path("landing.html").read_text(encoding="utf-8")
        self.assertEqual(landing.count("Up to 10 keywords per GEO analysis"), 3)
        self.assertNotIn("prompts per GEO analysis", landing)

    def test_workspace_pages_share_the_same_sidebar_component(self):
        self.assertNotIn('id="bots-side-rail"', self.bots)
        for name in ("bots.html", "geo-analysis.html", "geo-provider-comparison.html", "team.html", "billing.html", "pricing.html"):
            self.assertIn(f'"{name}"', self.sidebar)
        self.assertIn("const botId = isWorkspacePage ? null : selectedBotId", self.sidebar)

    def test_comparison_page_makes_route_provenance_and_cost_visible(self):
        # The page copy (both routes named, the cost badge) is checked as rendered in
        # tests/browser/geo-provider-comparison.spec.js; the page is built by Astro now.
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
