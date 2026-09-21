"""Stamp the tenant marker onto R2 knowledge objects written before it existed.

New uploads carry ``chatbot_id`` in their custom metadata because
``app/services/document_storage_service.py`` attaches it at ``put_object`` time
from the caller's authenticated chatbot id. Objects written before that change
carry nothing, so a retrieval filter would silently never match them.

R2 cannot mutate an object's metadata in place. The operation is a
``copy_object`` onto the same key with ``MetadataDirective="REPLACE"``, which
rewrites every system header too -- so this script reads each object's existing
headers first and puts them back unchanged. The bytes are never re-uploaded and
the key never changes.

Resolving the tenant
--------------------
For a historical object the key is the only record that survives. These keys
were not user-supplied: ``knowledge/bot_<chatbot_id>_<uuid4>_<secure_filename>``
was built by the application from the chatbot id that had already passed
``verify_chatbot_access`` at upload time. This script therefore reads the id
from that fixed prefix, and refuses every key that does not match it exactly --
including ``knowledge/_pdf_candidates/**``, which holds abandoned upload
candidates that are excluded from indexing and are never tenant knowledge.

This key-reading is correct only for the one-time historical set. Never copy it
into the write path: a key is an identifier, not an authorization fact, and a
second source of truth for the tenant would drift silently.

Usage (operator machine holding the R2 credentials; this file does not ship in
the container and needs no database access)::

    export R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... \
           R2_SECRET_ACCESS_KEY=... R2_BUCKET_UPLOADS=aibot-client-documents

    python scripts/backfill_r2_tenant_metadata.py            # dry run, writes nothing
    python scripts/backfill_r2_tenant_metadata.py --apply    # rewrites metadata

Re-running is a no-op: an object whose ``chatbot_id`` already matches is
skipped, so a partial run is resumed rather than repeated.
"""

import argparse
import os
import re
import sys

#: Only the immediate children of ``knowledge/`` were written with the tenant
#: prefix. Anything nested (candidates) or differently shaped is not resolvable.
KNOWLEDGE_PREFIX = "knowledge/"
TENANT_KEY = re.compile(r"knowledge/bot_(\d{1,64})_[^/]+")

#: Rewritten verbatim on the copy. ``MetadataDirective="REPLACE"`` drops every
#: header it is not given, and losing ``ContentType`` alone would make the
#: object unindexable.
PRESERVED_HEADERS = (
    "ContentType", "CacheControl", "ContentDisposition",
    "ContentEncoding", "ContentLanguage",
)

REQUIRED_ENV = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_UPLOADS")


def build_client():
    """Create the R2 client from the environment, reporting only names."""
    import boto3
    from botocore.config import Config

    values = {name: os.getenv(name, "").strip() for name in REQUIRED_ENV}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SystemExit("Missing R2 configuration: " + ", ".join(missing))
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{values['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=values["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=30,
                      retries={"mode": "standard", "total_max_attempts": 3},
                      s3={"addressing_style": "path"}),
    )
    return client, values["R2_BUCKET_UPLOADS"]


def resolve_chatbot_id(key):
    """Return the chatbot id this key records, or None when it records none."""
    match = TENANT_KEY.fullmatch(key)
    return match.group(1) if match else None


def error_code(error):
    """A provider error code, without the endpoint or credential detail."""
    response = getattr(error, "response", None) or {}
    return response.get("Error", {}).get("Code") or type(error).__name__


def plan_object(client, bucket, key, chatbot_id):
    """Return the copy arguments for this key, or None when it is already marked."""
    head = client.head_object(Bucket=bucket, Key=key)
    metadata = dict(head.get("Metadata") or {})
    if metadata.get("chatbot_id") == chatbot_id:
        return None
    metadata["chatbot_id"] = chatbot_id
    arguments = {
        "Bucket": bucket, "Key": key,
        "CopySource": {"Bucket": bucket, "Key": key},
        "MetadataDirective": "REPLACE",
        "Metadata": metadata,
        # An object stored without a type must not silently become one.
        "ContentType": head.get("ContentType") or "application/octet-stream",
    }
    for header in PRESERVED_HEADERS:
        if header != "ContentType" and head.get(header):
            arguments[header] = head[header]
    return arguments


def backfill(client, bucket, apply_changes):
    """Walk the knowledge prefix once and report updated/skipped/failed."""
    updated = skipped = failed = 0
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=KNOWLEDGE_PREFIX):
        for entry in page.get("Contents") or []:
            key = entry["Key"]
            chatbot_id = resolve_chatbot_id(key)
            if chatbot_id is None:
                skipped += 1
                print(f"skip   {key}  (no chatbot id in this key shape)")
                continue
            try:
                arguments = plan_object(client, bucket, key, chatbot_id)
                if arguments is None:
                    skipped += 1
                    print(f"skip   {key}  (chatbot_id={chatbot_id} already set)")
                    continue
                if apply_changes:
                    client.copy_object(**arguments)
                updated += 1
                print(f"{'update' if apply_changes else 'would '} {key}  chatbot_id={chatbot_id}")
            except Exception as error:  # noqa: BLE001 - one bad object must not stop the walk
                failed += 1
                print(f"FAIL   {key}  ({error_code(error)})", file=sys.stderr)
    return updated, skipped, failed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Add the chatbot_id tenant marker to existing R2 knowledge objects.",
        epilog="Dry run by default. Pass --apply to rewrite object metadata.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="rewrite metadata; without it nothing is written")
    arguments = parser.parse_args(argv)

    client, bucket = build_client()
    if not arguments.apply:
        print("DRY RUN -- nothing will be written. Re-run with --apply to change objects.\n")
    updated, skipped, failed = backfill(client, bucket, arguments.apply)

    verb = "updated" if arguments.apply else "would update"
    print(f"\n{verb}: {updated}  skipped: {skipped}  failed: {failed}")
    return 1 if (failed and arguments.apply) else 0


if __name__ == "__main__":
    raise SystemExit(main())
