import json
import os
import re
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 128 * 1024
DEFAULT_TIMEOUT_SECONDS = 10
MAX_TIMEOUT_SECONDS = 30


def _enabled():
    return os.getenv("LANGFLOW_AUTOMATION_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _server_url():
    raw = os.getenv("LANGFLOW_SERVER_URL", "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        allow_local_http = os.getenv("LANGFLOW_ALLOW_INSECURE_LOCAL", "false").lower() == "true"
        if not (allow_local_http and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("LANGFLOW_SERVER_URL must use HTTPS")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("LANGFLOW_SERVER_URL must be a valid host URL")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def run_langflow_automation(flow_id, payload):
    """Run one pre-approved Langflow flow through a server-side boundary.

    This adapter is deliberately opt-in. It accepts only JSON objects, keeps
    credentials server-side, enforces HTTPS for remote hosts, and bounds both
    timeout and response size. Tenant authorization and side-effect validation
    remain the caller's responsibility.
    """
    if not _enabled():
        raise RuntimeError("Langflow automation is disabled")
    if not flow_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(flow_id)) or not isinstance(payload, dict):
        raise ValueError("flow_id and object payload are required")

    api_key = os.getenv("LANGFLOW_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Langflow API key is not configured")

    timeout_raw = os.getenv("LANGFLOW_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = min(max(float(timeout_raw), 1), MAX_TIMEOUT_SECONDS)
    except ValueError as exc:
        raise ValueError("LANGFLOW_TIMEOUT_SECONDS must be numeric") from exc

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("Langflow request payload exceeded the safety limit")

    endpoint = f"{_server_url()}/api/v1/run/{quote(str(flow_id), safe='')}"
    request = Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )

    opener = build_opener(NoRedirectHandler)
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Langflow response exceeded the safety limit")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Langflow returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Langflow returned a non-object response")
    return result


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Langflow redirects are not permitted")
