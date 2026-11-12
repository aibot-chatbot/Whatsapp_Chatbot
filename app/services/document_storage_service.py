"""Private file storage with local materializations for existing PDF consumers.

Database paths stay unchanged. In R2 mode the remote object is authoritative;
an existing local file is never a fallback for a missing or unavailable object.
"""

import mimetypes
import os
import re
import shutil
import tempfile
from contextlib import closing
from functools import lru_cache

from app.services.upload_validation_service import MAX_UPLOAD_BYTES


class DocumentStorageError(RuntimeError):
    """A sanitized storage error safe for application error handling."""


def r2_enabled():
    backend = os.getenv("DOCUMENT_STORAGE_BACKEND", "local").strip().lower()
    if backend not in {"local", "r2"}:
        raise DocumentStorageError("DOCUMENT_STORAGE_BACKEND must be local or r2.")
    return backend == "r2"


def validate_storage_configuration():
    """Validate explicit configuration without contacting the network."""
    if not r2_enabled():
        return
    account, access_key, secret_key, bucket = _configuration()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account):
        raise DocumentStorageError("R2_ACCOUNT_ID must be a Cloudflare account ID.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise DocumentStorageError("R2_BUCKET_UPLOADS must be a valid bucket name.")


def _configuration():
    names = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_UPLOADS")
    values = tuple(os.getenv(name, "").strip() for name in names)
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise DocumentStorageError("R2 storage configuration is missing: " + ", ".join(missing) + ".")
    return values


@lru_cache(maxsize=1)
def _create_client(account, access_key, secret_key):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=30,
            retries={"mode": "standard", "total_max_attempts": 3},
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _client_and_bucket():
    validate_storage_configuration()
    account, access_key, secret_key, bucket = _configuration()
    try:
        return _create_client(account, access_key, secret_key), bucket
    except Exception:
        raise DocumentStorageError("Document storage is unavailable.") from None


def _safe_path_and_key(path, root, namespace):
    if namespace not in {"knowledge", "media", "reports"}:
        raise DocumentStorageError("Invalid document storage namespace.")
    try:
        resolved_root = os.path.realpath(os.path.abspath(os.fspath(root)))
        resolved_path = os.path.realpath(os.path.abspath(os.fspath(path)))
        if resolved_path == resolved_root or os.path.commonpath((resolved_root, resolved_path)) != resolved_root:
            raise ValueError("outside root")
        relative = os.path.relpath(resolved_path, resolved_root)
        # Reject alternate data streams on Windows and ambiguous portable keys.
        if ":" in relative or "\x00" in relative:
            raise ValueError("invalid path")
    except (OSError, TypeError, ValueError):
        raise DocumentStorageError("Invalid document storage path.") from None
    return resolved_path, namespace + "/" + relative.replace(os.sep, "/")


def _missing_object(error):
    response = getattr(error, "response", {})
    return response.get("Error", {}).get("Code") in {"NoSuchKey", "NotFound", "404"}


#: A tenant marker reaches R2 as an ``x-amz-meta-*`` HTTP header and is indexed
#: for retrieval filtering, where only the first 64 UTF-8 bytes of a string are
#: matched. Restricting it to a short header-safe token keeps the value both
#: injection-free and comparable.
_TENANT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _tenant_metadata(chatbot_id, company_id):
    """Build the tenant markers from caller-supplied ids, never from the key.

    An id the caller cannot express as a safe token is omitted rather than
    failing the upload. Omission is the closed direction: an object carrying no
    ``chatbot_id`` matches no tenant's retrieval filter, so it becomes invisible
    rather than shared. Storage never derives these from the object key -- a key
    is an identifier, not an authorization fact.
    """
    metadata = {}
    for name, value in (("chatbot_id", chatbot_id), ("company_id", company_id)):
        if value is None:
            continue
        text = str(value).strip()
        if _TENANT_ID.fullmatch(text):
            metadata[name] = text
    return metadata


def persist_file(path, *, root, namespace, chatbot_id=None, company_id=None):
    """Persist a validated local file before its caller reports success."""
    safe_path, key = _safe_path_and_key(path, root, namespace)
    if not r2_enabled():
        return safe_path
    client, bucket = _client_and_bucket()
    markers = _tenant_metadata(chatbot_id, company_id)
    try:
        with open(safe_path, "rb") as document:
            size = os.fstat(document.fileno()).st_size
            if size > MAX_UPLOAD_BYTES:
                raise DocumentStorageError("Document exceeds the storage size limit.")
            client.put_object(
                Bucket=bucket, Key=key, Body=document, ContentLength=size,
                ContentType=mimetypes.guess_type(safe_path)[0] or "application/octet-stream",
                CacheControl="private, no-store",
                **({"Metadata": markers} if markers else {}),
            )
    except DocumentStorageError:
        raise
    except Exception:
        raise DocumentStorageError("Document could not be stored.") from None
    return safe_path


def write_file(path, content, *, root, namespace, chatbot_id=None, company_id=None):
    """Persist generated bytes without reopening a concurrently replaced cache."""
    safe_path, key = _safe_path_and_key(path, root, namespace)
    if not isinstance(content, bytes) or len(content) > MAX_UPLOAD_BYTES:
        raise DocumentStorageError("Generated document exceeds the storage size limit or is invalid.")
    if r2_enabled():
        client, bucket = _client_and_bucket()
        markers = _tenant_metadata(chatbot_id, company_id)
        try:
            client.put_object(
                Bucket=bucket, Key=key, Body=content, ContentLength=len(content),
                ContentType=mimetypes.guess_type(safe_path)[0] or "application/octet-stream",
                CacheControl="private, no-store",
                **({"Metadata": markers} if markers else {}),
            )
        except Exception:
            raise DocumentStorageError("Generated document could not be stored.") from None

    temporary_path = None
    try:
        directory = os.path.dirname(safe_path)
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".r2-", dir=directory, delete=False) as temporary:
            temporary_path = temporary.name
            temporary.write(content)
        os.replace(temporary_path, safe_path)
        temporary_path = None
    except OSError:
        raise DocumentStorageError("Generated document local copy could not be saved.") from None
    finally:
        if temporary_path is not None:
            try:
                os.remove(temporary_path)
            except OSError:
                pass
    return safe_path


