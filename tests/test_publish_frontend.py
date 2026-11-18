"""Static contract for the publish screen.

Replaces test_integration_channel_limit_frontend.py, which pinned exact source
strings from the old page ("Channel Limit Reached", the Manage/Connect
ternaries, the body of updatePlatformButton). Those strings described one
implementation, not a behaviour, so they could not survive the rebuild.

The behaviours they guarded are still asserted here and, where a browser is
needed, in tests/browser/publish.spec.js.
"""

import re

import pytest

from tests.frontend_pages import ROOT, WEB_PUBLIC_JS, page_source_path

PUBLISH_HTML = page_source_path("integration.html")
PUBLISH_CSS = ROOT / "frontend" / "assets" / "css" / "publish.css"
CONTROL_ROOM_CSS = ROOT / "frontend" / "assets" / "css" / "dashboard-control-room.css"


@pytest.fixture(scope="module")
def markup():
    return PUBLISH_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html(markup):
    return markup + (WEB_PUBLIC_JS / "integration.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css():
    return PUBLISH_CSS.read_text(encoding="utf-8")


def test_publish_page_joins_the_control_room_design_system(html, css):
    # The integration.html AppLayout order test in page-smoke.spec.js checks the
    # served shell stylesheet, all three font families and the exact body class.
    assert "publish.css" in html
    assert "dashboard-icon" in html

    # The legacy glass system is gone.
    assert "family=Outfit" not in html
    assert "#050b18" not in html
    assert "glass-card" not in html

    assert "@media (max-width: 768px)" in css
    assert "prefers-reduced-motion: reduce" in css


def test_every_publish_rule_is_namespaced(css):
    """A page stylesheet must not reach outside .dashboard-page."""
    for line in css.splitlines():
        if ".pub-" in line and not line.strip().startswith(("*", "/*")):
            assert ".dashboard-page" in line, line


def test_publish_reuses_the_shared_vocabulary_rather_than_twinning_it(html, css):
    for shared in ("kw-panel", "kw-btn", "kw-pill", "kw-dot", "kw-badge", "kw-idrow",
                   "kw-field", "kw-input", "kw-banner", "kw-step-mark", "kw-locked",
                   "kw-advanced", "kw-modal", "kw-desc", "kw-empty"):
        assert shared in html, shared

    # No pub- twin of something kw- already does.
    for twin in ("pub-code", "pub-copyline", "pub-risk", "pub-fieldgrid", "pub-modal"):
        assert twin not in css, twin


def test_the_disclosure_and_sr_only_patterns_were_promoted_not_copied():
    """Three byte-identical *-visually-hidden copies existed before this."""
    shared = CONTROL_ROOM_CSS.read_text(encoding="utf-8")
    assert ".dashboard-page .kw-visually-hidden" in shared
    assert ".dashboard-page .kw-advanced {" in shared

    for page_css in ("behaviour.css", "bot-config.css", "dashboard-overview.css"):
        text = (ROOT / "frontend" / "assets" / "css" / page_css).read_text(encoding="utf-8")
        assert "visually-hidden" not in text, page_css
    behaviour = (ROOT / "frontend" / "assets" / "css" / "behaviour.css").read_text(encoding="utf-8")
    assert "bh-advanced" not in behaviour


def test_self_certification_is_gone(html):
    """The user used to tell the system the setup worked. The server knows."""
    assert "Completed Setup" not in html
    assert "closeSetup" not in html
    # Every state is derived from a real check instead.
    assert "function channelState(" in html
    assert "connection_status" in html


def test_no_technical_word_on_the_default_path(markup):
    """Advanced provider forms are opt-in; rendered defaults are checked in Playwright."""
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", markup, flags=re.S).lower()
    for word in ("webhook", "verify token", "phone number id", "session id",
                 "bearer token", "app id"):
        assert word not in body, word


def test_no_emoji_and_no_em_dashes_in_page_chrome(html):
    assert "\u2014" not in html
    assert "\u2013" not in html
    emoji = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", html)
    assert not emoji, emoji


def test_dom_order_is_reading_order(html):
    order = re.findall(r'id="(pub-live|pub-add|pub-settings)"', html)
    assert order == ["pub-add", "pub-live", "pub-settings"]


def test_channel_choice_leads_and_the_snippet_is_demoted(html):
    live_at = html.index('id="pub-live"')
    add_at = html.index('id="pub-add"')
    assert add_at < live_at

    # Installation stays inside the website choice and a closed disclosure.
    assert 'id="pub-flow-website" hidden' in html
    assert '<summary>Install on an existing website</summary>' in html
    assert "Enable website and share link" in html


def test_every_settings_disclosure_starts_closed(html):
    for details in re.findall(r"<details[^>]*>", html):
        assert "open" not in details, details
    # AppLayout handles the saved theme. The publish page must not persist the open state.
    assert "localStorage" not in html


def test_channel_usage_still_comes_from_the_billing_endpoint(html):
    """Carried over from the replaced test: the limit is server-owned."""
    assert "/api/billing/usage" in html
    assert "data.usage" in html
    assert "channels.used" in html
    assert "channels.limit" in html
    assert "function planFull()" in html


def test_pro_channel_contract_recovers_from_a_stale_plan_row(html):
    assert "const PRO_CHANNEL_LIMIT = 4" in html
    assert "planCode === 'pro'" in html
    assert "Math.max(rawLimit, PRO_CHANNEL_LIMIT)" in html


def test_a_full_plan_is_explained_before_the_click_not_after(html):
    assert "planfull" in html
    assert "Plan full" in html
    assert "already in use" in html
    assert "pricing.html" in html


def test_unlimited_plans_are_never_blocked(html):
    plan_full = re.search(r"function planFull\(\) \{.*?\n        \}", html, flags=re.S).group(0)
    assert "e.limit === null" in plan_full
    assert "return false" in plan_full


def test_bot_scoping_contract_is_unchanged(html):
    assert "function resolveSelectedChatbotId()" in html
    assert "sessionStorage.setItem('selectedBotId', urlBotId)" in html
    assert "urlParams.get('bot_id')" in html


def test_dead_code_from_the_old_page_is_gone(html):
    for dead in ("toggleDropdown", "initSidebar", "getSafeAuthHeaders",
                 "platforms-grid", "Coming Soon"):
        assert dead not in html, dead
    # Blocking dialogs replaced by the design system's modal.
    assert "window.confirm" not in html
    assert re.search(r"\balert\(", html) is None


def test_the_qr_generator_is_vendored_and_local(html):
    assert "assets/js/qrcode-gen.js" in html
    assert (ROOT / "frontend" / "assets" / "js" / "qrcode-gen.js").exists()
    # No page-owned CDN loader. The integration.html AppLayout smoke branch
    # checks the served page allows only the shell's pinned Lucide script.
    assert "cdn.jsdelivr" not in html
    assert "unpkg.com" not in html


def test_the_only_external_script_is_loaded_on_demand(html):
    """The Facebook SDK is fetched when the owner clicks, not on page view."""
    assert "connect.facebook.net" in html
    assert '<script src="https://connect.facebook.net' not in html
    assert "function loadFacebookSdk(" in html


def test_wasender_choice_preserves_the_provider_risk_disclosure(html):
    assert "WhatsApp via Wasender" in html
    assert "Your number can" in html and "blocked" in html
    wasender = re.search(r"function wasenderDisclosure\(\) \{.*?\n        \}",
                         html, flags=re.S).group(0)
    assert "kw-advanced" in wasender
    assert "kw-locked" in wasender
    # Never primary, so it never reads as the recommended path.
    assert "kw-btn-primary" not in wasender


def test_whatchimp_choice_has_no_risk_warning_and_one_copy_source(html):
    """WhatChimp is an official Cloud API platform; its wording lives in one object."""
    assert "WhatsApp via WhatChimp" in html
    assert html.count("const WHATCHIMP_COPY = {") == 1
    flow = re.search(r"function whatchimpFlow\(\) \{.*?\n        \}", html, flags=re.S).group(0)
    assert "kw-locked" not in flow
