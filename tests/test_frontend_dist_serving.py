"""Built pages in web/dist shadow legacy frontend/ files one by one, at the same URLs."""

import pytest

import app as app_module
from app import frontend_files
from app.csp_policy import page_csp_header


@pytest.fixture
def roots(tmp_path):
    dist, legacy = tmp_path / "dist", tmp_path / "frontend"
    dist.mkdir()
    legacy.mkdir()
    (legacy / "landing.html").write_text("legacy landing", encoding="utf-8")
    (legacy / "pricing.html").write_text("legacy pricing", encoding="utf-8")
    (dist / "pricing.html").write_text("built pricing", encoding="utf-8")
    # Sits beside both roots: reachable only if a path escapes them.
    (tmp_path / "secret.txt").write_text("outside both roots", encoding="utf-8")
    return dist, legacy


@pytest.fixture
def client(monkeypatch, roots):
    dist, legacy = roots
    monkeypatch.setattr(frontend_files, "WEB_DIST_DIR", str(dist))
    monkeypatch.setattr(frontend_files, "FRONTEND_DIR", str(legacy))
    monkeypatch.setattr(app_module, "MEDIA_FOLDER", str(legacy.parent / "media"))
    monkeypatch.setattr(app_module, "LEGACY_MEDIA_FOLDER", str(legacy.parent / "legacy-media"))
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False))
    application = app_module.create_app()
    application.config["TESTING"] = True
    return application.test_client()


def test_a_built_page_wins_over_the_legacy_file(client):
    response = client.get("/pricing")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "built pricing"
    assert response.mimetype == "text/html"
    assert response.headers["Content-Security-Policy"] == page_csp_header(None)


def test_a_page_not_built_yet_falls_back_to_frontend(client):
    response = client.get("/landing")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "legacy landing"


def test_root_serves_the_built_landing_page_once_it_exists(client, roots):
    dist, _legacy = roots
    assert client.get("/").get_data(as_text=True) == "legacy landing"
    (dist / "landing.html").write_text("built landing", encoding="utf-8")
    assert client.get("/").get_data(as_text=True) == "built landing"


@pytest.mark.parametrize("method,url,destination", [
    ("GET", "/accept-invite.html?token=abc&next=%2fbots&q=a+b&q=c", "/accept-invite?token=abc&next=%2fbots&q=a+b&q=c"),
    ("GET", "/landing.html", "/"),
    ("HEAD", "/pricing.html?plan=team", "/pricing?plan=team"),
    ("GET", "/pricing/?plan=team", "/pricing?plan=team"),
    ("HEAD", "/landing/", "/landing"),
])
def test_existing_page_redirects_to_its_clean_url(client, roots, method, url, destination):
    _, legacy = roots
    (legacy / "accept-invite.html").write_text("invite", encoding="utf-8")
    response = client.open(url, method=method)
    assert response.status_code == 301
    assert response.headers["Location"] == destination
    assert response.headers["Cache-Control"] == "public, max-age=3600"
    if method == "HEAD":
        assert response.data == b""


def test_post_keeps_existing_html_fallback(client, roots):
    _, legacy = roots
    (legacy / "login.html").write_text("login", encoding="utf-8")
    response = client.post("/login.html")
    assert response.status_code == 200
    assert response.data == b"login"
    assert client.post("/login").status_code == 404


def test_clean_aliases_apply_only_to_existing_top_level_pages(client, roots, monkeypatch):
    _, legacy = roots
    (legacy / "widget-chat.html").write_text("widget", encoding="utf-8")
    assets = legacy / "assets" / "js"
    assets.mkdir(parents=True)
    (assets / "x.js").write_text("script", encoding="utf-8")
    (assets / "x.html").write_text("nested page", encoding="utf-8")
    monkeypatch.setattr("app.routes.widget_routes.resolve_public_widget", lambda key: ({}, {}))
    monkeypatch.setattr("app.services.document_storage_service.r2_enabled", lambda: False)
    assert client.get("/widget-chat.html").data == b"widget"
    assert client.get("/widget/x").headers["Content-Security-Policy"] == "frame-ancestors *"
    assert client.get("/assets/js/x.js").data == b"script"
    assert client.get("/assets/js/x.html").data == b"nested page"
    for url in ("/widget-chat", "/widget-chat/", "/WIDGET-CHAT", "/assets/js/x", "/assets/js/x/",
                "/api/x", "/media/x", "/unknown", "/unknown/", "/unknown.html"):
        assert client.get(url).status_code == 404, url


@pytest.mark.parametrize("path", [
    "/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/..%5csecret.txt",
    "/../frontend/landing.html",
])
def test_parent_directory_paths_are_refused(client, path):
    response = client.get(path)
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "outside both roots" not in body and "legacy landing" not in body
