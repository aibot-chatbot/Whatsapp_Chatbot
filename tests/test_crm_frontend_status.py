from pathlib import Path

from tests.frontend_pages import page_source_path


# The page source: web/src/pages/crm.astro once Astro builds it, else frontend/crm.html.
CRM_HTML = page_source_path("crm.html")
CRM_JS = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "js" / "insights-actions.js"
CRM_CSS = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "css" / "insights-actions.css"
REPORTS_HTML = Path(__file__).resolve().parents[1] / "frontend" / "reports.html"


def test_insights_actions_consumes_the_canonical_lead_stages():
    html = CRM_HTML.read_text(encoding="utf-8")
    js = CRM_JS.read_text(encoding="utf-8")

    for status in ("new", "contacted", "qualified", "won", "lost"):
        assert f'data-status-card="{status}"' in html
        assert f'option value="{status}"' in html

    assert "counts.new + counts.contacted + counts.qualified" in js
    assert "counts.won + counts.lost" in js
    assert 'option value="in_progress"' not in html
    assert 'option value="closed"' not in html


def test_insights_actions_normalizes_retired_read_values():
    html = CRM_JS.read_text(encoding="utf-8")

    assert 'in_progress: "contacted"' in html
    assert 'closed: "lost"' in html


def test_insights_actions_workspace_preserves_public_frontend_contracts():
    html = CRM_HTML.read_text(encoding="utf-8")
    js = CRM_JS.read_text(encoding="utf-8")

    assert "Insights &amp; Actions" in html
    assert "Here’s what needs attention today" in html
    assert 'data-view-panel="today"' in html
    assert 'data-view-panel="leads"' in html
    assert 'data-view-panel="performance"' in html
    assert 'data-view-panel="signals"' in html
    assert 'id="signals-tab"' in html
    assert 'id="lead-type-filter"' in html
    assert 'id="lead-assignment-filter"' in html
    assert "canViewSignals()" in js

    for request_path in (
        "`/api/bots/${encodeURIComponent(selectedBotId)}`",
        "`/api/crm/leads?chatbot_id=${encodeURIComponent(selectedBotId)}`",
        "`/api/crm/leads/${encodeURIComponent(lead.id)}`",
        "`/api/analytics?chatbot_id=${encodeURIComponent(selectedBotId)}`",
        "`/api/analytics/report?chatbot_id=${encodeURIComponent(selectedBotId)}&days=${encodeURIComponent(days)}`",
        "`/api/agent/insights?chatbot_id=${encodeURIComponent(selectedBotId)}`",
    ):
        assert request_path in js

    assert 'sessionStorage.setItem("selectedBotId", selectedBotId)' in js
    assert 'params.get("tab") === "ai-signals"' in js


def test_insights_actions_uses_control_room_visual_and_accessibility_contract():
    html = CRM_HTML.read_text(encoding="utf-8")
    css = CRM_CSS.read_text(encoding="utf-8")

    # The head and <body> come from AppLayout now, so they are checked as served: the control-room CSS
    # and the Geist / JetBrains Mono / Space Grotesk fonts in page-smoke.spec.js ("pages on AppLayout
    # load the shared shell in the fixed order"), and the body class in insights-actions.spec.js.
    assert 'aria-live="polite"' in html
    assert 'role="tablist"' in html
    assert "@media (max-width: 768px)" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "glassmorphism" not in css


def test_reports_page_redirects_to_performance_view_and_preserves_bot_context():
    html = REPORTS_HTML.read_text(encoding="utf-8")

    assert 'new URL("crm.html", window.location.href)' in html
    assert 'current.get("bot_id") || sessionStorage.getItem("selectedBotId")' in html
    assert 'destination.searchParams.set("view", "performance")' in html
    assert "window.location.replace(destination.href)" in html
