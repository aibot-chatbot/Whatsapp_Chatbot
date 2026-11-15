"""Built pages in web/dist shadow legacy frontend/ files one by one, at the same URLs."""

import pytest

import app as app_module
from app import frontend_files


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
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False))
    application = app_module.create_app()
    application.config["TESTING"] = True
    return application.test_client()


def test_a_built_page_wins_over_the_legacy_file(client):
    response = client.get("/pricing.html")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "built pricing"


def test_a_page_not_built_yet_falls_back_to_frontend(client):
    response = client.get("/landing.html")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "legacy landing"


def test_root_serves_the_built_landing_page_once_it_exists(client, roots):
    dist, _legacy = roots
    assert client.get("/").get_data(as_text=True) == "legacy landing"
    (dist / "landing.html").write_text("built landing", encoding="utf-8")
    assert client.get("/").get_data(as_text=True) == "built landing"


@pytest.mark.parametrize("path", [
    "/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/..%5csecret.txt",
    "/../frontend/landing.html",
])
def test_parent_directory_paths_are_refused(client, path):
    response = client.get(path)
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "outside both roots" not in body and "legacy landing" not in body
