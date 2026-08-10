"""Characterization tests for the four website-scraping stage endpoints.

These endpoints had no test coverage before the unified ingestion endpoint was
added. They are pinned here so that composing them behind
``POST /api/knowledge/ingest`` provably does not change their behaviour:

    POST /api/knowledge/scrape-analyze  -> knowledge_routes.scrape_analyze_website
    POST /api/knowledge/scrape-batch    -> knowledge_routes.scrape_batch_website
    POST /api/knowledge/scrape-extract  -> knowledge_routes.scrape_extract_website
    POST /api/knowledge/scrape-embed    -> knowledge_routes.scrape_embed_website
"""

from unittest.mock import patch

import pytest

from app import create_app
from app.services.billing_guard import BillingLimitError


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
COMPANY_ID = 28
CHATBOT_ID = 29

CURRENT_USER = {
    "id": 31,
    "company_id": COMPANY_ID,
    "email": "tenant-28@example.test",
    "role": "admin",
    "status": "active",
}


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def authenticated():
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value=CURRENT_USER,
    ), patch(
        "app.routes.knowledge_routes.verify_chatbot_access"
    ), patch(
        "app.routes.knowledge_routes.can_use_plan_feature"
    ), patch(
        "app.routes.knowledge_routes.can_upload_knowledge_file"
    ):
        yield


# ── scrape-analyze ────────────────────────────────────────────────────────


def test_scrape_analyze_returns_discovered_links(client, authenticated):
    # Arrange
    discovered = ["https://example.test", "https://example.test/pricing"]

    # Act
    with patch(
        "app.routes.knowledge_routes.discover_website_links", return_value=discovered
    ) as discover:
        response = client.post(
            f"/api/knowledge/scrape-analyze?chatbot_id={CHATBOT_ID}",
            json={"url": "https://example.test"},
            headers=AUTH_HEADERS,
        )

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"] == {"url": "https://example.test", "links": discovered}
    discover.assert_called_once_with("https://example.test")


