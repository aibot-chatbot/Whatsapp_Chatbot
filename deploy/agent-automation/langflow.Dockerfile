# Reviewed minimal profile: no model-provider packages are needed by this bridge.
FROM langflowai/langflow:base-1.12.2@sha256:a946ee3409a4447b0614efc7edbbe5ef0d9c27165487ffcce6b7e25299e1c5a1
COPY --chown=1000:1000 deploy/agent-automation/langflow/components /opt/agent-components
ENV LANGFLOW_COMPONENTS_PATH=/opt/agent-components
# Inline so the literal .dockerignore allowlist (pinned by tests) needs no new entry.
# Fly volumes mount root-owned, and `langflow run` cannot bind "::" (IPv4-only port
# probe; gunicorn splits ":::7860" into an empty port). The worker reaches this app
# over Fly's IPv6 .internal network, so serve uvicorn on a dual-stack "::" socket
# (uvicorn's own "::" listener is IPv6-only because asyncio sets IPV6_V6ONLY).
# A second listener on LANGFLOW_PUBLIC_MCP_PORT is the app's only public surface:
# it serves Langflow's built-in MCP endpoint and 404s everything else, so Claude can
# edit flows without the fly-proxy tunnel (which stalls on uploads over ~8 KB).
# tests/test_langflow_public_mcp_guard.py executes this script's guard.
COPY <<'EOF' /usr/local/bin/langflow-fly-start
import os
import socket

PRIVATE_PORT = int(os.environ.get("LANGFLOW_PORT", "7860"))
# Unset means private-only, as before.
PUBLIC_PORT = int(os.environ.get("LANGFLOW_PUBLIC_MCP_PORT", "0"))
# Exact matches only: a prefix test would admit "..", "//" and encoded variants.
PUBLIC_PATHS = frozenset({"/api/v1/agentic/mcp", "/api/v1/agentic/mcp/"})
LOOPBACK_HOST = f"127.0.0.1:{PRIVATE_PORT}".encode()


def public_mcp_only(app):
    """Serve the full app on the private port and only the MCP endpoint anywhere else."""
    async def guarded(scope, receive, send):
        server = scope.get("server")
        if scope["type"] == "lifespan" or (server and server[1] == PRIVATE_PORT):
            return await app(scope, receive, send)
        if scope["type"] == "http" and scope["path"] in PUBLIC_PATHS:
            # MCP tools call the REST API back at request.base_url. Point that at the
            # private listener so whole-flow writes never leave the machine.
            headers = [(k, v) for k, v in scope["headers"] if k != b"host"]
            headers.append((b"host", LOOPBACK_HOST))
            return await app({**scope, "headers": headers, "scheme": "http"}, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        await send({"type": "http.response.start", "status": 404,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})
    return guarded


def listener(port):
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    return sock


def make_app():
    from langflow.main import setup_app
    return public_mcp_only(setup_app())


if __name__ == "__main__":
    import uvicorn

    UID, GID = 1000, 0  # the image's `user` account (group 0)
    if os.geteuid() == 0:
        config_dir = os.environ["LANGFLOW_CONFIG_DIR"]
        os.makedirs(config_dir, exist_ok=True)
        for root, dirs, files in os.walk(config_dir):  # os.walk never follows symlinks
            for name in dirs + files:
                os.chown(os.path.join(root, name), UID, GID, follow_symlinks=False)
        os.chown(config_dir, UID, GID)
        os.setgroups([])
        os.setgid(GID)
        os.setuid(UID)
    sockets = [listener(PRIVATE_PORT)] + ([listener(PUBLIC_PORT)] if PUBLIC_PORT else [])
    # No access log: Langflow accepts API keys as a query parameter.
    config = uvicorn.Config(make_app, factory=True, host="::", port=PRIVATE_PORT,
                            access_log=False, timeout_graceful_shutdown=50)
    uvicorn.Server(config).run(sockets=sockets)
EOF
USER root
CMD ["python", "/usr/local/bin/langflow-fly-start"]
