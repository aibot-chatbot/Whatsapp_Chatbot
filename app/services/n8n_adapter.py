"""Configuration and health for the out-of-process n8n automation worker.

n8n never decides anything. It drains the ``automation_events`` outbox that
Flask has already written and reports each event back as completed or failed,
so an n8n outage delays queued work but can never affect a user-facing action.
That is the opposite half of the Langflow layer, which answers synchronously
inside a request and is advisory only.

Work flows n8n -> Flask, so n8n presents a worker token on the way in and this
process holds no n8n credentials. The health probe below is the only outbound
call, and it proves the instance answers - not that a workflow is polling.
"""

import json
import os
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_LEASE_SECONDS = 300
MIN_LEASE_SECONDS = 30
MAX_LEASE_SECONDS = 3600
HEALTH_TIMEOUT_SECONDS = 2
MAX_HEALTH_BYTES = 1024


def n8n_worker_enabled():
    return os.getenv("N8N_WORKER_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def worker_lease_seconds():
    """How long a claimed event may stay ``running`` before it is re-offered.

    A worker that dies mid-event would otherwise strand its row at ``running``
    forever, so the lease is what makes the outbox self-healing without a
    separate reaper job.
    """
    raw = os.getenv("N8N_WORKER_LEASE_SECONDS", str(DEFAULT_LEASE_SECONDS))
    try:
        lease = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_LEASE_SECONDS
    return min(max(lease, MIN_LEASE_SECONDS), MAX_LEASE_SECONDS)


def _base_url():
    raw = os.getenv("N8N_BASE_URL", "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        allow_local_http = os.getenv("N8N_ALLOW_INSECURE_LOCAL", "false").lower() == "true"
        if not (parsed.scheme == "http" and allow_local_http and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("N8N_BASE_URL must use HTTPS")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("N8N_BASE_URL must be a valid host URL")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def n8n_automation_health():
    """Report whether the n8n instance answers, without running any workflow."""
    if not n8n_worker_enabled():
        return {"status": "disabled"}
    try:
        base_url = _base_url()
    except ValueError:
        return {"status": "not_configured"}
    if not os.getenv("N8N_WORKER_TOKEN", "").strip():
        return {"status": "not_configured"}

    try:
        request = Request(f"{base_url}/healthz", headers={"Accept": "application/json"})
        with build_opener(NoRedirectHandler).open(request, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return {"status": "unavailable"}
            raw = response.read(MAX_HEALTH_BYTES + 1)
        if len(raw) > MAX_HEALTH_BYTES:
            return {"status": "unavailable"}
        result = json.loads(raw.decode("utf-8"))
        return {"status": "ok" if isinstance(result, dict) and result.get("status") == "ok" else "unavailable"}
    except Exception:
        return {"status": "unavailable"}


# Deliberately a copy of the Langflow adapter's guard rather than a shared
# import: the two integrations stay independently deletable, and this file
# should not pull in the advisory layer just to probe a health endpoint.
class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("n8n redirects are not permitted")
