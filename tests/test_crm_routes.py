"""Focused regression tests for CRM lead assignment route behavior."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app import create_app
from app.services.billing_guard import BillingLimitError


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
DATABASE_USER = {
    "id": 31,
    "company_id": 42,
    "email": "crm-admin@example.test",
    "role": "admin",
    "status": "active",
}
MOCK_LEAD = {
    "id": 7,
    "chatbot_id": 29,
    "conversation_id": 101,
    "status": "contacted",
    "assigned_to": 9,
}


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@contextmanager
def authenticated_user(*, jwt_company_id=999, database_company_id=42):
    database_user = {**DATABASE_USER, "company_id": database_company_id}
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={
            "user_id": database_user["id"],
            "company_id": jwt_company_id,
            "role": "owner",
        },
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value=database_user,
    ):
        yield


def test_valid_nonempty_assignment_succeeds_without_server_error(client):
    with authenticated_user(), patch(
        "app.routes.crm_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.crm_routes.can_use_plan_feature",
        return_value=True,
    ) as feature_gate, patch(
        "app.routes.crm_routes.update_crm_lead_status_notes",
        return_value=MOCK_LEAD,
    ) as update_lead:
        response = client.patch(
            "/api/crm/leads/7",
            json={"chatbot_id": 29, "assigned_to": 9},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.status_code != 500
    assert response.get_json()["data"]["lead"] == MOCK_LEAD
    feature_gate.assert_called_once_with(42, "crm_lead_assignment")
    update_lead.assert_called_once_with(
        chatbot_id=29,
        lead_id=7,
        status=None,
        notes=None,
        assigned_to=9,
    )


def test_assignment_gate_uses_database_company_not_stale_jwt(client):
    with authenticated_user(jwt_company_id=5, database_company_id=42), patch(
        "app.routes.crm_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.crm_routes.can_use_plan_feature",
        return_value=True,
    ) as feature_gate, patch(
        "app.routes.crm_routes.update_crm_lead_status_notes",
        return_value=MOCK_LEAD,
    ):
        response = client.patch(
            "/api/crm/leads/7",
            json={"chatbot_id": 29, "assigned_to": 9},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    feature_gate.assert_called_once_with(42, "crm_lead_assignment")


def test_clearing_assignment_succeeds_without_feature_gate(client):
    cleared_lead = {**MOCK_LEAD, "assigned_to": None}
    with authenticated_user(), patch(
        "app.routes.crm_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.crm_routes.can_use_plan_feature",
    ) as feature_gate, patch(
        "app.routes.crm_routes.update_crm_lead_status_notes",
        return_value=cleared_lead,
    ) as update_lead:
        response = client.patch(
            "/api/crm/leads/7",
            json={"chatbot_id": 29, "assigned_to": ""},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    feature_gate.assert_not_called()
    assert update_lead.call_args.kwargs["assigned_to"] == ""


def test_assignment_is_rejected_when_feature_is_unavailable(client):
    unavailable = BillingLimitError(
        "CRM lead assignment is not available on your plan.",
        code="feature_not_available",
    )
    with authenticated_user(), patch(
        "app.routes.crm_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.crm_routes.can_use_plan_feature",
        side_effect=unavailable,
    ), patch(
        "app.routes.crm_routes.update_crm_lead_status_notes",
    ) as update_lead:
        response = client.patch(
            "/api/crm/leads/7",
            json={"chatbot_id": 29, "assigned_to": 9},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json() == {
        "status": "error",
        "code": "feature_not_available",
        "message": "CRM lead assignment is not available on your plan.",
    }
    update_lead.assert_not_called()


def test_cross_tenant_assignment_is_rejected_before_update(client):
    with authenticated_user(), patch(
        "app.routes.crm_routes.verify_chatbot_access",
        side_effect=PermissionError("You do not have access to this chatbot."),
    ), patch(
        "app.routes.crm_routes.can_use_plan_feature",
    ) as feature_gate, patch(
        "app.routes.crm_routes.update_crm_lead_status_notes",
    ) as update_lead:
        response = client.patch(
            "/api/crm/leads/7",
            json={"chatbot_id": 29, "assigned_to": 9},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json()["message"] == "You do not have access to this chatbot."
    feature_gate.assert_not_called()
    update_lead.assert_not_called()


def test_status_notes_and_follow_up_update_behavior_is_preserved(client):
    updated_lead = {
        **MOCK_LEAD,
        "status": "in_progress",
        "notes": "Call after 3pm",
        "follow_up_date": "2026-07-30",
    }
    with authenticated_user(), patch(
        "app.routes.crm_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.crm_routes.can_use_plan_feature",
    ) as feature_gate, patch(
        "app.routes.crm_routes.update_crm_lead_status_notes",
        return_value=updated_lead,
    ) as update_lead:
        response = client.patch(
            "/api/crm/leads/7",
            json={
                "chatbot_id": 29,
                "status": "in_progress",
                "notes": "Call after 3pm",
                "follow_up_date": "2026-07-30",
            },
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    feature_gate.assert_not_called()
    update_lead.assert_called_once_with(
        chatbot_id=29,
        lead_id=7,
        status="in_progress",
        notes="Call after 3pm",
        assigned_to=None,
        follow_up_date="2026-07-30",
    )


def test_upsert_nonempty_assignment_uses_authenticated_company_context(client):
    conversation = {
        "id": 101,
        "customer_phone": "+60123456789",
        "customer_name": "Customer",
        "source_channel": "whatsapp",
    }
    with authenticated_user(jwt_company_id=5, database_company_id=42), patch(
        "app.routes.crm_routes.verify_chatbot_access",
        return_value={"id": 29, "company_id": 42},
    ), patch(
        "app.routes.crm_routes.can_use_plan_feature",
        return_value=True,
    ) as feature_gate, patch(
        "app.routes.crm_routes.get_conversation_by_id_and_chatbot",
        return_value=conversation,
    ), patch(
        "app.routes.crm_routes.upsert_crm_lead_by_conversation",
        return_value=MOCK_LEAD,
    ) as upsert_lead:
        response = client.post(
            "/api/crm/leads/upsert",
            json={
                "chatbot_id": 29,
                "conversation_id": 101,
                "assigned_to": 9,
            },
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    feature_gate.assert_called_once_with(42, "crm_lead_assignment")
    upsert_lead.assert_called_once_with(
        company_id=42,
        chatbot_id=29,
        conversation_id=101,
        customer_phone="+60123456789",
        customer_name="Customer",
        source_channel="whatsapp",
        status="new",
        priority="medium",
        assigned_to=9,
        follow_up_date=None,
        notes=None,
    )
