"""Privacy Policy and Terms pages: complete, linked from sign-up, and served publicly."""

import re
from pathlib import Path

import pytest

import app as app_module
from tests.frontend_pages import page_source_path

ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
# Astro builds web/src/pages/<name>.astro to the legacy /<name>.html URL.
PAGES = {
    "privacy.html": WEB_SRC / "pages" / "privacy.astro",
    "terms.html": WEB_SRC / "pages" / "terms.astro",
}
LAYOUT = WEB_SRC / "layouts" / "LegalLayout.astro"


def markup(path):
    """The template of an .astro file: its `---` frontmatter script is not page content."""
    source = path.read_text(encoding="utf-8")
    stripped = re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", source, count=1, flags=re.S)
    assert stripped != source, f"{path.name} has no frontmatter to strip"
    return stripped


def page(name):
    return markup(PAGES[name])


def page_with_layout(name):
    # The layout owns the head, skip link and header, so whole-page checks read both.
    return markup(LAYOUT) + page(name)


def test_section_counts_match_the_source_documents():
    privacy, terms = page("privacy.html"), page("terms.html")
    assert len(re.findall(r'id="en-s\d+"', privacy)) == 21
    assert len(re.findall(r'id="ms-s\d+"', privacy)) == 21
    assert len(re.findall(r'id="t-s\d+"', terms)) == 17


@pytest.mark.parametrize("name", PAGES)
def test_every_in_page_link_points_at_a_real_anchor(name):
    source = page_with_layout(name)
    ids = set(re.findall(r'id="([^"]+)"', source))
    targets = re.findall(r'href="#([^"]+)"', source)
    assert "content" in targets, "the layout's skip link must be checked too"
    assert targets and set(targets) <= ids


@pytest.mark.parametrize("name", PAGES)
def test_docx_template_placeholders_do_not_leak(name):
    source = page_with_layout(name)
    assert not re.search(r"[\[\]]", source), "a [bracketed] docx placeholder reached the page"
    assert "need update" not in source


def test_operator_name_uses_a_single_spelling():
    landing = page_source_path("landing.html").read_text(encoding="utf-8")  # its trust block names the operator too
    sources = [page(name) for name in PAGES] + [landing]
    spellings = {
        m.group(1).lower()
        for source in sources
        for m in re.finditer(r"Meta (Realty|Reality) Sdn Bhd", source, re.I)
    }
    assert len(spellings) == 1


def test_privacy_policy_names_cloudflare_in_both_languages():
    # Customer pages never name the AI platform, so the privacy policy is where it must be disclosed:
    # Cloudflare serves AI replies, stores uploaded documents and runs the message queue.
    english, malay = page("privacy.html").split('id="ms"', 1)
    assert "Cloudflare" in english and "Cloudflare" in malay


def test_registration_consent_links_to_the_real_pages():
    register = (WEB_SRC / "pages" / "register.astro").read_text(encoding="utf-8")
    consent = re.search(r"I agree to the.*?</p>", register, re.S).group(0)
    assert 'href="terms.html"' in consent and 'href="privacy.html"' in consent
    assert 'href="#"' not in consent


def test_landing_footer_legal_links_resolve():
    landing = page_source_path("landing.html").read_text(encoding="utf-8")
    for name, source in PAGES.items():
        assert f'href="{name}"' in landing and source.is_file()


def test_terms_defers_to_the_privacy_policy():
    assert 'href="privacy.html"' in page("terms.html")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False))

    def no_network(*args, **kwargs):
        raise AssertionError("Legal page tests must not access external services")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("httpx.Client.send", no_network)
    application = app_module.create_app()
    application.config["TESTING"] = True
    return application.test_client()


# The pages themselves are built by Astro; tests/browser/page-smoke.spec.js checks them as served.
def test_legal_stylesheet_is_served_without_signing_in(client):
    response = client.get("/assets/css/legal.css")
    assert response.status_code == 200
    assert ".ver-title" in response.get_data(as_text=True)
