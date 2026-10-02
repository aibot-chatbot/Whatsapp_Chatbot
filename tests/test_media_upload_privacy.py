"""Media uploads must reject foreign tenants without exposing backend details."""

import io
from unittest.mock import Mock

import jwt
import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

from app.decorators import auth_decorator
from app.routes import media_attachment_routes


@pytest.fixture
def upload_client(monkeypatch, tmp_path):
    secret = "synthetic-upload-privacy-test-secret-32-bytes"
    monkeypatch.setattr(auth_decorator, "get_jwt_secret", lambda: secret)
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda user_id: {
        "id": user_id, "company_id": 7, "role": "owner", "status": "active"})
    monkeypatch.setattr(media_attachment_routes, "verify_chatbot_access", lambda chatbot_id: {
        "id": chatbot_id, "company_id": 7})
    monkeypatch.setattr("app.storage_paths.MEDIA_FOLDER", str(tmp_path))

    def no_network(*args, **kwargs):
        raise AssertionError("Upload privacy tests must not access external services")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("httpx.Client.send", no_network)
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.register_blueprint(media_attachment_routes.media_attachment_blueprint)
    token = jwt.encode({"user_id": 17}, secret, algorithm="HS256")
    return application.test_client(), {"Authorization": f"Bearer {token}"}, tmp_path


def test_foreign_chatbot_upload_is_forbidden_before_file_save(upload_client, monkeypatch, caplog):
    client, headers, upload_folder = upload_client
    private_detail = "synthetic foreign-company private document path"
    access = Mock(side_effect=PermissionError(private_detail))
    save = Mock()
    monkeypatch.setattr(media_attachment_routes, "verify_chatbot_access", access)
    monkeypatch.setattr(FileStorage, "save", save)

    response = client.post("/api/media-attachments/upload?chatbot_id=42", headers=headers,
        data={"media_file": (io.BytesIO(b"synthetic file content"), "private.pdf")})

    assert response.status_code == 403
    assert response.json["message"] == "You do not have access to this chatbot."
    access.assert_called_once_with(42)
    save.assert_not_called()
    assert not list(upload_folder.iterdir())
    assert private_detail not in response.get_data(as_text=True) + caplog.text


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_storage_failure_does_not_expose_document_or_backend_details(
        upload_client, monkeypatch, caplog, error_type):
    client, headers, _ = upload_client
    private_detail = "synthetic /private/client-document.pdf secret=synthetic-provider-key"
    monkeypatch.setattr(FileStorage, "save", Mock(side_effect=error_type(private_detail)))

    response = client.post("/api/media-attachments/upload?chatbot_id=42", headers=headers,
        data={"media_file": (io.BytesIO(b"synthetic file content"), "private.pdf")})

    assert response.status_code == 500
    assert response.json["message"] == "Unable to upload the media file. Please try again."
    assert private_detail not in response.get_data(as_text=True) + caplog.text
    assert f"Upload media attachment failed ({error_type.__name__})" in caplog.text


def test_upload_requires_authentication_before_access_or_file_save(upload_client, monkeypatch):
    client, _, upload_folder = upload_client
    access = Mock()
    monkeypatch.setattr(media_attachment_routes, "verify_chatbot_access", access)

    response = client.post("/api/media-attachments/upload?chatbot_id=42",
        data={"media_file": (io.BytesIO(b"synthetic file content"), "private.pdf")})

    assert response.status_code == 401
    access.assert_not_called()
    assert not list(upload_folder.iterdir())


def test_remote_storage_failure_removes_new_upload_without_returning_share_url(
        upload_client, monkeypatch, caplog):
    client, headers, upload_folder = upload_client
    private_detail = "synthetic R2 credentials and private document path"
    persist = Mock(side_effect=RuntimeError(private_detail))
    monkeypatch.setattr(media_attachment_routes, "persist_file", persist)

    response = client.post("/api/media-attachments/upload?chatbot_id=42", headers=headers,
        data={"media_file": (io.BytesIO(b"synthetic file content"), "private.pdf")})

    assert response.status_code == 500
    assert "public_url" not in response.get_data(as_text=True)
    assert not list(upload_folder.iterdir())
    assert persist.call_args.kwargs == {
        "root": str(upload_folder), "namespace": "media", "chatbot_id": 42}
    assert private_detail not in response.get_data(as_text=True) + caplog.text
