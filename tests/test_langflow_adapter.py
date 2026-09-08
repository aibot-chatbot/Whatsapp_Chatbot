import json
from unittest.mock import patch

import pytest

from app.services.langflow_adapter import (
    MAX_RESPONSE_BYTES,
    langflow_automation_health,
    run_langflow_automation,
)


def _configure_health(monkeypatch):
    monkeypatch.setenv("LANGFLOW_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "https://langflow.example.test/")
    monkeypatch.setenv("LANGFLOW_API_KEY", "test-key")
    monkeypatch.setenv("LANGFLOW_CRM_FLOW_ID", "crm-flow")
    monkeypatch.setenv("LANGFLOW_KNOWLEDGE_FLOW_ID", "knowledge-flow")


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
        status = 200

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


def test_health_reports_disabled_without_opening_http(monkeypatch):
    monkeypatch.delenv("LANGFLOW_AUTOMATION_ENABLED", raising=False)

    with patch("app.services.langflow_adapter.build_opener") as build_opener:
        result = langflow_automation_health()

    assert result == {"status": "disabled"}
    build_opener.assert_not_called()


def test_health_requires_both_valid_flow_ids(monkeypatch):
    _configure_health(monkeypatch)
    monkeypatch.delenv("LANGFLOW_KNOWLEDGE_FLOW_ID")

    with patch("app.services.langflow_adapter.build_opener") as build_opener:
        result = langflow_automation_health()

    assert result == {"status": "not_configured"}
    build_opener.assert_not_called()


def test_health_reports_unavailable_when_its_mocked_transport_fails(monkeypatch):
    _configure_health(monkeypatch)

    with patch(
        "app.services.langflow_adapter.build_opener",
        side_effect=RuntimeError("connection refused"),
    ):
        result = langflow_automation_health()

    assert result == {"status": "unavailable"}


def test_health_uses_a_keyless_bounded_health_check(monkeypatch):
    _configure_health(monkeypatch)
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, limit):
            captured["limit"] = limit
            return b'{"status":"ok","chat":"ok","db":"ok"}'

    class Opener:
        def open(self, request, **kwargs):
            captured["request"] = request
            captured["timeout"] = kwargs["timeout"]
            return Response()

    with patch("app.services.langflow_adapter.build_opener", return_value=Opener()):
        result = langflow_automation_health()

    assert result == {"status": "ok"}
    assert captured["request"].full_url == "https://langflow.example.test/health_check"
    assert captured["request"].get_header("X-api-key") is None
    assert captured["timeout"] == 2
    assert captured["limit"] == 1025


@pytest.mark.parametrize("status, body", [
    (200, b'{"status":"ok","chat":"ok","db":"error"}'),
    (200, b'not-json'),
    (200, b'x' * 1025),
    (202, b'{"status":"ok","chat":"ok","db":"ok"}'),
])
def test_health_rejects_incomplete_or_invalid_runtime_health(monkeypatch, status, body):
    _configure_health(monkeypatch)
    with patch("app.services.langflow_adapter.build_opener") as opener:
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = status
        response.read.return_value = body
        assert langflow_automation_health() == {"status": "unavailable"}


def test_local_http_opt_in_does_not_allow_other_url_schemes(monkeypatch):
    _configure_health(monkeypatch)
    monkeypatch.setenv("LANGFLOW_ALLOW_INSECURE_LOCAL", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "ftp://localhost")
    with patch("app.services.langflow_adapter.build_opener") as opener:
        assert langflow_automation_health() == {"status": "not_configured"}
        opener.assert_not_called()


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_langflow_adapter_rejects_nonfinite_timeout(monkeypatch, timeout):
    monkeypatch.setenv("LANGFLOW_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "https://langflow.example.test")
    monkeypatch.setenv("LANGFLOW_API_KEY", "test-key")
    monkeypatch.setenv("LANGFLOW_TIMEOUT_SECONDS", timeout)

    with pytest.raises(ValueError, match="finite"):
        run_langflow_automation("flow-1", {"event": "document_completed"})


def test_langflow_adapter_rejects_an_accepted_async_job(monkeypatch):
    monkeypatch.setenv("LANGFLOW_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "https://langflow.example.test")
    monkeypatch.setenv("LANGFLOW_API_KEY", "test-key")

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b'{"accepted":true}'

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    with patch("app.services.langflow_adapter.build_opener", return_value=Opener()):
        with pytest.raises(RuntimeError, match="completed synchronous"):
            run_langflow_automation("flow-1", {"event": "document_completed"})


def test_langflow_adapter_rejects_oversized_response(monkeypatch):
    monkeypatch.setenv("LANGFLOW_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "https://langflow.example.test")
    monkeypatch.setenv("LANGFLOW_API_KEY", "test-key")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b"x" * (MAX_RESPONSE_BYTES + 1)

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    with patch("app.services.langflow_adapter.build_opener", return_value=Opener()):
        with pytest.raises(RuntimeError, match="safety limit"):
            run_langflow_automation("flow-1", {"event": "document_completed"})


def test_langflow_adapter_rejects_invalid_json(monkeypatch):
    monkeypatch.setenv("LANGFLOW_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("LANGFLOW_SERVER_URL", "https://langflow.example.test")
    monkeypatch.setenv("LANGFLOW_API_KEY", "test-key")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b"not-json"

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    with patch("app.services.langflow_adapter.build_opener", return_value=Opener()):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            run_langflow_automation("flow-1", {"event": "document_completed"})
