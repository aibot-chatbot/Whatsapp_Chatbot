"""The Langflow container's public listener serves only the built-in MCP endpoint.

The guard lives inline in deploy/agent-automation/langflow.Dockerfile (a heredoc),
so this test executes that exact script text without its __main__ startup.
"""
import asyncio
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parents[1] / "deploy/agent-automation/langflow.Dockerfile"
START = "COPY <<'EOF' /usr/local/bin/langflow-fly-start\n"


@pytest.fixture
def public_mcp_only(monkeypatch):
    monkeypatch.setenv("LANGFLOW_PORT", "7860")
    monkeypatch.setenv("LANGFLOW_PUBLIC_MCP_PORT", "8080")
    text = DOCKERFILE.read_text(encoding="utf-8")
    script = text.split(START, 1)[1].split("\nEOF\n", 1)[0]
    namespace = {"__name__": "langflow_fly_start"}
    exec(compile(script, "langflow-fly-start", "exec"), namespace)
    return namespace["public_mcp_only"]


def call(guard, scope):
    seen, sent = [], []

    async def app(inner_scope, receive, send):
        seen.append(inner_scope)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    asyncio.run(guard(app)(scope, receive, send))
    return seen, sent


def http(path, port, host=b"aibot-agent-langflow-my.fly.dev"):
    return {"type": "http", "path": path, "scheme": "https", "server": ("::", port),
            "headers": [(b"host", host), (b"x-api-key", b"synthetic-key")]}


@pytest.mark.parametrize("path", [
    "/", "/api/v1/flows/", "/api/v1/login", "/health_check", "/api/v1/agentic/mcp/../flows",
    "//api/v1/agentic/mcp", "/api/v1/agentic/mcp/x", "/api/v1/agentic",
])
def test_public_port_404s_everything_but_the_mcp_endpoint(public_mcp_only, path):
    seen, sent = call(public_mcp_only, http(path, 8080))
    assert seen == []
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 404


@pytest.mark.parametrize("path", ["/api/v1/agentic/mcp", "/api/v1/agentic/mcp/"])
def test_public_mcp_request_loops_back_to_the_private_listener(public_mcp_only, path):
    seen, sent = call(public_mcp_only, http(path, 8080))
    assert sent == []
    (scope,) = seen
    assert scope["scheme"] == "http"
    assert [v for k, v in scope["headers"] if k == b"host"] == [b"127.0.0.1:7860"]
    assert (b"x-api-key", b"synthetic-key") in scope["headers"]


def test_public_websocket_is_closed(public_mcp_only):
    scope = {**http("/api/v1/agentic/mcp", 8080), "type": "websocket"}
    seen, sent = call(public_mcp_only, scope)
    assert seen == [] and sent == [{"type": "websocket.close", "code": 1008}]


def test_private_port_keeps_the_full_app(public_mcp_only):
    scope = http("/", 7860, host=b"aibot-agent-langflow-my.internal:7860")
    seen, sent = call(public_mcp_only, scope)
    assert seen == [scope] and sent == []


@pytest.mark.parametrize("server", [None, ("::", 9999)])
def test_unknown_listener_fails_closed(public_mcp_only, server):
    seen, sent = call(public_mcp_only, {**http("/api/v1/flows/", 8080), "server": server})
    assert seen == [] and sent[0]["status"] == 404


def test_lifespan_passes_through(public_mcp_only):
    seen, _ = call(public_mcp_only, {"type": "lifespan"})
    assert seen == [{"type": "lifespan"}]
