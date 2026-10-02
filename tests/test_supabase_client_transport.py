"""test_supabase_client_transport.py

Unit tests for the shared Supabase httpx transport. No network access: the
underlying httpx.HTTPTransport.handle_request is patched.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLASK_DEBUG", "1")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch

import httpx

from app.database.db import (
    DEAD_CONNECTION_RETRIES,
    IDEMPOTENT_METHODS,
    _RetryDeadConnectionTransport,
)

_URL = "https://test.supabase.co/rest/v1/company_subscriptions"


def _request(method):
    return httpx.Request(method, _URL)


class _Attempts:
    """Fail the first `failures` attempts with a dead pooled connection."""

    def __init__(self, failures):
        self.failures = failures
        self.count = 0

    def __call__(self, request, **kwargs):
        self.count += 1
        if self.count <= self.failures:
            raise httpx.RemoteProtocolError("Server disconnected", request=request)
        return httpx.Response(200, json=[], request=request)


class TestRetryDeadConnectionTransport(unittest.TestCase):
    """A server-closed keep-alive connection must not surface as a 500."""

    def _run(self, method, failures):
        attempts = _Attempts(failures)
        transport = _RetryDeadConnectionTransport()
        with patch.object(httpx.HTTPTransport, "handle_request", attempts):
            response = transport.handle_request(_request(method))
        return response, attempts.count

    def test_read_survives_one_dead_connection(self):
        """A GET retries onto a fresh connection instead of raising."""
        response, attempts = self._run("GET", failures=1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempts, 2)

    def test_read_gives_up_after_the_retry_budget(self):
        """A genuinely broken endpoint still raises; the error is never swallowed."""
        attempts = _Attempts(failures=DEAD_CONNECTION_RETRIES + 1)
        transport = _RetryDeadConnectionTransport()
        with patch.object(httpx.HTTPTransport, "handle_request", attempts):
            with self.assertRaises(httpx.RemoteProtocolError):
                transport.handle_request(_request("GET"))

        self.assertEqual(attempts.count, DEAD_CONNECTION_RETRIES + 1)

    def test_writes_are_never_replayed(self):
        """Replaying a POST could credit an order twice, so it must fail fast."""
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            with self.subTest(method=method):
                self.assertNotIn(method, IDEMPOTENT_METHODS)
                attempts = _Attempts(failures=1)
                transport = _RetryDeadConnectionTransport()
                with patch.object(httpx.HTTPTransport, "handle_request", attempts):
                    with self.assertRaises(httpx.RemoteProtocolError):
                        transport.handle_request(_request(method))

                self.assertEqual(attempts.count, 1)

    def test_successful_read_is_sent_once(self):
        """No retry overhead on the happy path."""
        response, attempts = self._run("GET", failures=0)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempts, 1)


class TestSharedClientWiring(unittest.TestCase):
    """The retrying transport must actually be the one Supabase queries through."""

    def test_module_client_uses_the_retrying_transport(self):
        from app.database.db import _httpx_client

        self.assertIsInstance(_httpx_client._transport, _RetryDeadConnectionTransport)

    def test_postgrest_read_survives_a_dead_connection(self):
        """End to end: .execute() returns rows instead of raising RemoteProtocolError."""
        from supabase import create_client, ClientOptions
        from app.database.db import _httpx_client

        client = create_client(
            "https://test.supabase.co",
            "test-service-role-key",
            options=ClientOptions(httpx_client=_httpx_client),
        )
        attempts = _Attempts(failures=1)
        with patch.object(httpx.HTTPTransport, "handle_request", attempts):
            result = client.table("company_subscriptions").select("*").execute()

        self.assertEqual(result.data, [])
        self.assertEqual(attempts.count, 2)


if __name__ == "__main__":
    unittest.main()
