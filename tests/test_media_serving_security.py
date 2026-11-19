"""Uploaded bytes must never become an active page on the application's origin."""

import io
from pathlib import Path
from urllib.parse import urlsplit

import jwt
import pytest
from werkzeug.test import EnvironBuilder

import app as app_module
from app.decorators import auth_decorator
from app.routes import media_attachment_routes


@pytest.mark.parametrize("streaming", [False, True])
def test_oversized_upload_returns_413_without_saving(media_client, streaming):
    client, primary, _ = media_client
    client.application.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    token = jwt.encode({"user_id": 17}, auth_decorator.get_jwt_secret(), algorithm="HS256")
    builder = EnvironBuilder(path="/api/media-attachments/upload?chatbot_id=42", method="POST",
        headers={"Authorization": f"Bearer {token}"},
        data={"media_file": (io.BytesIO(b"x" * 65536), "large.pdf")})
    environ = builder.get_environ()
    if streaming:
        environ.pop("CONTENT_LENGTH", None)
        environ["wsgi.input_terminated"] = True
    try:
        assert client.open(environ).status_code == 413
        assert not list(primary.iterdir())
    finally:
        environ["wsgi.input"].close()
        builder.close()


@pytest.fixture
def media_client(monkeypatch, tmp_path):
    primary = tmp_path / "media"
    legacy = tmp_path / "legacy"
    primary.mkdir()
    legacy.mkdir()
    monkeypatch.setattr(app_module, "MEDIA_FOLDER", str(primary))
    monkeypatch.setattr(app_module, "LEGACY_MEDIA_FOLDER", str(legacy))
    monkeypatch.setattr("app.storage_paths.MEDIA_FOLDER", str(primary))
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False))
    monkeypatch.setattr(auth_decorator, "get_jwt_secret", lambda: "synthetic-media-test-secret-value-32-bytes")
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda user_id: {
        "id": user_id, "company_id": 7, "role": "owner", "status": "active"})
    monkeypatch.setattr(media_attachment_routes, "verify_chatbot_access", lambda chatbot_id: {
        "id": chatbot_id, "company_id": 7})

    def no_network(*args, **kwargs):
        raise AssertionError("Media regression tests must not access external services")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("httpx.Client.send", no_network)
    application = app_module.create_app()
    application.config["TESTING"] = True
    return application.test_client(), primary, legacy


