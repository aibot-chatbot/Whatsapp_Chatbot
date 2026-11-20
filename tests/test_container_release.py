"""Keep private local files and request metadata out of the container release."""

import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_container_context_is_an_explicit_tracked_runtime_file_manifest():
    raw = (ROOT / ".dockerignore").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "Write .dockerignore as UTF-8 without a BOM"
    rules = [line for line in raw.decode("utf-8").splitlines() if line and not line.startswith("#")]
    assert rules[0] == "**", "The build context must start by excluding everything"

    # This deliberately supports only literal exceptions, not a second Dockerignore engine.
    # Docker traverses excluded parents when a negated descendant path is present.
    included = []
    for rule in rules[1:]:
        assert re.fullmatch(r"![A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", rule), rule
        path = rule[1:]
        assert all(part not in {".", ".."} for part in path.split("/")), path
        included.append(path)
    assert included == sorted(set(included)), "Keep literal exceptions unique and sorted"

    index = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z"], cwd=ROOT
    ).decode("utf-8")
    tracked = {}
    for entry in filter(None, index.split("\0")):
        metadata, path = entry.split("\t", 1)
        mode, _, stage = metadata.split()
        tracked[path] = (mode, stage)

    required = {
        ".dockerignore", "Dockerfile", "requirements.txt", "wsgi.py",
        "langflow/crm-stage-automation.json",
        "langflow/knowledge-document-follow-up.json",
        "analysis_worker.py",
        "deploy/agent-automation/langflow.Dockerfile",
        "deploy/agent-automation/worker.Dockerfile",
        "deploy/agent-automation/langflow/components/agent_analysis/__init__.py",
        "deploy/agent-automation/langflow/components/agent_analysis/model_step.py",
        # The Dockerfile's Node stage copies these by name before `npm ci && npm run build`.
        "web/package.json", "web/package-lock.json", "web/astro.config.mjs",
        # app/csp_policy.py reads both files at import.
        "app/csp_inline_handlers.json", "app/csp_policy.json",
    }
    assert required <= tracked.keys(), "Required container inputs must be tracked"
    # .svg ships too: every page links favicon.svg, and it 404'd in production when excluded.
    served_suffixes = {".html", ".css", ".js", ".svg"}
    expected = required | {
        path for path in tracked
        if (path.startswith("app/") and PurePosixPath(path).suffix == ".py")
        # frontend/ and web/public/ are served as-is, so both keep the same file-type guard.
        or (path.startswith(("frontend/", "web/public/")) and PurePosixPath(path).suffix in served_suffixes)
        # Astro build inputs only; web/node_modules and web/dist are produced inside the image.
        or path == "web/tsconfig.json" or path.startswith("web/src/")
    }
    assert set(included) == expected
    for path in included:
        assert tracked[path] in {("100644", "0"), ("100755", "0")}, path
        local = ROOT / path
        assert stat.S_ISREG(local.lstat().st_mode), path
        assert not any((ROOT / parent).is_symlink() for parent in PurePosixPath(path).parents), path

    # Literal-only exceptions make exact membership sufficient: no wildcard can
    # admit these local artifacts, including files with otherwise allowed suffixes.
    private_paths = {
        "frontend/bash.exe.stackdump", "frontend/customer-export.sqlite",
        "frontend/assets/private-key.pem", "frontend/login.html.bak",
        "frontend/customer-document.pdf", "frontend/credentials-note.txt",
        "app/.env", "app/customer-backup.db", "app/private-credentials.py",
        "frontend/assets/js/private-credentials.js", "frontend/private-notes.html",
        "web/node_modules/astro/package.json", "web/dist/landing.html", "web/.env",
        "web/public/customer-document.pdf", "web/public/assets/customer-export.csv",
    }
    assert private_paths.isdisjoint(included)


def test_container_access_log_omits_request_credentials_and_customer_metadata():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    command = json.loads(next(line[4:] for line in dockerfile.splitlines() if line.startswith("CMD ")))
    args = shlex.split(command[-1])
    log_format = args[args.index("--access-logformat") + 1]
    private = "synthetic-webhook-secret"
    # Gunicorn renders its access format using Python's mapping interpolation.
    rendered = log_format % {
        "m": "POST", "s": "200", "L": "0.123",
        "r": f"POST /wasender/webhook/{private}?token={private} HTTP/1.1",
        "U": f"/wasender/webhook/{private}", "q": f"token={private}",
        "f": f"https://example.test/{private}", "h": "192.0.2.42",
        "a": "synthetic-private-user-agent",
    }
    assert private not in rendered
    assert "192.0.2.42" not in rendered
    assert "synthetic-private-user-agent" not in rendered
    assert "POST" in rendered and "200" in rendered and "0.123" in rendered
