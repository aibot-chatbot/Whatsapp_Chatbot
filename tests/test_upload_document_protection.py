"""Document protections use synthetic bytes and never call external services."""

import io
from unittest.mock import Mock

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.test import EnvironBuilder

import app as app_module
from app import views
from app.routes import knowledge_routes
from app.services import knowledge_service, pdf_relevance_validation_service as candidates
from app.services import upload_validation_service as validation


@pytest.fixture
def protected_client(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "MEDIA_FOLDER", str(tmp_path))
    monkeypatch.setattr(app_module, "LEGACY_MEDIA_FOLDER", str(tmp_path))
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False))
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **kw: {"user_id": 17})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda user_id: {
        "id": user_id, "company_id": 7, "role": "owner", "status": "active"})
    for module in (views, knowledge_routes):
        monkeypatch.setattr(module, "verify_chatbot_access", lambda chatbot_id: {"company_id": 7})
        monkeypatch.setattr(module, "can_upload_knowledge_file", lambda *args: None)
        monkeypatch.setattr(module, "can_upload_knowledge_storage", lambda *args: None)
    monkeypatch.setattr(knowledge_routes, "get_active_knowledge_file", lambda chatbot_id: {"id": 1})
    monkeypatch.setattr("app.routes.media_attachment_routes.verify_chatbot_access", lambda chatbot_id: {"company_id": 7})

    def no_network(*args, **kwargs):
        raise AssertionError("Document protection tests must not contact external services")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("httpx.Client.send", no_network)
    application = app_module.create_app()
    application.config["TESTING"] = True
    application.add_url_rule("/api/_private-test.pdf", endpoint="private_api_test", view_func=lambda: ("private", 200, {
        "Cache-Control": "public, max-age=3600", "CDN-Cache-Control": "public"}))
    application.add_url_rule("/_private-test", endpoint="private_auth_test", view_func=lambda: "private")
    return application.test_client()


@pytest.mark.parametrize("path,field", [
    ("/upload-pdf", "pdf_file"),
    ("/api/knowledge/pdf-candidates/validate", "pdf_file"),
    ("/api/media-attachments/upload", "media_file"),
])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("stricter_config", [False, True])
def test_every_upload_bounds_multipart_before_saving(protected_client, monkeypatch, tmp_path, path, field, streaming, stricter_config):
    # Exercise the route default and stricter operator configuration separately.
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 2048)
    protected_client.application.config["MAX_CONTENT_LENGTH"] = 1024 if stricter_config else None
    save_primary = Mock()
    save_candidate = Mock()
    monkeypatch.setattr(views, "save_uploaded_pdf", save_primary)
    monkeypatch.setattr(knowledge_routes, "validate_supporting_pdf_candidate", save_candidate)
    builder = EnvironBuilder(path=path + "?chatbot_id=42", method="POST",
        headers={"Authorization": "Bearer test"},
        data={field: (io.BytesIO(b"%PDF-1.4\n" + b"x" * (1100 if stricter_config else 2200)), "large.pdf")})
    environ = builder.get_environ()
    if streaming:
        environ.pop("CONTENT_LENGTH", None)
        environ["wsgi.input_terminated"] = True
    try:
        response = protected_client.open(environ)
        assert response.status_code == 413
        assert response.is_json
        save_primary.assert_not_called()
        save_candidate.assert_not_called()
        assert not list(tmp_path.iterdir())
    finally:
        environ["wsgi.input"].close()
        builder.close()


@pytest.mark.parametrize("path,headers", [
    ("/api/_private-test.pdf", {}),
    ("/api/missing-document.pdf", {}),
    ("/upload-pdf", {}),
    ("/_private-test", {"Authorization": "Bearer test"}),
    ("/media/report.pdf", {}),
])
def test_sensitive_success_and_error_responses_cannot_be_cached(protected_client, tmp_path, path, headers):
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4\nsynthetic")
    response = protected_client.get(path, headers=headers)
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["CDN-Cache-Control"] == "no-store"
    assert response.headers["Cloudflare-CDN-Cache-Control"] == "no-store"
    if path.startswith("/media/"):
        assert response.headers["Referrer-Policy"] == "no-referrer"


