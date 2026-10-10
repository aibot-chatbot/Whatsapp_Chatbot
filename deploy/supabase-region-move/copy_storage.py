"""Copy every Supabase Storage bucket and object from the old project to the new one.

Run through move.sh: python -I copy_storage.py <secrets_dir> <old_ref> <new_ref>
Re-runnable: uploads upsert. Public objects are checked afterwards by comparing
the headers both projects serve. Keys are read from files and never printed.
"""

import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests

TIMEOUT = 60
PAGE = 100
MAIN_ENV = Path(r"C:\Users\Vincent\Desktop\Whatsapp_Chatbot\.env")
COMPARED_HEADERS = ("content-length", "content-type", "cache-control")


def env_value(path, key):
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit(f"{key} is missing from {path}")


class Storage:
    def __init__(self, ref, key):
        self.ref = ref
        self.base = f"https://{ref}.supabase.co/storage/v1"
        self.session = requests.Session()
        self.session.headers.update({"apikey": key, "Authorization": f"Bearer {key}"})

    def call(self, method, path, **kwargs):
        response = self.session.request(method, self.base + path, timeout=TIMEOUT, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{self.ref}: {method} {path} -> {response.status_code} {response.text[:200]}")
        return response

    def list_files(self, bucket, prefix=""):
        files, offset = [], 0
        while True:
            page = self.call("POST", f"/object/list/{bucket}", json={
                "prefix": prefix, "limit": PAGE, "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }).json()
            for item in page:
                path = prefix + item["name"]
                if item.get("id") is None:  # a folder, not an object
                    files += self.list_files(bucket, path + "/")
                else:
                    files.append((path, item.get("metadata") or {}))
            if len(page) < PAGE:
                return files
            offset += PAGE

    def public_headers(self, bucket, path):
        url = f"https://{self.ref}.supabase.co/storage/v1/object/public/{bucket}/{quote(path)}"
        response = requests.head(url, timeout=TIMEOUT)
        return {name: response.headers.get(name) for name in COMPARED_HEADERS} | {"status": response.status_code}


def copy_bucket(old, new, bucket, existing):
    bucket_id = bucket["id"]
    config = {key: bucket.get(key) for key in ("public", "file_size_limit", "allowed_mime_types")}
    if bucket_id in existing:
        new.call("PUT", f"/bucket/{bucket_id}", json=config)
    else:
        new.call("POST", "/bucket", json={"id": bucket_id, "name": bucket["name"], **config})

    mismatches = []
    files = old.list_files(bucket_id)
    for path, meta in files:
        body = old.call("GET", f"/object/{bucket_id}/{quote(path)}").content
        # Storage ignores a Cache-Control request header; it reads the form field (seconds).
        seconds = re.search(r"\d+", meta.get("cacheControl") or "")
        new.call(
            "POST", f"/object/{bucket_id}/{quote(path)}",
            headers={"x-upsert": "true"},
            files={"file": (path.rsplit("/", 1)[-1], body, meta.get("mimetype") or "application/octet-stream")},
            data={"cacheControl": seconds.group(0) if seconds else "3600"},
        )
        if bucket.get("public"):
            before, after = old.public_headers(bucket_id, path), new.public_headers(bucket_id, path)
            if before != after:
                mismatches.append(f"  {bucket_id}/{path}: old {before} new {after}")
    print(f"{bucket_id}: {len(files)} objects copied")
    return mismatches


def main(secrets_dir, old_ref, new_ref):
    if old_ref not in env_value(MAIN_ENV, "SUPABASE_URL"):
        raise SystemExit(f"{MAIN_ENV} no longer points at {old_ref}; put the old service key back to re-copy")
    old = Storage(old_ref, env_value(MAIN_ENV, "SUPABASE_SERVICE_ROLE_KEY"))
    new = Storage(new_ref, env_value(Path(secrets_dir) / "supabase-sg.env", "NEW_SERVICE_ROLE_KEY"))

    existing = {bucket["id"] for bucket in new.call("GET", "/bucket").json()}
    mismatches = []
    for bucket in old.call("GET", "/bucket").json():
        mismatches += copy_bucket(old, new, bucket, existing)

    if mismatches:
        print("Served headers differ:\n" + "\n".join(mismatches))
        raise SystemExit(1)
    print("OK: every public object is served with the same size, type and cache header")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: copy_storage.py <secrets_dir> <old_ref> <new_ref>")
    main(*sys.argv[1:])
