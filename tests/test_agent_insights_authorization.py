"""Focused authorization tests for the AI Signals insights endpoint."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app import create_app


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
DATABASE_USER = {
    "id": 31,
    "company_id": 42,
    "email": "insights-user@example.test",
    "role": "admin",
    "status": "active",
}
RAW_INSIGHTS = {
    "summary": {
        "lead_interest": 2,
        "handoff_request": 1,
        "complaint": 3,
        "knowledge_gap": 4,
    },
    "recent": [
        {
            "intent": "lead_interest",
            "action_type": "create_lead",
            "confidence": 0.91,
            "created_at": "2026-07-24T08:30:00+00:00",
        }
    ],
}
EXPECTED_RESPONSE = {
    "status": "success",
    "data": {
        "summary": {
            "follow_up_opportunities": 2,
            "needs_staff_attention": 1,
            "negative_feedback": 3,
            "missing_answers": 4,
        },
        "recent": [
            {
                "label": "Follow-up opportunity detected",
                "suggested_next_step": "Review for business follow-up",
                "confidence": 0.91,
                "created_at": "2026-07-24T08:30:00+00:00",
            }
        ],
    },
}


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@contextmanager
def authenticated_user(*, database_role, jwt_role=None, database_company_id=42):
    database_user = {
        **DATABASE_USER,
        "company_id": database_company_id,
        "role": database_role,
    }
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={
            "user_id": database_user["id"],
            "company_id": 999,
            "role": jwt_role or database_role,
        },
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value=database_user,
    ):
        yield


def test_owner_can_access_insights_with_existing_response_structure(client):
    with authenticated_user(database_role="owner"), patch(
        "app.routes.analytics_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ) as verify_access, patch(
        "app.routes.analytics_routes.get_agent_insights_by_chatbot",
        return_value=RAW_INSIGHTS,
    ) as get_insights:
        response = client.get(
            "/api/agent/insights?chatbot_id=29",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json() == EXPECTED_RESPONSE
    verify_access.assert_called_once_with(29)
    get_insights.assert_called_once_with(29, limit=10)


def test_admin_can_access_insights(client):
    with authenticated_user(database_role="admin"), patch(
        "app.routes.analytics_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.analytics_routes.get_agent_insights_by_chatbot",
        return_value=RAW_INSIGHTS,
    ):
        response = client.get(
            "/api/agent/insights?chatbot_id=29",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200


def test_member_is_denied_before_chatbot_or_insight_access(client):
    with authenticated_user(database_role="member"), patch(
        "app.routes.analytics_routes.verify_chatbot_access",
    ) as verify_access, patch(
        "app.routes.analytics_routes.get_agent_insights_by_chatbot",
    ) as get_insights:
        response = client.get(
            "/api/agent/insights?chatbot_id=29",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json() == {
        "status": "error",
        "message": "You do not have permission to perform this action.",
    }
    verify_access.assert_not_called()
    get_insights.assert_not_called()


def test_unauthenticated_request_is_denied(client):
    with patch(
        "app.routes.analytics_routes.verify_chatbot_access",
    ) as verify_access, patch(
        "app.routes.analytics_routes.get_agent_insights_by_chatbot",
    ) as get_insights:
        response = client.get("/api/agent/insights?chatbot_id=29")

    assert response.status_code == 401
    verify_access.assert_not_called()
    get_insights.assert_not_called()


def test_cross_tenant_chatbot_is_denied_before_insight_access(client):
    with authenticated_user(database_role="admin"), patch(
        "app.routes.analytics_routes.verify_chatbot_access",
        side_effect=PermissionError("You do not have access to this chatbot."),
    ), patch(
        "app.routes.analytics_routes.get_agent_insights_by_chatbot",
    ) as get_insights:
        response = client.get(
            "/api/agent/insights?chatbot_id=29",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json() == {
        "status": "error",
        "message": "You do not have access to this chatbot.",
    }
    get_insights.assert_not_called()


@pytest.mark.parametrize("jwt_role", ["owner", "admin"])
def test_stale_privileged_jwt_cannot_bypass_current_database_member_role(
    client,
    jwt_role,
):
    with authenticated_user(database_role="member", jwt_role=jwt_role), patch(
        "app.routes.analytics_routes.verify_chatbot_access",
    ) as verify_access, patch(
        "app.routes.analytics_routes.get_agent_insights_by_chatbot",
    ) as get_insights:
        response = client.get(
            "/api/agent/insights?chatbot_id=29",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    verify_access.assert_not_called()
    get_insights.assert_not_called()


def test_stale_member_jwt_does_not_block_current_database_admin(client):
    with authenticated_user(database_role="admin", jwt_role="member"), patch(
        "app.routes.analytics_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.analytics_routes.get_agent_insights_by_chatbot",
        return_value=RAW_INSIGHTS,
    ):
        response = client.get(
            "/api/agent/insights?chatbot_id=29",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json() == EXPECTED_RESPONSE
