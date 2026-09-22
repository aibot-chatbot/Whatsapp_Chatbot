from unittest.mock import patch
from uuid import uuid4
import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def guest():
    with patch("app.routes.tuition_routes._load_widget_or_error", return_value=({"chatbot_id": 7}, {"company_id": 42})), \
         patch("app.routes.tuition_routes.can_use_plan_feature", return_value=True), \
         patch("app.routes.tuition_routes.validate_session_id", return_value="trusted-session"), \
         patch("app.routes.tuition_routes.service.require_trial_context", return_value={}), \
         patch("app.routes.tuition_routes.find_widget_conversation", return_value={"id": 9}), \
         patch("app.routes.tuition_routes.open_conversation", return_value={"id": 9}):
        yield


def test_guest_cannot_submit_company_or_confirmed_true(client, guest):
    with patch("app.routes.tuition_routes.service.confirm_trial") as confirm:
        for field in ({"company_id": 1}, {"confirmed": True}, {"conversation_id": 99}):
            response = client.post("/api/widget/key/tuition", json={"action": "confirm", "session_id_token": "s", "confirmation_token": "token", **field})
            assert response.status_code == 400
        confirm.assert_not_called()


def test_confirm_uses_trusted_session_and_server_token(client, guest):
    with patch("app.routes.tuition_routes.service.confirm_trial", return_value={"booking": {"id": str(uuid4())}}) as confirm:
        response = client.post("/api/widget/key/tuition", json={"action": "confirm", "session_id_token": "s", "confirmation_token": "server-token"})
        assert response.status_code == 200
        confirm.assert_called_once_with(company_id=42, chatbot_id=7, conversation_id=9, confirmation_token="server-token")


def test_guest_list_never_exposes_other_conversations(client, guest):
    with patch("app.routes.tuition_routes.service.list_sessions", return_value=[]) as sessions, \
         patch("app.routes.tuition_routes.service.list_participants", return_value=[]) as participants, \
         patch("app.routes.tuition_routes.service.list_bookings", return_value=[]) as bookings:
        response = client.post("/api/widget/key/tuition", json={"action": "list", "session_id_token": "s"})
        assert response.status_code == 200
        bookings.assert_called_once_with(company_id=42, chatbot_id=7, conversation_id=9)
        assert response.json["data"]["reminders_supported"] is False


def test_guest_handoff_conflict_is_not_success(client, guest):
    from app.services.tuition_service import TuitionError
    with patch("app.routes.tuition_routes.service.confirm_trial", side_effect=TuitionError("Staff is handling this conversation", "tuition_human_controlled", 409)):
        assert client.post("/api/widget/key/tuition", json={"action": "confirm", "session_id_token": "s", "confirmation_token": "token"}).status_code == 409


def test_list_without_existing_conversation_is_read_only(client, guest):
    with patch("app.routes.tuition_routes.find_widget_conversation", return_value=None), \
         patch("app.routes.tuition_routes.open_conversation") as create, \
         patch("app.routes.tuition_routes.service.list_sessions", return_value=[]), \
         patch("app.routes.tuition_routes.service.list_bookings") as bookings:
        response = client.post("/api/widget/key/tuition", json={"action": "list", "session_id_token": "s"})
        assert response.status_code == 200
        assert response.json["data"]["participants"] == response.json["data"]["bookings"] == []
        create.assert_not_called()
        bookings.assert_not_called()


def test_disabled_or_incomplete_trial_never_creates_conversation(client, guest):
    from app.services.tuition_service import TuitionError
    with patch("app.routes.tuition_routes.open_conversation") as create, \
         patch("app.routes.tuition_routes.service.list_sessions", side_effect=TuitionError("Disabled", "tuition_disabled", 503)):
        assert client.post("/api/widget/key/tuition", json={"action": "list", "session_id_token": "s"}).status_code == 503
        assert client.post("/api/widget/key/tuition", json={"action": "participant", "session_id_token": "s"}).status_code == 400
        create.assert_not_called()