def test_public_static_assets_keep_existing_cache_behavior(protected_client):
    response = protected_client.get("/static/assets/js/plan-catalog.js")
    assert response.status_code == 200
    assert "no-store" not in response.headers.get("Cache-Control", "")


@pytest.mark.parametrize("entrypoint", ["primary", "candidate"])
@pytest.mark.parametrize("payload,error", [
    (b"<html>not a PDF</html>", ValueError),
    (b"", ValueError),
    (b"%PDF-1.4\n" + b"x" * 64, RequestEntityTooLarge),
])
def test_invalid_documents_leave_no_file_or_record(monkeypatch, tmp_path, entrypoint, payload, error):
    monkeypatch.setattr(validation, "MAX_UPLOAD_BYTES", 64)
    monkeypatch.setattr(candidates, "MAX_UPLOAD_BYTES", 64)
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    monkeypatch.setattr(candidates, "CANDIDATE_DATA_FOLDER", str(tmp_path))
    save_record = Mock()
    create_candidate = Mock()
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", save_record)
    monkeypatch.setattr(candidates, "create_candidate", create_candidate)
    upload = FileStorage(stream=io.BytesIO(payload), filename="client.pdf")
    with pytest.raises(error):
        if entrypoint == "primary":
            knowledge_service.save_uploaded_pdf(upload, 42)
        else:
            candidates.validate_supporting_pdf_candidate(upload, 42, 7, 17, 0.65,
                primary_file={"id": 1, "file_type": "pdf"})
    save_record.assert_not_called()
    create_candidate.assert_not_called()
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_pdf_signature_check_accepts_exact_size_limit(monkeypatch, tmp_path):
    payload = b"%PDF-1.4\nsynthetic"
    monkeypatch.setattr(validation, "MAX_UPLOAD_BYTES", len(payload))
    document = tmp_path / "valid.pdf"
    document.write_bytes(payload)
    assert validation.validate_saved_pdf(document) == len(payload)


@pytest.mark.parametrize("module,path,save_name", [
    (views, "/upload-pdf", "save_uploaded_pdf"),
    (knowledge_routes, "/api/knowledge/pdf-candidates/validate", "validate_supporting_pdf_candidate"),
])
def test_pdf_upload_denies_other_tenant_before_saving(protected_client, monkeypatch, module, path, save_name):
    monkeypatch.setattr(module, "verify_chatbot_access", Mock(side_effect=PermissionError("private tenant data")))
    save = Mock()
    monkeypatch.setattr(module, save_name, save)
    response = protected_client.post(path + "?chatbot_id=43",
        headers={"Authorization": "Bearer test"},
        data={"pdf_file": (io.BytesIO(b"%PDF-1.4\n"), "client.pdf")})
    assert response.status_code == 403
    assert "private tenant data" not in response.get_data(as_text=True)
    save.assert_not_called()


@pytest.mark.parametrize("module,path,save_name", [
    (views, "/upload-pdf", "save_uploaded_pdf"),
    (knowledge_routes, "/api/knowledge/pdf-candidates/validate", "validate_supporting_pdf_candidate"),
])
def test_pdf_storage_permission_failure_is_private_server_error(protected_client, monkeypatch, module, path, save_name):
    monkeypatch.setattr(module, save_name, Mock(side_effect=PermissionError("private storage path")))
    response = protected_client.post(path + "?chatbot_id=42",
        headers={"Authorization": "Bearer test"},
        data={"pdf_file": (io.BytesIO(b"%PDF-1.4\n"), "client.pdf")})
    assert response.status_code == 500
    assert "private storage path" not in response.get_data(as_text=True)