def test_scrape_analyze_requires_url(client, authenticated):
    response = client.post(
        f"/api/knowledge/scrape-analyze?chatbot_id={CHATBOT_ID}",
        json={},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_scrape_analyze_requires_chatbot_id(client, authenticated):
    response = client.post(
        "/api/knowledge/scrape-analyze",
        json={"url": "https://example.test"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400


# ── scrape-batch ──────────────────────────────────────────────────────────


def test_scrape_batch_saves_urls_as_supporting_knowledge(client, authenticated):
    with patch(
        "app.routes.knowledge_routes.scrape_website_urls_batch",
        return_value={"file_name": "https://example.test", "message": "saved"},
    ) as batch:
        response = client.post(
            f"/api/knowledge/scrape-batch?chatbot_id={CHATBOT_ID}",
            json={"urls": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["file_name"] == "https://example.test"
    batch.assert_called_once_with(["https://example.test"], CHATBOT_ID)


def test_scrape_batch_rejects_non_list_urls(client, authenticated):
    response = client.post(
        f"/api/knowledge/scrape-batch?chatbot_id={CHATBOT_ID}",
        json={"urls": "https://example.test"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400


def test_scrape_batch_surfaces_billing_limit_as_403_with_code(client, authenticated):
    with patch(
        "app.routes.knowledge_routes.can_use_plan_feature",
        side_effect=BillingLimitError("Upgrade required", code="feature_not_in_plan"),
    ):
        response = client.post(
            f"/api/knowledge/scrape-batch?chatbot_id={CHATBOT_ID}",
            json={"urls": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json()["code"] == "feature_not_in_plan"


# ── scrape-extract ────────────────────────────────────────────────────────


def test_scrape_extract_refines_combined_content(client, authenticated):
    with patch(
        "app.services.knowledge_service.fetch_and_parse_url",
        side_effect=["page one text", "page two text"],
    ), patch(
        "app.routes.knowledge_routes.extract_business_knowledge",
        return_value="REFINED",
    ) as extract:
        response = client.post(
            f"/api/knowledge/scrape-extract?chatbot_id={CHATBOT_ID}",
            json={"urls": ["https://example.test", "https://example.test/pricing"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["extracted_text"] == "REFINED"
    assert data["primary_url"] == "https://example.test"
    assert data["failed_urls"] == []
    extract.assert_called_once_with(
        "page one text\n\npage two text", chatbot_id=CHATBOT_ID
    )


def test_scrape_extract_reports_partially_failed_urls(client, authenticated):
    with patch(
        "app.services.knowledge_service.fetch_and_parse_url",
        side_effect=["page one text", ValueError("boom")],
    ), patch(
        "app.routes.knowledge_routes.extract_business_knowledge",
        return_value="REFINED",
    ):
        response = client.post(
            f"/api/knowledge/scrape-extract?chatbot_id={CHATBOT_ID}",
            json={"urls": ["https://example.test", "https://example.test/bad"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["failed_urls"] == ["https://example.test/bad"]


def test_scrape_extract_returns_400_when_every_url_fails(client, authenticated):
    with patch(
        "app.services.knowledge_service.fetch_and_parse_url",
        side_effect=ValueError("boom"),
    ):
        response = client.post(
            f"/api/knowledge/scrape-extract?chatbot_id={CHATBOT_ID}",
            json={"urls": ["https://example.test/bad"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 400
    assert "Failed to scrape any" in response.get_json()["message"]


def test_scrape_extract_rejects_empty_url_list(client, authenticated):
    response = client.post(
        f"/api/knowledge/scrape-extract?chatbot_id={CHATBOT_ID}",
        json={"urls": []},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400


def test_scrape_extract_checks_file_quota_before_the_billed_llm_call(
    client, authenticated
):
    with patch(
        "app.routes.knowledge_routes.can_upload_knowledge_file",
        side_effect=BillingLimitError("Knowledge file limit reached", code="file_limit"),
    ), patch("app.routes.knowledge_routes.extract_business_knowledge") as extract:
        response = client.post(
            f"/api/knowledge/scrape-extract?chatbot_id={CHATBOT_ID}",
            json={"urls": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json()["code"] == "file_limit"
    extract.assert_not_called()


# ── scrape-embed ──────────────────────────────────────────────────────────


def test_scrape_embed_saves_refined_chunks(client, authenticated):
    with patch(
        "app.routes.knowledge_routes.save_refined_knowledge_chunks",
        return_value={"file_name": "https://example.test", "message": "saved"},
    ) as save:
        response = client.post(
            f"/api/knowledge/scrape-embed?chatbot_id={CHATBOT_ID}",
            json={
                "text_content": "REFINED",
                "primary_url": "https://example.test",
            },
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["data"]["file_name"] == "https://example.test"
    kwargs = save.call_args.kwargs
    assert kwargs["text_content"] == "REFINED"
    assert kwargs["primary_url"] == "https://example.test"
    assert kwargs["chatbot_id"] == CHATBOT_ID


def test_scrape_embed_passes_company_id_so_the_storage_quota_is_enforced(
    client, authenticated
):
    """Regression: the storage quota check inside save_refined_knowledge_chunks
    is guarded by `if company_id:` (knowledge_service.py:673-674). Omitting the
    argument silently skips it."""
    with patch(
        "app.routes.knowledge_routes.save_refined_knowledge_chunks",
        return_value={"file_name": "https://example.test", "message": "saved"},
    ) as save:
        client.post(
            f"/api/knowledge/scrape-embed?chatbot_id={CHATBOT_ID}",
            json={
                "text_content": "REFINED",
                "primary_url": "https://example.test",
            },
            headers=AUTH_HEADERS,
        )

    assert save.call_args.kwargs.get("company_id") == COMPANY_ID


def test_scrape_embed_requires_text_content_and_primary_url(client, authenticated):
    response = client.post(
        f"/api/knowledge/scrape-embed?chatbot_id={CHATBOT_ID}",
        json={"primary_url": "https://example.test"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400


def test_scrape_embed_honours_custom_file_name(client, authenticated):
    with patch(
        "app.routes.knowledge_routes.save_refined_knowledge_chunks",
        return_value={"file_name": "Custom", "message": "saved"},
    ) as save:
        client.post(
            f"/api/knowledge/scrape-embed?chatbot_id={CHATBOT_ID}",
            json={
                "text_content": "REFINED",
                "primary_url": "https://example.test",
                "file_name": "Custom",
            },
            headers=AUTH_HEADERS,
        )

    assert save.call_args.kwargs["file_name"] == "Custom"


# ── shared tenancy / role gates ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "payload"),
    [
        ("/api/knowledge/scrape-analyze", {"url": "https://example.test"}),
        ("/api/knowledge/scrape-batch", {"urls": ["https://example.test"]}),
        ("/api/knowledge/scrape-extract", {"urls": ["https://example.test"]}),
        (
            "/api/knowledge/scrape-embed",
            {"text_content": "x", "primary_url": "https://example.test"},
        ),
    ],
)
def test_scrape_stages_deny_cross_tenant_chatbot_ids(client, url, payload):
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id", return_value=CURRENT_USER
    ), patch(
        "app.routes.knowledge_routes.verify_chatbot_access",
        side_effect=PermissionError("You do not have access to this chatbot."),
    ), patch(
        "app.routes.knowledge_routes.discover_website_links"
    ) as discover, patch(
        "app.routes.knowledge_routes.scrape_website_urls_batch"
    ) as batch, patch(
        "app.routes.knowledge_routes.extract_business_knowledge"
    ) as extract, patch(
        "app.routes.knowledge_routes.save_refined_knowledge_chunks"
    ) as save:
        response = client.post(
            f"{url}?chatbot_id={CHATBOT_ID}", json=payload, headers=AUTH_HEADERS
        )

    assert response.status_code in (403, 500)
    discover.assert_not_called()
    batch.assert_not_called()
    extract.assert_not_called()
    save.assert_not_called()
