# Reviewed minimal profile: no model-provider packages are needed by this bridge.
FROM langflowai/langflow:base-1.12.2@sha256:a946ee3409a4447b0614efc7edbbe5ef0d9c27165487ffcce6b7e25299e1c5a1
COPY --chown=1000:1000 deploy/agent-automation/langflow/components /opt/agent-components
ENV LANGFLOW_COMPONENTS_PATH=/opt/agent-components
# Inline so the literal .dockerignore allowlist (pinned by tests) needs no new entry.
# Fly volumes mount root-owned, and `langflow run` cannot bind "::" (IPv4-only port
# probe; gunicorn splits ":::7860" into an empty port). The worker reaches this app
# over Fly's IPv6 .internal network, so serve uvicorn on a dual-stack "::" socket
# (uvicorn's own "::" listener is IPv6-only because asyncio sets IPV6_V6ONLY).
COPY <<'EOF' /usr/local/bin/langflow-fly-start
import os
import socket

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
port = int(os.environ.get("LANGFLOW_PORT", "7860"))
sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
sock.bind(("::", port))
# No access log: Langflow accepts API keys as a query parameter.
config = uvicorn.Config("langflow.main:setup_app", factory=True, host="::", port=port,
                        access_log=False, timeout_graceful_shutdown=50)
uvicorn.Server(config).run(sockets=[sock])
EOF
USER root
CMD ["python", "/usr/local/bin/langflow-fly-start"]
