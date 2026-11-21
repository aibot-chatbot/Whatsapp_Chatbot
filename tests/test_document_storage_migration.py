import io
import json
import runpy
from pathlib import Path

import pytest

from app.services import document_storage_migration as migration
from app.services import document_storage_service as storage


@pytest.fixture
def migration_store(monkeypatch, tmp_path):
    data, media, legacy = tmp_path / "data", tmp_path / "data/media_uploads", tmp_path / "legacy"
    media.mkdir(parents=True)
    legacy.mkdir()
    objects = {}
    monkeypatch.setenv("R2_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("R2_BUCKET_UPLOADS", "synthetic-documents")
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "r2")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "synthetic")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "synthetic")

    class Client:
        def put_object(self, *, Bucket, Key, Body, **kwargs):
            objects[Key] = Body.read()

        def get_object(self, *, Bucket, Key):
            return {"Body": io.BytesIO(objects[Key]), "ContentLength": len(objects[Key])}

    client = Client()
    monkeypatch.setattr(storage, "_create_client", lambda *args: client)
    return data, media, legacy, objects, client


def test_migration_verifies_all_artifacts_and_keeps_mounted_media_precedence(migration_store):
    data, media, legacy, objects, _ = migration_store
    files = {data / "historical.pdf": b"pdf", data / "bot_7_12_readme.md": b"readme",
             data / "bot_7_readme.md": b"active", data / "bot_7_12_history.json": b"[]",
             data / "_pdf_candidates/7/12.pdf": b"candidate", media / "clip.mp4": b"current",
             legacy / "clip.mp4": b"old", legacy / "brochure.pdf": b"brochure"}
    for path, payload in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (data / "schema.sql").write_text("synthetic schema")
    (media / ".r2-incomplete").write_bytes(b"incomplete")

    result = migration.migrate_existing_files(data, media, legacy)

    assert result["files"] == 7
    assert result["bytes"] == sum(len(value) for value in objects.values())
    assert objects["media/clip.mp4"] == b"current"
    assert objects["knowledge/_pdf_candidates/7/12.pdf"] == b"candidate"
    assert "knowledge/media_uploads/clip.mp4" not in objects
    assert not any("schema.sql" in key or ".r2-" in key for key in objects)
    assert all(path.read_bytes() == payload for path, payload in files.items())
    assert json.loads((data / ".r2-migration-complete.json").read_text())["files"] == 7


def test_completed_migration_never_resurrects_remote_deleted_documents(migration_store):
    data, media, legacy, objects, _ = migration_store
    (data / "old.pdf").write_bytes(b"document")
    expected = migration.migrate_existing_files(data, media, legacy)
    objects.clear()
    assert migration.migrate_existing_files(data, media, legacy) == expected
    assert objects == {}


def test_checksum_failure_preserves_original_and_prevents_completion(migration_store, monkeypatch):
    data, media, legacy, objects, client = migration_store
    original = data / "document.pdf"
    original.write_bytes(b"original")
    monkeypatch.setattr(client, "get_object", lambda **kwargs: {"Body": io.BytesIO(b"corrupt")})
    with pytest.raises(storage.DocumentStorageError, match="checksum"):
        migration.migrate_existing_files(data, media, legacy)
    assert original.read_bytes() == b"original"
    assert not (data / ".r2-migration-complete.json").exists()


def test_marker_from_another_bucket_cannot_skip_migration(migration_store, monkeypatch):
    data, media, legacy, _, _ = migration_store
    (data / "document.pdf").write_bytes(b"document")
    migration.migrate_existing_files(data, media, legacy)
    monkeypatch.setenv("R2_BUCKET_UPLOADS", "different-documents")
    with pytest.raises(storage.DocumentStorageError, match="destination"):
        migration.migrate_existing_files(data, media, legacy)


def test_empty_or_missing_inventory_cannot_be_marked_complete(migration_store):
    data, media, legacy, objects, _ = migration_store
    with pytest.raises(storage.DocumentStorageError, match="minimum"):
        migration.migrate_existing_files(data, media, legacy, expected_min_files=43)
    assert not (data / ".r2-migration-complete.json").exists()
    assert not objects


def test_source_change_blocks_cutover(migration_store, monkeypatch):
    data, media, legacy, _, client = migration_store
    source = data / "source.pdf"
    source.write_bytes(b"before")
    original_get = client.get_object

    def concurrent_get(**kwargs):
        response = original_get(**kwargs)
        source.write_bytes(b"after")
        return response

    monkeypatch.setattr(client, "get_object", concurrent_get)
    with pytest.raises(storage.DocumentStorageError, match="changed"):
        migration.migrate_existing_files(data, media, legacy)
    assert not (data / ".r2-migration-complete.json").exists()


def test_wsgi_migration_completes_before_application_creation(monkeypatch):
    import app

    order = []
    monkeypatch.setattr(migration, "migrate_before_startup", lambda: order.append("migration"))
    monkeypatch.setattr(app, "create_app", lambda: order.append("application"))
    monkeypatch.setenv("BILLING_SCHEDULER_ENABLED", "false")
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "wsgi.py"))
    assert order == ["migration", "application"]
