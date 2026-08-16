from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_HTML = ROOT / "frontend" / "index.html"
DASHBOARD_CSS = ROOT / "frontend" / "assets" / "css" / "dashboard-control-room.css"


def test_dashboard_keeps_bot_scoped_runtime_contract():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert "sessionStorage.setItem(\"selectedBotId\", selectedBotId)" in html
    assert "`/api/bots/${selectedBotId}`" in html
    assert "`/api/analytics?chatbot_id=${selectedBotId}`" in html
    assert "`/api/dashboard/health?chatbot_id=${selectedBotId}`" in html
    assert "`/api/dashboard/live-workflow?chatbot_id=${selectedBotId}`" in html


def test_dashboard_uses_stitch_control_room_design_contract():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    css = DASHBOARD_CSS.read_text(encoding="utf-8")

    assert "dashboard-control-room.css" in html
    assert "family=Geist" in html
    assert "family=JetBrains+Mono" in html
    assert "family=Space+Grotesk" in html
    assert 'class="dashboard-page"' in html
    assert "dashboard-icon" in html
    assert "Material+Symbols" not in html
    assert "dashboard-guide" in html
    assert "data-dashboard-link" in html
    assert "⚡" not in html
    assert "📉" not in html
    assert "📜" not in html

    for token in (
        "--control-canvas: #0e0f11",
        "--control-panel: #16181b",
        "--control-accent: #3e9c89",
        "--font-heading: 'Space Grotesk'",
        "--font-body: 'Geist'",
        "--font-mono: 'JetBrains Mono'",
    ):
        assert token in css

    assert "@media (max-width: 768px)" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ".dashboard-page [hidden]" in css


def test_dashboard_guidance_links_keep_selected_bot_context():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert "function updateDashboardLinks()" in html
    assert "document.querySelectorAll('[data-dashboard-link]')" in html
    assert "url.searchParams.set('bot_id', selectedBotId)" in html


def test_dashboard_dom_order_matches_visual_reading_order():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    assert html.index('class="stats-grid"') < html.index('class="glass-card dashboard-guide"')
    assert html.index('class="glass-card dashboard-guide"') < html.index('class="glass-card bot-health"')
    assert html.index('class="glass-card bot-health"') < html.index('class="glass-card live-workflow"')

