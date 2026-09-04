import json
from unittest.mock import patch

import pytest

from app.services.langflow_adapter import run_langflow_automation


def test_langflow_adapter_is_disabled_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv("LANGFLOW_AUTOMATION_ENABLED", raising=False)
    monkeypatch.delenv("LANGFLOW_SERVER_URL", raising=False)
    monkeypatch.delenv("LANGFLOW_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="disabled"):
        run_langflow_automation("flow-1", {"event": "document_completed"})


def test_langflow_adapter_rejects_non_https_remote_url(monkeypatch):
    monkeypatch.setenv("LANGFLOW_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "http://langflow.internal")
    monkeypatch.setenv("LANGFLOW_API_KEY", "test-key")

    with pytest.raises(ValueError, match="HTTPS"):
        run_langflow_automation("flow-1", {"event": "document_completed"})


def test_langflow_adapter_sends_bounded_authenticated_request(monkeypatch):
    monkeypatch.setenv("LANGFLOW_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "https://langflow.example.test/")
    monkeypatch.setenv("LANGFLOW_API_KEY", "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return json.dumps({"outputs": [{"result": "ok"}]}).encode()

    captured = {}

    class Opener:
        def open(self, request, **_kwargs):
            captured["request"] = request
            return Response()

    opener = Opener()
    with patch("app.services.langflow_adapter.build_opener", return_value=opener):
        result = run_langflow_automation("flow-1", {"event": "document_completed"})

    assert result["outputs"][0]["result"] == "ok"
    sent = captured["request"]
    assert sent.full_url == "https://langflow.example.test/api/v1/run/flow-1"
    assert sent.get_header("X-api-key") == "test-key"
