import base64
import hashlib
import json
import re
from pathlib import Path


_POLICY = json.loads(Path(__file__).with_name("csp_policy.json").read_text(encoding="utf-8"))
_HANDLERS = json.loads(Path(__file__).with_name("csp_inline_handlers.json").read_text(encoding="utf-8"))
_HOST_LABEL = r"[A-Za-z0-9]+(?:-+[A-Za-z0-9]+)*"
_HTTPS_DSN = re.compile(
    r"(?i:https)://[A-Za-z0-9._~%+-]+(?::[A-Za-z0-9._~!$&()*+,=:%-]+)?@"
    rf"(?P<authority>{_HOST_LABEL}(?:\.{_HOST_LABEL})*(?::(?P<port>[0-9]{{1,5}}))?)"
    r"(?:/[A-Za-z0-9._~!$&()*+,=:@%-]+)*/[0-9]+/?"
)


def page_csp_header(sentry_dsn):
    policy = _POLICY
    dsn = _HTTPS_DSN.fullmatch(sentry_dsn or "")
    if dsn and (dsn["port"] is None or int(dsn["port"]) <= 65535):
        policy = {**policy, "connect-src": [*policy["connect-src"], f"https://{dsn['authority']}"]}
    return "; ".join(f"{name} {' '.join(sources)}" for name, sources in policy.items())


def page_csp_report_only_header():
    sources = [source for source in _POLICY["script-src"] if source != "'unsafe-inline'"]
    sources.append("'unsafe-hashes'")
    for handler in _HANDLERS:
        digest = hashlib.sha256(handler.encode("utf-8")).digest()
        sources.append(f"'sha256-{base64.b64encode(digest).decode('ascii')}'")
    return "script-src " + " ".join(sources)
