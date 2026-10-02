"""One-time, verified R2 cutover before the single application worker starts."""

import hashlib
import json
import os
import re
import tempfile
from contextlib import closing
from pathlib import Path

from app.services import document_storage_service as storage
from app.services.upload_validation_service import MAX_UPLOAD_BYTES


def _sources(data_root, media_root, legacy_root):
    """Admit document artifacts and preserve mounted-media precedence."""
    sources = {}
    for path in data_root.rglob("*"):
        relative = path.relative_to(data_root)
        if path.is_symlink():
            raise storage.DocumentStorageError("Migration encountered an unsafe document path.")
        if path.is_relative_to(media_root) or path.name.startswith(".r2-"):
            continue
        admitted = (
            len(relative.parts) == 1 and (
                path.suffix.lower() == ".pdf"
                or re.fullmatch(r"bot_.+_(?:readme\.md|history\.json)", path.name)
            )
        ) or (relative.parts[0] == "_pdf_candidates" and path.suffix.lower() == ".pdf")
        if admitted:
            if path.is_symlink() or not path.is_file():
                raise storage.DocumentStorageError("Migration encountered an unsafe document path.")
            sources["knowledge/" + relative.as_posix()] = (path, data_root, "knowledge")
    for root in (legacy_root, media_root):
        if not root.exists():
            continue
        if root.is_symlink():
            raise storage.DocumentStorageError("Migration encountered an unsafe media root.")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise storage.DocumentStorageError("Migration encountered an unsafe media path.")
            if path.is_file() and not path.name.startswith(".r2-"):
                relative = path.relative_to(root).as_posix()
                sources["media/" + relative] = (path, root, "media")
    return sources


def _digest(stream):
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise storage.DocumentStorageError("Migration document exceeds the storage size limit.")
        digest.update(chunk)
    return size, digest.hexdigest()


def migrate_existing_files(data_root, media_root, legacy_root, expected_min_files=1):
    """Run only with the previous local-storage worker stopped; keep originals."""
    storage.validate_storage_configuration()
    if not storage.r2_enabled():
        raise storage.DocumentStorageError("R2 must be configured before migration.")
    data_root, media_root, legacy_root = map(Path, (data_root, media_root, legacy_root))
    if data_root.is_symlink() or not data_root.is_dir():
        raise storage.DocumentStorageError("Migration requires the existing data volume.")
    identity = {"version": 1, "account_id": os.environ["R2_ACCOUNT_ID"],
                "bucket": os.environ["R2_BUCKET_UPLOADS"]}
    marker = data_root / ".r2-migration-complete.json"
    if marker.exists():
        if marker.is_symlink():
            raise storage.DocumentStorageError("Migration marker is unsafe.")
        result = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or any(result.get(key) != value for key, value in identity.items()):
            raise storage.DocumentStorageError("Migration marker does not match this R2 destination.")
        if (type(result.get("files")) is not int or result["files"] < 1
                or type(result.get("bytes")) is not int or result["bytes"] < 0
                or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("manifest_sha256", "")))):
            raise storage.DocumentStorageError("Migration marker is incomplete.")
        return result

    sources = _sources(data_root, media_root, legacy_root)
    if expected_min_files < 1 or len(sources) < expected_min_files:
        raise storage.DocumentStorageError("Migration inventory is below the verified minimum.")
    client, bucket = storage._client_and_bucket()
    manifest = hashlib.sha256()
    total_bytes = 0
    for key, (path, root, namespace) in sorted(sources.items()):
        with path.open("rb") as document:
            expected = _digest(document)
        storage.persist_file(path, root=root, namespace=namespace)
        try:
            remote = client.get_object(Bucket=bucket, Key=key)
            with closing(remote["Body"]) as body:
                actual = _digest(body)
        except Exception:
            raise storage.DocumentStorageError("Migration remote readback failed.") from None
        if actual != expected:
            raise storage.DocumentStorageError("Migration checksum verification failed.")
        with path.open("rb") as document:
            if _digest(document) != expected:
                raise storage.DocumentStorageError("Migration source changed during copy.")
        total_bytes += expected[0]
        manifest.update(f"{key}\0{expected[0]}\0{expected[1]}\n".encode("utf-8"))
    result = dict(identity, files=len(sources), bytes=total_bytes,
                  manifest_sha256=manifest.hexdigest())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".r2-",
                                         dir=data_root, delete=False) as output:
            temporary = output.name
            json.dump(result, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, marker)
        temporary = None
        if os.name != "nt":
            directory_fd = os.open(data_root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return result


def migrate_before_startup():
    if os.getenv("R2_INITIAL_MIGRATION", "").strip().lower() not in {"1", "true", "yes"}:
        return
    try:
        from app.services.knowledge_service import DATA_FOLDER
        from app.storage_paths import LEGACY_MEDIA_FOLDER, MEDIA_FOLDER

        minimum = int(os.getenv("R2_MIGRATION_MIN_FILES", "1"))
        result = migrate_existing_files(DATA_FOLDER, MEDIA_FOLDER, LEGACY_MEDIA_FOLDER, minimum)
    except Exception:
        raise storage.DocumentStorageError("R2 migration did not complete; application startup stopped.") from None
    print(f"R2 initial migration verified: {result['files']} files, {result['bytes']} bytes.", flush=True)