def materialize_file(path, *, root, namespace):
    """Fetch the authoritative object into an atomically replaced local file."""
    safe_path, key = _safe_path_and_key(path, root, namespace)
    if not r2_enabled():
        if not os.path.isfile(safe_path):
            raise FileNotFoundError("Document was not found.")
        return safe_path
    client, bucket = _client_and_bucket()
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if _missing_object(exc):
            raise FileNotFoundError("Document was not found.") from None
        raise DocumentStorageError("Document could not be retrieved.") from None

    temporary_path = None
    try:
        with closing(response["Body"]) as body:
            length = response.get("ContentLength")
            if not isinstance(length, int) or length < 0 or length > MAX_UPLOAD_BYTES:
                raise DocumentStorageError("Document exceeds the storage size limit or has an invalid length.")
            directory = os.path.dirname(safe_path)
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".r2-", dir=directory, delete=False) as temporary:
                temporary_path = temporary.name
                total = 0
                while True:
                    chunk = body.read(min(1024 * 1024, MAX_UPLOAD_BYTES - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES or total > length:
                        raise DocumentStorageError("Document exceeds its expected storage length.")
                    temporary.write(chunk)
                if total != length:
                    raise DocumentStorageError("Document download was incomplete.")
            os.replace(temporary_path, safe_path)
            temporary_path = None
    except DocumentStorageError:
        raise
    except Exception:
        raise DocumentStorageError("Document could not be retrieved.") from None
    finally:
        if temporary_path is not None:
            try:
                os.remove(temporary_path)
            except OSError:
                pass
    return safe_path


def file_exists(path, *, root, namespace):
    safe_path, key = _safe_path_and_key(path, root, namespace)
    if not r2_enabled():
        return os.path.isfile(safe_path)
    client, bucket = _client_and_bucket()
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if _missing_object(exc):
            return False
        raise DocumentStorageError("Document storage could not be checked.") from None
    return True


def delete_file(path, *, root, namespace):
    """Delete remote first; a failed deletion must remain visible to callers."""
    safe_path, key = _safe_path_and_key(path, root, namespace)
    if r2_enabled():
        client, bucket = _client_and_bucket()
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            raise DocumentStorageError("Document could not be deleted from storage.") from None
    try:
        os.remove(safe_path)
    except FileNotFoundError:
        pass
    except OSError:
        raise DocumentStorageError("Document local copy could not be deleted.") from None


def delete_tree(directory, *, root, namespace):
    """Delete every object stored under one directory, remote first, then the local copies.

    For erasing a whole tenant scope (a deleted workspace's reports, say). The key prefix
    always ends in "/", so reports/4 can never match reports/42. Like delete_file, a remote
    failure raises before anything local is removed.
    """
    safe_directory, key = _safe_path_and_key(directory, root, namespace)
    if r2_enabled():
        client, bucket = _client_and_bucket()
        failed, token = 0, None
        try:
            while True:
                page = client.list_objects_v2(
                    Bucket=bucket, Prefix=key + "/", **({"ContinuationToken": token} if token else {}))
                for item in page.get("Contents") or []:
                    try:
                        client.delete_object(Bucket=bucket, Key=item["Key"])
                    except Exception:
                        failed += 1
                token = page.get("NextContinuationToken")
                if not page.get("IsTruncated") or not token:
                    break
        except Exception:
            raise DocumentStorageError("Stored documents could not be listed for deletion.") from None
        if failed:
            raise DocumentStorageError("Some stored documents could not be deleted.")
    try:
        shutil.rmtree(safe_directory)
    except FileNotFoundError:
        pass
    except OSError:
        raise DocumentStorageError("Local document copies could not be deleted.") from None
