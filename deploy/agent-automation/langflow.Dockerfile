# Reviewed minimal profile: no model-provider packages are needed by this bridge.
FROM langflowai/langflow:base-1.12.2@sha256:a946ee3409a4447b0614efc7edbbe5ef0d9c27165487ffcce6b7e25299e1c5a1
COPY --chown=1000:1000 deploy/agent-automation/langflow/components /opt/agent-components
ENV LANGFLOW_COMPONENTS_PATH=/opt/agent-components
