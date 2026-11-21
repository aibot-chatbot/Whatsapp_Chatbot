import os
from time import monotonic

import httpx
from flask import g, has_request_context
from supabase import create_client, Client, ClientOptions
from supabase.lib.client_options import DEFAULT_POSTGREST_CLIENT_TIMEOUT

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")

# Replaying a GET is safe whether or not it reached Supabase; replaying a write
# could credit an order twice, so writes fail fast and the caller decides.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEAD_CONNECTION_RETRIES = 2


class _RetryDeadConnectionTransport(httpx.HTTPTransport):
    """Retry a read whose pooled connection was already closed by the server.

    One client is shared by every Gunicorn request thread, the billing scheduler
    and the Wasender retry loop, so its connections sit idle between requests.
    Supabase closes an idle keep-alive connection from its side and httpx only
    learns of it after handing that dead connection to the next request, which
    then raises RemoteProtocolError. postgrest's own send_with_retry cannot cover
    this: it retries 503/520 *responses*, and a dropped connection never
    produces one. Retrying gets a fresh connection from the pool.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        retries_left = (
            DEAD_CONNECTION_RETRIES if request.method in IDEMPOTENT_METHODS else 0
        )
        while True:
            deadline = getattr(g, "publish_test_request_deadline", None) if has_request_context() else None
            if deadline is not None:
                remaining = min(8, deadline - monotonic())
                if remaining <= 0:
                    raise httpx.TimeoutException("Publish test database deadline expired", request=request)
                request.extensions["timeout"] = dict.fromkeys(("connect", "read", "write", "pool"), remaining)
            try:
                return super().handle_request(request)
            except httpx.RemoteProtocolError:
                if retries_left <= 0:
                    raise
                retries_left -= 1


# Mirrors the client postgrest builds for itself (HTTP/2, redirects, 120s), and
# only adds the retry above. Supabase storage/auth/functions are unused here, so
# this client serves PostgREST alone.
_httpx_client = httpx.Client(
    transport=_RetryDeadConnectionTransport(http2=True),
    follow_redirects=True,
    timeout=DEFAULT_POSTGREST_CLIENT_TIMEOUT,
)

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    options=ClientOptions(httpx_client=_httpx_client),
)
