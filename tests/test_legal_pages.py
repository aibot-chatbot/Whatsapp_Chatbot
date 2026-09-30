"""Privacy Policy and Terms pages: complete, linked from sign-up, and served publicly."""

import re
from pathlib import Path

import pytest

import app as app_module

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PAGES = ("privacy.html", "terms.html")


def read(name):
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_section_counts_match_the_source_documents():
    privacy, terms = read("privacy.html"), read("terms.html")
    assert len(re.findall(r'id="en-s\d+"', privacy)) == 21
    assert len(re.findall(r'id="ms-s\d+"', privacy)) == 21
    assert len(re.findall(r'id="t-s\d+"', terms)) == 17


@pytest.mark.parametrize("page", PAGES)
def test_every_in_page_link_points_at_a_real_anchor(page):
    source = read(page)
    ids = set(re.findall(r'id="([^"]+)"', source))
    targets = re.findall(r'href="#([^"]+)"', source)
    assert targets and set(targets) <= ids


@pytest.mark.parametrize("page", PAGES)
def test_docx_template_placeholders_do_not_leak(page):
    source = read(page)
    assert not re.search(r"[\[\]]", source), "a [bracketed] docx placeholder reached the page"
    assert "need update" not in source


def test_operator_name_uses_a_single_spelling():
    spellings = {
        m.group(1).lower()
        for page in PAGES
        for m in re.finditer(r"Meta (Realty|Reality) Sdn Bhd", read(page), re.I)
    }
    assert len(spellings) == 1


def test_registration_consent_links_to_the_real_pages():
    consent = re.search(r"I agree to the.*?</p>", read("register.html"), re.S).group(0)
    assert 'href="terms.html"' in consent and 'href="privacy.html"' in consent
    assert 'href="#"' not in consent


def test_landing_footer_legal_links_resolve():
    landing = read("landing.html")
    for page in PAGES:
        assert f'href="{page}"' in landing and (FRONTEND / page).is_file()


def test_terms_defers_to_the_privacy_policy():
    assert 'href="privacy.html"' in read("terms.html")


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


@pytest.mark.parametrize("path,needle", [
    ("/privacy.html", 'id="en-s21"'),
    ("/terms.html", 'id="t-s17"'),
    ("/assets/css/legal.css", ".ver-title"),
])
def test_legal_pages_are_served_without_signing_in(client, path, needle):
    response = client.get(path)
    assert response.status_code == 200
    assert needle in response.get_data(as_text=True)
