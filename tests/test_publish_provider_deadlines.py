"""Publish tests bound the normal billed provider transports without changing live calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, g

from app.services import ai_gateway, ai_router, cloudflare_service, deepseek_service, openrouter_service, rag_service


@pytest.fixture
def publish_request():
    with Flask(__name__).test_request_context():
        g.publish_test = True
        yield


def test_later_attempts_share_remaining_request_time(publish_request, monkeypatch):
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(ai_gateway, "monotonic", clock, raising=False)
    assert 0 < ai_gateway.publish_test_timeout() <= 20
    clock.return_value = 138.0
    assert ai_gateway.publish_test_timeout() == 2
    clock.return_value = 141.0
    with pytest.raises(TimeoutError):
        ai_gateway.publish_test_timeout()


@pytest.mark.parametrize("publish", [True, False])
def test_deepseek_scenario_and_answer_calls_scope_sdk_retries(publish, monkeypatch):
    app = Flask(__name__)
    client = Mock()
    limited = client.with_options.return_value
    raw = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))], usage=None)
    for target in (client, limited):
        target.chat.completions.create.return_value = raw
    monkeypatch.setattr("openai.OpenAI", Mock(return_value=client))
    monkeypatch.setattr(deepseek_service, "client", client)
    monkeypatch.setattr(ai_gateway, "deepseek_base_url", lambda: ai_gateway.DEEPSEEK_DIRECT_BASE_URL)
    monkeypatch.setattr(deepseek_service, "prepare_chat_prompt", lambda **kw: {"prompt": "synthetic"})
    with app.test_request_context():
        g.publish_test = publish
        for invoke in (lambda: ai_router._call_deepseek_direct("question", "deepseek-v4-flash", 0.2),
                       lambda: deepseek_service._request("question", "synthetic", 4)):
            client.reset_mock()
            invoke()
            if publish:
                opts = client.with_options.call_args.kwargs
                assert opts["max_retries"] == 0
                assert 0 < opts["timeout"] <= 20
                limited.chat.completions.create.assert_called_once()
            else:
                client.with_options.assert_not_called()
                client.chat.completions.create.assert_called_once()


@pytest.mark.parametrize("provider", ["cloudflare", "openrouter"])
def test_scenario_http_calls_leave_time_for_grading_and_storage(provider, publish_request, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "0" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "synthetic")
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "synthetic"}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(openrouter_service.requests, "post", post)
    monkeypatch.setattr(openrouter_service.openrouter_key_service, "key_for_company", lambda *args: "synthetic")
    monkeypatch.setattr(cloudflare_service, "extract_usage", Mock())
    if provider == "openrouter":
        openrouter_service.post_chat_completion({}, api_key="synthetic", timeout=90)
    else:
        cloudflare_service.request("question", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    connect, read = post.call_args.kwargs["timeout"]
    assert 0 < connect <= 3
    assert 0 < read <= 20


def test_retrieval_embedding_is_bounded_only_for_publish(publish_request, monkeypatch):
    embed = Mock(return_value=SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0])]))
    monkeypatch.setattr(rag_service.client.models, "embed_content", embed)
    assert rag_service.generate_embedding("synthetic") == [1.0]
    options = embed.call_args.kwargs["config"]["http_options"]
    assert 0 < options["timeout"] <= 8000
    assert options["retry_options"]["attempts"] == 1
    g.publish_test = False
    assert rag_service.generate_embedding("synthetic") == [1.0]
    assert "http_options" not in embed.call_args.kwargs["config"]


def test_publish_database_timeout_is_request_local_and_reserves_grading_time(monkeypatch):
    import httpx
    from time import monotonic
    from app.database.db import _RetryDeadConnectionTransport

    seen = []
    def capture(_transport, request):
        seen.append(request.extensions.get("timeout"))
        return httpx.Response(200)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", capture)
    transport = _RetryDeadConnectionTransport()
    with Flask(__name__).test_request_context():
        g.publish_test_request_deadline = monotonic() + 2
        transport.handle_request(httpx.Request("GET", "https://example.test"))
    transport.handle_request(httpx.Request("GET", "https://example.test"))
    assert all(0 < v <= 2 for v in seen[0].values())
    assert seen[1] is None