@pytest.mark.parametrize("filename,payload", [
    ("page.html", b"<script>sessionStorage.getItem('token')</script>"),
    ("image.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'),
    ("page.xhtml", b'<html xmlns="http://www.w3.org/1999/xhtml"><script>alert(1)</script></html>'),
    ("image.SVG", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'),
    ("unknown", b"<script>alert(1)</script>"),
])
@pytest.mark.parametrize("storage", ["upload", "legacy"])
def test_active_uploads_are_downloaded_and_sandboxed(media_client, filename, payload, storage):
    client, _, legacy = media_client
    if storage == "upload":
        token = jwt.encode({"user_id": 17}, auth_decorator.get_jwt_secret(), algorithm="HS256")
        uploaded = client.post(
            "/api/media-attachments/upload?chatbot_id=42",
            headers={"Authorization": f"Bearer {token}"},
            data={"media_file": (io.BytesIO(payload), filename)},
        )
        assert uploaded.status_code == 201
        media_path = urlsplit(uploaded.json["data"]["public_url"]).path
    else:
        (legacy / filename).write_bytes(payload)
        media_path = f"/media/{filename}"

    # Anonymous provider fetches still work, without making an app-origin page.
    response = client.get(media_path)
    assert response.status_code == 200
    assert response.data == payload
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    directives = {item.strip() for item in response.headers["Content-Security-Policy"].split(";")}
    assert "sandbox" in directives
    assert "default-src 'none'" in directives


@pytest.mark.parametrize("filename,mimetype", [
    ("photo.png", "image/png"),
    ("photo.jpg", "image/jpeg"),
    ("animation.gif", "image/gif"),
    ("recording.mp3", "audio/mpeg"),
    ("clip.mp4", "video/mp4"),
])
@pytest.mark.parametrize("storage", ["primary", "legacy"])
def test_passive_media_keeps_inline_mime_and_range_support(media_client, filename, mimetype, storage):
    client, primary, legacy = media_client
    payload = b"synthetic provider download content"
    ((primary if storage == "primary" else legacy) / filename).write_bytes(payload)
    response = client.get(f"/media/{filename}", headers={"Range": "bytes=0-8"})
    assert response.status_code == 206
    assert response.data == payload[:9]
    assert response.mimetype == mimetype
    assert response.headers["Content-Disposition"].startswith("inline;")
    assert response.headers["Content-Security-Policy"] == "sandbox allow-same-origin"


def test_media_downloads_stay_inside_storage_roots(media_client, tmp_path):
    client, _, _ = media_client
    (tmp_path / "outside.txt").write_text("private synthetic data", encoding="utf-8")
    for path in ("/media/../outside.txt", "/media/%2e%2e/outside.txt", "/media/missing.txt"):
        assert client.get(path).status_code == 404


def test_repeated_upload_names_do_not_replace_existing_public_assets(media_client):
    client, primary, _ = media_client
    token = jwt.encode({"user_id": 17}, auth_decorator.get_jwt_secret(), algorithm="HS256")
    paths = []
    for payload in (b"first synthetic brochure", b"replacement synthetic brochure"):
        response = client.post(
            "/api/media-attachments/upload?chatbot_id=42",
            headers={"Authorization": f"Bearer {token}"},
            data={"media_file": (io.BytesIO(payload), "brochure.pdf")},
        )
        assert response.status_code == 201
        paths.append(urlsplit(response.json["data"]["public_url"]).path)
    assert paths[0] != paths[1]
    assert client.get(paths[0]).data == b"first synthetic brochure"
    assert client.get(paths[1]).data == b"replacement synthetic brochure"
    assert len(list(primary.iterdir())) == 2


def test_r2_media_uses_remote_bytes_with_existing_provider_range_support(media_client, monkeypatch):
    from app.services import document_storage_service as storage
    client, primary, _ = media_client
    (primary / "clip.mp4").write_bytes(b"stale local bytes")
    monkeypatch.setattr(storage, "r2_enabled", lambda: True)

    def materialize(path, *, root, namespace):
        assert root == str(primary) and namespace == "media"
        assert Path(path) == primary / "clip.mp4"
        (primary / "clip.mp4").write_bytes(b"authoritative remote bytes")
        return path

    monkeypatch.setattr(storage, "materialize_file", materialize)
    response = client.get("/media/clip.mp4", headers={"Range": "bytes=0-8"})
    assert response.status_code == 206
    assert response.data == b"authorita"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Content-Security-Policy"] == "sandbox allow-same-origin"


@pytest.mark.parametrize("missing", [True, False])
def test_r2_failure_never_serves_stale_or_legacy_media(media_client, monkeypatch, missing):
    from app.services import document_storage_service as storage
    client, primary, legacy = media_client
    for folder in (primary, legacy):
        (folder / "private.pdf").write_bytes(b"stale private bytes")
    monkeypatch.setattr(storage, "r2_enabled", lambda: True)

    def fail(*args, **kwargs):
        if missing:
            raise FileNotFoundError("synthetic deleted R2 object")
        raise storage.DocumentStorageError("synthetic provider private detail")

    monkeypatch.setattr(storage, "materialize_file", fail)
    response = client.get("/media/private.pdf")
    assert response.status_code == (404 if missing else 503)
    assert b"stale private bytes" not in response.data
    assert b"synthetic" not in response.data
    assert response.headers["Cloudflare-CDN-Cache-Control"] == "no-store"


@pytest.mark.parametrize("filename", ["payload.js", "payload.mjs", "payload.css"])
def test_uploads_are_never_served_as_script_or_stylesheet(media_client, filename):
    # With nosniff a browser refuses a script or stylesheet of any other type, so an upload
    # can never satisfy the page CSP's 'self' in script-src or style-src.
    client, primary, _ = media_client
    (primary / filename).write_bytes(b"alert(1)")
    response = client.get(f"/media/{filename}")
    assert response.status_code == 200
    assert response.mimetype == "application/octet-stream"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("url", ["javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x",
                                 "/media/x.pdf", "https:no-host", 7])
def test_attachment_urls_must_be_absolute_http(media_client, monkeypatch, url):
    # The card renders media_url as a link, and providers fetch it, so only http(s) URLs are stored.
    client, _, _ = media_client
    saved = []
    monkeypatch.setattr(media_attachment_routes, "create_attachment", lambda *args: saved.append(args) or {"id": 1})
    monkeypatch.setattr(media_attachment_routes, "update_attachment", lambda *args: saved.append(args) or {"id": 1})
    monkeypatch.setattr(media_attachment_routes, "get_attachment_by_id", lambda *args: {"id": 1})
    token = jwt.encode({"user_id": 17}, auth_decorator.get_jwt_secret(), algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/media-attachments?chatbot_id=3", headers=headers,
                       json={"label": "Brochure", "media_url": url}).status_code == 400
    assert client.put("/api/media-attachments/1?chatbot_id=3", headers=headers,
                      json={"media_url": url}).status_code == 400
    assert saved == []
    assert client.post("/api/media-attachments?chatbot_id=3", headers=headers,
                       json={"label": "Brochure", "media_url": "https://cdn.example.test/a.pdf"}).status_code == 201


@pytest.mark.parametrize("path", ["/widget/..%2F/favicon.svg", "/chat/..%2F/favicon.svg",
                                  "/media/..%2F/favicon.svg", "/api/widget/..%2F..%2F/favicon.svg"])
def test_dot_segments_never_reach_frontend_files(media_client, path):
    # Header exemptions are decided on the request path, so a page reached through "<prefix>/../"
    # would be served without the page CSP and X-Frame-Options.
    client, _, _ = media_client
    assert client.get("/favicon.svg").status_code == 200
    assert client.get(path).status_code == 404
