"""No provider, SQL, arbitrary URL or prompt: only a persisted model-step ID."""
import json
import os
from urllib.parse import urlparse
from uuid import UUID

import httpx
from lfx.custom import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.message import Message


class AnalysisModelStep(Component):
    display_name = "Analysis Model Step"
    description = "Execute an authorized, persisted report step through Flask."
    name = "AnalysisModelStep"
    icon = "ShieldCheck"
    inputs = [MessageTextInput(name="input_value", display_name="Run and step IDs", required=True)]
    outputs = [Output(name="message", display_name="Step result", method="step_result")]

    def step_result(self) -> Message:
        if not isinstance(self.input_value, str) or len(self.input_value) > 512:
            raise ValueError("Invalid step input")
        body = json.loads(self.input_value)
        if not isinstance(body, dict) or set(body) != {"run_id", "step_id"}:
            raise ValueError("Only run_id and step_id are allowed")
        body["run_id"] = str(UUID(str(body["run_id"])))
        if body["step_id"] not in {"plan", "analyze"}:
            raise ValueError("Invalid step ID")
        base = os.environ.get("FLASK_AGENT_BASE_URL", "").strip().rstrip("/")
        parsed = urlparse(base)
        token = os.environ.get("AGENT_INTERNAL_TOKEN", "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or len(token) < 32:
            raise ValueError("The authenticated Flask bridge is not configured")
        # No transport retries: durable Flask state decides if a step can be replayed.
        with httpx.Client(timeout=110, follow_redirects=False) as client:
            with client.stream("POST", base + "/internal/agent-model-steps",
                               headers={"Authorization": "Bearer " + token}, json=body) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        raise ValueError("Step response exceeds its limit")
        value = json.loads(content)
        if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
            raise ValueError("Invalid step response")
        return Message(text=json.dumps(value["data"], ensure_ascii=False), sender="Machine", sender_name="Analysis")
