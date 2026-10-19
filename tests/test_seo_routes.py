"""robots.txt, sitemap.xml and llms.txt: served publicly, built from FRONTEND_URL, honest."""

import re
import xml.etree.ElementTree as ET

import pytest

import app as app_module

SITE = "https://omnexa.example.test"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False, FRONTEND_URL=SITE + "/"))

    def no_network(*args, **kwargs):
        raise AssertionError("SEO route tests must not access external services")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("httpx.Client.send", no_network)
    application = app_module.create_app()
    application.config["TESTING"] = True
    return application.test_client()


def _allowed(robots, path):
    """RFC 9309 for the one group we publish: the longest matching rule wins, Allow wins ties."""
    best = (-1, True)
    for kind, pattern in re.findall(r"^(Allow|Disallow): (\S+)$", robots, re.M):
        regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\$", "$")
        if re.match(regex, path) and len(pattern) >= best[0]:
            best = max(best, (len(pattern), kind == "Allow"))
    return best[1]


def test_robots_opens_public_pages_and_closes_the_app(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    robots = response.get_data(as_text=True)

    assert f"Sitemap: {SITE}/sitemap.xml" in robots
    for crawler in ("Googlebot", "GPTBot", "ClaudeBot", "PerplexityBot", "OAI-SearchBot"):
        assert f"User-agent: {crawler}" in robots
    for public in ("/", "/privacy.html", "/terms.html", "/assets/css/legal.css", "/llms.txt"):
        assert _allowed(robots, public), public
    for private in ("/api/bots", "/bots.html", "/crm.html", "/media/a.pdf", "/widget/key", "/platform-admin.html"):
        assert not _allowed(robots, private), private


def test_sitemap_lists_only_crawlable_public_pages(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [loc.text or "" for loc in ET.fromstring(response.get_data()).findall("s:url/s:loc", ns)]
    assert locs == [f"{SITE}/", f"{SITE}/privacy.html", f"{SITE}/terms.html"]

    robots = client.get("/robots.txt").get_data(as_text=True)
    for loc in locs:
        assert _allowed(robots, loc[len(SITE):]), loc


def test_llms_txt_quotes_only_billed_prices_and_no_provider(client):
    response = client.get("/llms.txt")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert body.startswith("# Omnexa\n")
    assert f"]({SITE}/privacy.html)" in body
    assert "- Free, RM 0:" in body
    for plan in ("Essential", "Advanced", "Pro"):
        assert f"- {plan}: 1 month" in body
    allowed = {
        "RM 0", "RM 1", "RM 5", "RM 20", "RM 60",
        "RM 89.00", "RM 115.70", "RM 124.60", "RM 133.50", "RM 189.00",
        "RM 245.70", "RM 264.60", "RM 283.50", "RM 374.00", "RM 486.20",
        "RM 523.60", "RM 561.00", "RM 373.80", "RM 694.20", "RM 793.80",
        "RM 1,068.00", "RM 1,474.20", "RM 1,570.80", "RM 2,268.00",
        "RM 2,917.20", "RM 4,488.00",
    }
    assert set(re.findall(r"RM\s?\d+(?:[.,]\d+)*", body)) <= allowed
    assert "7-day free trial" in body
    for provider in ("Cloudflare", "OpenRouter"):
        assert provider not in body
