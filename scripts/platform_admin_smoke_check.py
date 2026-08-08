"""Read-only platform-admin smoke verification for local or approved staging use.

Usage::

    set PLATFORM_ADMIN_TOKEN=<redacted>
    python scripts/platform_admin_smoke_check.py --base-url http://127.0.0.1:5000
    python scripts/platform_admin_smoke_check.py --base-url http://127.0.0.1:5000 --company-id 42

The bearer token is read only from ``PLATFORM_ADMIN_TOKEN``. The script makes
GET requests only, never prints response bodies or credentials, and does not
perform production access or data mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse


BASE_URL_ENV = "PLATFORM_ADMIN_BASE_URL"
TOKEN_ENV = "PLATFORM_ADMIN_TOKEN"
COMPANY_ID_ENV = "PLATFORM_ADMIN_COMPANY_ID"
TIMEOUT_ENV = "PLATFORM_ADMIN_SMOKE_TIMEOUT"
DEFAULT_TIMEOUT = 10.0
FORBIDDEN_BILLING_PATTERNS = (
    "payment_reference",
    "gateway_order_id",
    "checkout_url",
    "idempotency_key",
    "payment_gateway",
    "order_reference",
)
FORBIDDEN_BILLING_CURRENCY = re.compile(r"\b(?:RM|MYR)\b", re.IGNORECASE)


class SmokeConfigurationError(ValueError):
    """A required smoke-check configuration value is missing or invalid."""


@dataclass(frozen=True)
class CheckResult:
    path: str
    passed: bool
    detail: str


class _HttpResponse:
    """Small response adapter keeping the script's test seam dependency-free."""

    def __init__(self, raw_response: object, request: urllib_request.Request):
        self.status_code = int(raw_response.status)
        self.request = request
        self._body = raw_response.read()

    def json(self) -> object:
        return json.loads(self._body.decode("utf-8"))


def _http_get(
    url: str, *, headers: Mapping[str, str], timeout: float, method: str = "GET"
) -> _HttpResponse:
    if method != "GET":
        raise ValueError("smoke checker only permits GET requests")
    request = urllib_request.Request(url, headers=dict(headers), method=method)
    with urllib_request.urlopen(request, timeout=timeout) as response:
        return _HttpResponse(response, request)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help=f"App base URL; defaults to {BASE_URL_ENV}.")
    parser.add_argument("--company-id", help=f"Optional company ID; defaults to {COMPANY_ID_ENV}.")
    parser.add_argument("--timeout", type=float, help=f"Request timeout in seconds; defaults to {TIMEOUT_ENV} or {DEFAULT_TIMEOUT}.")
    return parser


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _build_parser()
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        # Do not echo unknown values: a user must never see a token echoed by
        # argument parsing if they accidentally supplied one on the CLI.
        raise SmokeConfigurationError("unsupported command-line option")
    return args


def _required_env(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SmokeConfigurationError(f"{name} is required")
    return value


def _base_url(cli_value: str | None, environ: Mapping[str, str]) -> str:
    value = (cli_value or environ.get(BASE_URL_ENV, "")).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SmokeConfigurationError("base URL must use http or https")
    return value


def _positive_company_id(cli_value: str | None, environ: Mapping[str, str]) -> int | None:
    value = (cli_value or environ.get(COMPANY_ID_ENV, "")).strip()
    if not value:
        return None
    try:
        company_id = int(value)
    except ValueError as exc:
        raise SmokeConfigurationError("company ID must be a positive integer") from exc
    if company_id <= 0:
        raise SmokeConfigurationError("company ID must be a positive integer")
    return company_id


def _timeout(cli_value: float | None, environ: Mapping[str, str]) -> float:
    raw = cli_value if cli_value is not None else environ.get(TIMEOUT_ENV, "")
    if raw in ("", None):
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise SmokeConfigurationError("timeout must be a positive number") from exc
    if value <= 0:
        raise SmokeConfigurationError("timeout must be a positive number")
    return value


def _response_data(response: object) -> object:
    if getattr(response, "request", None) is not None and response.request.method != "GET":
        raise RuntimeError("request method was not GET")
    if getattr(response, "status_code", None) != 200:
        raise RuntimeError(f"unexpected HTTP status {getattr(response, 'status_code', 'unknown')}")
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise RuntimeError("response was not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success" or "data" not in payload:
        raise RuntimeError("response did not contain the expected success envelope")
    return payload["data"]


def _billing_response_is_safe(data: object) -> bool:
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
    lowered = serialized.lower()
    if any(pattern in lowered for pattern in FORBIDDEN_BILLING_PATTERNS):
        return False
    return FORBIDDEN_BILLING_CURRENCY.search(serialized) is None


def _paths(company_id: int | None) -> Iterable[tuple[str, bool]]:
    yield "/api/platform-admin/me", False
    yield "/api/platform-admin/overview", False
    yield "/api/platform-admin/audit-events", False
    yield "/api/platform-admin/companies", False
    if company_id is None:
        return
    prefix = f"/api/platform-admin/companies/{company_id}"
    for suffix in (
        "",
        "/subscription",
        "/subscription-history",
        "/ai-credit-usage",
        "/ai-credit-transactions",
        "/billing-orders",
        "/users",
        "/chatbots",
    ):
        yield prefix + suffix, suffix == "/billing-orders"


def _run_with_overview_check(
    base_url: str,
    token: str,
    company_id: int | None,
    timeout: float,
    http_get: Callable[..., object],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for path, billing_orders in _paths(company_id):
        try:
            response = http_get(
                base_url + path,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=timeout,
                method="GET",
            )
            data = _response_data(response)
            if path.endswith("/overview") and (
                not isinstance(data, dict) or "operational_alerts" not in data
            ):
                raise RuntimeError("overview did not contain operational_alerts")
            if billing_orders and not _billing_response_is_safe(data):
                raise RuntimeError("billing response contained a forbidden field or currency marker")
            results.append(CheckResult(path, True, f"HTTP {response.status_code}"))
        except (OSError, urllib_error.URLError, TimeoutError):
            results.append(CheckResult(path, False, "request failed"))
        except (RuntimeError, TypeError, ValueError) as exc:
            results.append(CheckResult(path, False, str(exc)))
    return results


def _print_results(results: Sequence[CheckResult], company_id: int | None) -> None:
    print("RESULT | METHOD | PATH | DETAIL")
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'} | GET | {result.path} | {result.detail}")
    if company_id is None:
        print("SKIP | GET | company detail child endpoints | company ID not provided")


def main(argv: Sequence[str] | None = None) -> int:
    environ = os.environ
    try:
        args = _parse_args(argv)
        base_url = _base_url(args.base_url, environ)
        token = _required_env(TOKEN_ENV, environ)
        company_id = _positive_company_id(args.company_id, environ)
        timeout = _timeout(args.timeout, environ)
        results = _run_with_overview_check(base_url, token, company_id, timeout, _http_get)
    except SmokeConfigurationError as exc:
        print(f"FAIL | configuration | {exc}")
        return 2

    _print_results(results, company_id)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
