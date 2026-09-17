from unittest.mock import Mock

import pytest

from app import create_app
from app.routes import testbot_routes, chat_routes, widget_routes
from app.services import ai_router


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **k: {"user_id": 1})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: {
        "id": 1, "company_id": 42, "role": "admin", "status": "active"})
    monkeypatch.setattr("app.services.company_status_service.ensure_company_operational", lambda _: {"id": 42})
    for module in (testbot_routes, chat_routes):
        monkeypatch.setattr(module, "verify_chatbot_access", lambda _: {"id": 7, "company_id": 42})
        monkeypatch.setattr(module, "get_or_create_conversation", lambda *a, **k: {"id": 100})
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.parametrize("module,path", [(testbot_routes,"/api/testbot/chat?chatbot_id=7"),
                                        (chat_routes,"/api/chat/test?chatbot_id=7")])
def test_test_routes_forward_exact_conversation_for_preflow_pause(client, monkeypatch, module, path):
    generate = Mock(return_value="Hello")
    monkeypatch.setattr(module, "generate_response", generate)
    response = client.post(path, headers={"Authorization": "Bearer synthetic"}, json={"message": "Start flow"})
    assert response.status_code == 200
    assert generate.call_args.kwargs["conversation_id"] == 100


def test_paused_test_lab_never_reaches_flow_or_model(client, monkeypatch):
    monkeypatch.setattr(testbot_routes, "generate_response", ai_router.generate_response)
    monkeypatch.setattr(ai_router, "get_bot_by_id", lambda _: {"id": 7, "company_id": 42})
    monkeypatch.setattr("app.database.conversation_repository.get_conversation_by_id_and_chatbot",
                        lambda *a: {"id": 100, "chatbot_id": 7, "source_channel": "web"})
    monkeypatch.setattr("app.database.agent_action_repository.is_conversation_escalated", lambda *a, **k: True)
    flow = Mock(side_effect=AssertionError("Paused conversation reached Flow"))
    monkeypatch.setattr(ai_router, "_try_process_flow_message", flow)
    response = client.post("/api/testbot/chat?chatbot_id=7", headers={"Authorization": "Bearer synthetic"},
                           json={"message": "Start flow"})
    assert response.status_code == 200
    assert response.json["data"]["reply"] == "This conversation is currently assigned to human staff."
    flow.assert_not_called()


def test_widget_forwards_its_existing_conversation(client, monkeypatch):
    monkeypatch.setattr(widget_routes, "_load_widget_or_error", lambda: ({"chatbot_id": 7}, {}))
    monkeypatch.setattr(widget_routes, "open_conversation", lambda *a: {"id": 100})
    monkeypatch.setattr(widget_routes, "assert_session_quota", lambda *a: 10)
    monkeypatch.setattr(widget_routes, "record_customer_message", Mock())
    record_bot = Mock()
    monkeypatch.setattr(widget_routes, "record_bot_message", record_bot)
    generate = Mock(return_value="<SILENT_BOT_RESPONSE>")
    monkeypatch.setattr(widget_routes, "generate_response", generate)
    response = client.post("/api/widget/synthetic/message", json={"session_id": "web_abcdefghijklmnop", "message": "Hello"})
    assert response.status_code == 200
    assert generate.call_args.kwargs["conversation_id"] == 100
    assert response.json["data"]["handled_by"] == "human"
    record_bot.assert_not_called()
