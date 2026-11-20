"""tests/frontend_pages.py: a page's source follows it from frontend/ to web/src/pages/."""

import pytest

import tests.frontend_pages as frontend_pages


@pytest.fixture
def roots(tmp_path, monkeypatch):
    pages, legacy = tmp_path / "pages", tmp_path / "frontend"
    pages.mkdir()
    monkeypatch.setattr(frontend_pages, "WEB_PAGES", pages)
    monkeypatch.setattr(frontend_pages, "FRONTEND", legacy)
    return pages, legacy


def test_page_source_moves_to_the_astro_page_once_it_exists(roots):
    pages, legacy = roots
    assert frontend_pages.page_source_path("landing.html") == legacy / "landing.html"
    (pages / "landing.astro").write_text("", encoding="utf-8")
    assert frontend_pages.page_source_path("landing.html") == pages / "landing.astro"


def test_a_missing_page_resolves_to_a_missing_legacy_file(roots):
    # Callers that check .exists() must see False, not a stray match.
    assert not frontend_pages.page_source_path("nowhere.html").exists()


@pytest.mark.parametrize("name", ["docs/landing.html", "landing", "landing.htm"])
def test_names_that_are_not_top_level_pages_are_refused(roots, name):
    (roots[0] / "landing.astro").write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        frontend_pages.page_source_path(name)
