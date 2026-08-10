"""Tests for the unified knowledge ingestion endpoint.

``POST /api/knowledge/ingest?chatbot_id=`` runs the four website-scraping
stages that are otherwise exposed as four separate HTTP calls
(``scrape-analyze`` -> ``scrape-batch`` -> ``scrape-extract`` -> ``scrape-embed``)
inside a single request, and reports per-stage progress for every source.

Scope note: this endpoint covers **website sources only**. Uploaded documents
go through ``POST /upload-pdf`` (app/views.py:98), a different code path with a
different request encoding and no per-stage seams.
"""

from unittest.mock import patch

import pytest

from app import create_app
from app.services.billing_guard import BillingLimitError


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
COMPANY_ID = 28
CHATBOT_ID = 29
INGEST_URL = f"/api/knowledge/ingest?chatbot_id={CHATBOT_ID}"

CURRENT_USER = {
    "id": 31,
    "company_id": COMPANY_ID,
    "email": "tenant-28@example.test",
    "role": "admin",
    "status": "active",
}

# The ingestion service calls the stage functions through the knowledge_service
# module, so every stage is patched in that one namespace.
SERVICE = "app.services.knowledge_service"


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def authenticated():
    """Authenticated admin whose tenancy and billing gates all pass."""
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id", return_value=CURRENT_USER
    ), patch(
        "app.routes.knowledge_routes.verify_chatbot_access"
    ), patch(
        "app.routes.knowledge_routes.can_use_plan_feature"
    ), patch(
        "app.routes.knowledge_routes.can_upload_knowledge_file"
    ):
        yield


def stage_map(source: dict) -> dict:
    """{stage_name: stage_status} for one source entry of the response."""
    return {stage["name"]: stage["status"] for stage in source["stages"]}


# ── 1. Happy path: one call completes ingestion end to end ────────────────


def test_single_call_runs_all_four_stages_and_ingests(client, authenticated):
    # Arrange
    with patch(
        f"{SERVICE}.discover_website_links",
        return_value=["https://example.test", "https://example.test/pricing"],
    ) as discover, patch(
        f"{SERVICE}.fetch_and_parse_url",
        side_effect=["page one text", "page two text"],
    ) as fetch, patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ) as extract, patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "https://example.test (+1 pages)", "message": "ok"},
    ) as save:
        # Act
        response = client.post(
            INGEST_URL,
            json={"sources": [{"url": "https://example.test", "discover_links": True}]},
            headers=AUTH_HEADERS,
        )

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["status"] == "succeeded"
    assert data["chatbot_id"] == CHATBOT_ID
    assert data["totals"] == {
        "requested": 1,
        "succeeded": 1,
        "partial": 0,
        "failed": 0,
    }

    # All four stages ran, in one HTTP call.
    discover.assert_called_once_with("https://example.test")
    assert fetch.call_count == 2
    extract.assert_called_once()
    save.assert_called_once()

    source = data["sources"][0]
    assert source["status"] == "succeeded"
    assert source["phase"] == "done"
    assert source["file_name"] == "https://example.test (+1 pages)"
    assert source["error_code"] is None


def test_source_accepts_a_bare_url_string(client, authenticated):
    with patch(f"{SERVICE}.discover_website_links") as discover, patch(
        f"{SERVICE}.fetch_and_parse_url", return_value="body text"
    ), patch(f"{SERVICE}.extract_business_knowledge", return_value="REFINED"), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "https://example.test", "message": "ok"},
    ):
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "succeeded"
    # Link discovery is opt-in, so a bare URL must not crawl the whole site.
    discover.assert_not_called()


def test_caller_supplied_urls_skip_the_analyze_stage(client, authenticated):
    with patch(f"{SERVICE}.discover_website_links") as discover, patch(
        f"{SERVICE}.fetch_and_parse_url", side_effect=["a", "b"]
    ), patch(f"{SERVICE}.extract_business_knowledge", return_value="REFINED"), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ):
        response = client.post(
            INGEST_URL,
            json={
                "sources": [
                    {
                        "url": "https://example.test",
                        "urls": [
                            "https://example.test/a",
                            "https://example.test/b",
                        ],
                    }
                ]
            },
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    discover.assert_not_called()
    source = response.get_json()["data"]["sources"][0]
    assert stage_map(source)["analyze"] == "skipped"
    assert source["status"] == "succeeded"


# ── 2. Per-stage progress ─────────────────────────────────────────────────


def test_response_reports_every_stage_in_pipeline_order(client, authenticated):
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="body text"), patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "https://example.test", "message": "ok"},
    ):
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    source = response.get_json()["data"]["sources"][0]
    assert [stage["name"] for stage in source["stages"]] == [
        "analyze",
        "scrape",
        "extract",
        "embed",
    ]
    assert stage_map(source) == {
        "analyze": "skipped",
        "scrape": "succeeded",
        "extract": "succeeded",
        "embed": "succeeded",
    }


def test_stage_progress_shows_exactly_where_a_source_stopped(client, authenticated):
    """A source that dies during extract must not be reported as embedded."""
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="body text"), patch(
        f"{SERVICE}.extract_business_knowledge",
        side_effect=RuntimeError("llm exploded"),
    ), patch(f"{SERVICE}.save_refined_knowledge_chunks") as save:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    source = response.get_json()["data"]["sources"][0]
    assert source["phase"] == "extract"
    assert source["status"] == "failed"
    assert stage_map(source) == {
        "analyze": "skipped",
        "scrape": "succeeded",
        "extract": "failed",
        "embed": "skipped",
    }
    assert source["error_code"] == "extract_failed"
    assert "llm exploded" in source["error_message"]
    save.assert_not_called()


def test_scrape_stage_detail_names_the_pages_that_failed(client, authenticated):
    with patch(
        f"{SERVICE}.fetch_and_parse_url",
        side_effect=["good page", ValueError("404 not found")],
    ), patch(f"{SERVICE}.extract_business_knowledge", return_value="REFINED"), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ):
        response = client.post(
            INGEST_URL,
            json={
                "sources": [
                    {
                        "url": "https://example.test",
                        "urls": [
                            "https://example.test/ok",
                            "https://example.test/bad",
                        ],
                    }
                ]
            },
            headers=AUTH_HEADERS,
        )

    source = response.get_json()["data"]["sources"][0]
    scrape = next(s for s in source["stages"] if s["name"] == "scrape")
    assert scrape["status"] == "partial"
    assert scrape["detail"]["scraped_pages"] == 1
    failed = scrape["detail"]["failed_pages"]
    assert [f["url"] for f in failed] == ["https://example.test/bad"]
    assert "404 not found" in failed[0]["error"]
    # One bad page does not lose the good page.
    assert source["status"] == "partial"
    assert stage_map(source)["embed"] == "succeeded"


# ── 3. Partial success across sources ─────────────────────────────────────


def test_a_failing_source_does_not_roll_back_a_successful_one(client, authenticated):
    def fetch(url: str) -> str:
        if "bad" in url:
            raise ValueError("connection refused")
        return "good page text"

    with patch(f"{SERVICE}.fetch_and_parse_url", side_effect=fetch), patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "https://good.test", "message": "ok"},
    ) as save:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://good.test", "https://bad.test"]},
            headers=AUTH_HEADERS,
        )

    # Partial success is still a processed request, not an error.
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["status"] == "partial"
    assert data["totals"] == {
        "requested": 2,
        "succeeded": 1,
        "partial": 0,
        "failed": 1,
    }

    # The good source really was ingested.
    save.assert_called_once()

    good, bad = data["sources"]
    assert good["url"] == "https://good.test"
    assert good["status"] == "succeeded"
    assert good["file_name"] == "https://good.test"

    assert bad["url"] == "https://bad.test"
    assert bad["status"] == "failed"
    assert bad["phase"] == "scrape"
    assert bad["error_code"] == "scrape_failed"
    assert "connection refused" in bad["error_message"]


def test_all_sources_failing_returns_400_with_per_source_reasons(
    client, authenticated
):
    with patch(
        f"{SERVICE}.fetch_and_parse_url", side_effect=ValueError("dns failure")
    ), patch(f"{SERVICE}.save_refined_knowledge_chunks") as save:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://a.test", "https://b.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 400
    body = response.get_json()
    assert body["status"] == "error"
    assert body["data"]["status"] == "failed"
    assert body["data"]["totals"]["failed"] == 2
    for source in body["data"]["sources"]:
        assert source["error_code"] == "scrape_failed"
        assert "dns failure" in source["error_message"]
    save.assert_not_called()


def test_an_embed_failure_on_one_source_leaves_the_other_ingested(
    client, authenticated
):
    def save(**kwargs):
        if "bad" in kwargs["primary_url"]:
            raise RuntimeError("supabase write failed")
        return {"file_name": kwargs["file_name"], "message": "ok"}

    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="text"), patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(f"{SERVICE}.save_refined_knowledge_chunks", side_effect=save):
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://good.test", "https://bad.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "partial"
    good, bad = data["sources"]
    assert good["status"] == "succeeded"
    assert bad["status"] == "failed"
    assert bad["phase"] == "embed"
    assert bad["error_code"] == "embed_failed"


def test_extract_returning_nothing_falls_back_to_raw_text_rather_than_losing_work(
    client, authenticated
):
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="raw page text"), patch(
        f"{SERVICE}.extract_business_knowledge", return_value=""
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ) as save:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    source = response.get_json()["data"]["sources"][0]
    assert stage_map(source)["extract"] == "partial"
    assert stage_map(source)["embed"] == "succeeded"
    assert source["status"] == "partial"
    assert "raw page text" in save.call_args.kwargs["text_content"]


# ── 4. Tenancy ────────────────────────────────────────────────────────────


def test_cannot_ingest_into_another_companys_chatbot(client):
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id", return_value=CURRENT_USER
    ), patch(
        "app.routes.knowledge_routes.verify_chatbot_access",
        side_effect=PermissionError("You do not have access to this chatbot."),
    ), patch(
        f"{SERVICE}.fetch_and_parse_url"
    ) as fetch, patch(
        f"{SERVICE}.save_refined_knowledge_chunks"
    ) as save:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json()["status"] == "error"
    # Denied before any network or write work happens.
    fetch.assert_not_called()
    save.assert_not_called()


def test_ingest_requires_chatbot_id(client, authenticated):
    response = client.post(
        "/api/knowledge/ingest",
        json={"sources": ["https://example.test"]},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400


def test_ingest_denies_members(client):
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value={**CURRENT_USER, "role": "member"},
    ), patch(
        f"{SERVICE}.fetch_and_parse_url"
    ) as fetch:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    fetch.assert_not_called()


def test_ingest_passes_the_authenticated_company_id_to_the_storage_quota_check(
    client, authenticated
):
    """The company_id must reach save_refined_knowledge_chunks, otherwise the
    storage quota check inside it (knowledge_service.py:673-674) is skipped."""
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="text"), patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ) as save:
        client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert save.call_args.kwargs["company_id"] == COMPANY_ID
    assert save.call_args.kwargs["chatbot_id"] == CHATBOT_ID


# ── 5. Billing / quota guards ─────────────────────────────────────────────


def test_plan_feature_gate_blocks_before_any_scraping(client):
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id", return_value=CURRENT_USER
    ), patch(
        "app.routes.knowledge_routes.verify_chatbot_access"
    ), patch(
        "app.routes.knowledge_routes.can_use_plan_feature",
        side_effect=BillingLimitError(
            "Your plan does not include batch website scraping",
            code="feature_not_in_plan",
        ),
    ), patch(
        f"{SERVICE}.fetch_and_parse_url"
    ) as fetch:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    body = response.get_json()
    assert body["status"] == "error"
    assert body["code"] == "feature_not_in_plan"
    fetch.assert_not_called()


def test_file_quota_gate_blocks_before_the_billed_llm_extraction(client):
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": 31, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id", return_value=CURRENT_USER
    ), patch(
        "app.routes.knowledge_routes.verify_chatbot_access"
    ), patch(
        "app.routes.knowledge_routes.can_use_plan_feature"
    ), patch(
        "app.routes.knowledge_routes.can_upload_knowledge_file",
        side_effect=BillingLimitError(
            "Knowledge file limit reached", code="file_limit"
        ),
    ), patch(
        f"{SERVICE}.extract_business_knowledge"
    ) as extract, patch(
        f"{SERVICE}.fetch_and_parse_url"
    ) as fetch:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.get_json()["code"] == "file_limit"
    extract.assert_not_called()
    fetch.assert_not_called()


def test_storage_quota_exhausted_midway_keeps_earlier_sources_ingested(
    client, authenticated
):
    """A quota error on source 2 must be reported against source 2 only —
    source 1 stays ingested."""
    calls: list[str] = []

    def save(**kwargs):
        calls.append(kwargs["primary_url"])
        if len(calls) == 1:
            return {"file_name": kwargs["file_name"], "message": "ok"}
        raise BillingLimitError(
            "Knowledge storage limit reached",
            code="knowledge_storage_limit",
            details={"limit_bytes": 1000},
        )

    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="text"), patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(f"{SERVICE}.save_refined_knowledge_chunks", side_effect=save):
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://first.test", "https://second.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "partial"
    first, second = data["sources"]
    assert first["status"] == "succeeded"
    assert second["status"] == "failed"
    assert second["error_code"] == "knowledge_storage_limit"
    assert "storage limit" in second["error_message"].lower()


# ── 6. Input validation at the boundary ───────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"sources": []},
        {"sources": "https://example.test"},
        {"sources": [{}]},
        {"sources": [{"url": ""}]},
        {"sources": [{"url": "   "}]},
        {"sources": [None]},
        {"sources": [123]},
        {"sources": [{"url": "ftp://example.test"}]},
        {"sources": [{"url": "javascript:alert(1)"}]},
        {"sources": [{"url": "https://example.test", "urls": "not-a-list"}]},
        {"sources": [{"url": "https://example.test", "max_pages": 0}]},
        {"sources": [{"url": "https://example.test", "max_pages": "many"}]},
        {"sources": [{"url": "https://example.test", "file_name": "  "}]},
        ["https://example.test"],
    ],
)
def test_malformed_source_payloads_are_rejected_with_400(
    client, authenticated, payload
):
    with patch(f"{SERVICE}.fetch_and_parse_url") as fetch:
        response = client.post(INGEST_URL, json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    fetch.assert_not_called()


def test_too_many_sources_is_rejected_rather_than_run_synchronously(
    client, authenticated
):
    from app.services import knowledge_ingestion_service

    too_many = [
        f"https://example.test/{i}"
        for i in range(knowledge_ingestion_service.MAX_SOURCES_PER_REQUEST + 1)
    ]
    with patch(f"{SERVICE}.fetch_and_parse_url") as fetch:
        response = client.post(
            INGEST_URL, json={"sources": too_many}, headers=AUTH_HEADERS
        )

    assert response.status_code == 400
    fetch.assert_not_called()


def test_discovered_pages_are_capped(client, authenticated):
    from app.services import knowledge_ingestion_service

    discovered = [f"https://example.test/{i}" for i in range(20)]
    with patch(f"{SERVICE}.discover_website_links", return_value=discovered), patch(
        f"{SERVICE}.fetch_and_parse_url", return_value="text"
    ) as fetch, patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ):
        response = client.post(
            INGEST_URL,
            json={"sources": [{"url": "https://example.test", "discover_links": True}]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert fetch.call_count == knowledge_ingestion_service.DEFAULT_MAX_PAGES

    source = response.get_json()["data"]["sources"][0]
    analyze = next(s for s in source["stages"] if s["name"] == "analyze")
    assert analyze["detail"]["discovered_pages"] == 20
    assert analyze["detail"]["selected_pages"] == (
        knowledge_ingestion_service.DEFAULT_MAX_PAGES
    )


def test_max_pages_is_clamped_to_the_ceiling(client, authenticated):
    from app.services import knowledge_ingestion_service

    ceiling = knowledge_ingestion_service.MAX_PAGES_CEILING
    discovered = [f"https://example.test/{i}" for i in range(ceiling + 10)]
    with patch(f"{SERVICE}.discover_website_links", return_value=discovered), patch(
        f"{SERVICE}.fetch_and_parse_url", return_value="text"
    ) as fetch, patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ):
        client.post(
            INGEST_URL,
            json={
                "sources": [
                    {
                        "url": "https://example.test",
                        "discover_links": True,
                        "max_pages": 9999,
                    }
                ]
            },
            headers=AUTH_HEADERS,
        )

    assert fetch.call_count == ceiling


def test_analyze_failure_falls_back_to_the_source_url_itself(client, authenticated):
    """Link discovery is best-effort: losing it must not lose the page."""
    with patch(
        f"{SERVICE}.discover_website_links", side_effect=RuntimeError("timeout")
    ), patch(f"{SERVICE}.fetch_and_parse_url", return_value="text") as fetch, patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ):
        response = client.post(
            INGEST_URL,
            json={"sources": [{"url": "https://example.test", "discover_links": True}]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    source = response.get_json()["data"]["sources"][0]
    assert stage_map(source)["analyze"] == "partial"
    assert source["status"] == "partial"
    fetch.assert_called_once_with("https://example.test")


def test_duplicate_urls_within_a_source_are_scraped_once(client, authenticated):
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="text") as fetch, patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ):
        client.post(
            INGEST_URL,
            json={
                "sources": [
                    {
                        "url": "https://example.test",
                        "urls": [
                            "https://example.test/a",
                            "https://example.test/a",
                            "https://example.test/b",
                        ],
                    }
                ]
            },
            headers=AUTH_HEADERS,
        )

    assert fetch.call_count == 2


def test_unicode_and_emoji_content_survives_ingestion(client, authenticated):
    content = "Café ☕ 价格: RM10 — 100% 正品 🎉"
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value=content), patch(
        f"{SERVICE}.extract_business_knowledge", return_value=content
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ) as save:
        response = client.post(
            INGEST_URL,
            json={"sources": ["https://example.test"]},
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert save.call_args.kwargs["text_content"] == content


def test_multi_page_source_file_name_follows_the_batch_convention(
    client, authenticated
):
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="text"), patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "f", "message": "ok"},
    ) as save:
        client.post(
            INGEST_URL,
            json={
                "sources": [
                    {
                        "url": "https://example.test",
                        "urls": [
                            "https://example.test/a",
                            "https://example.test/b",
                        ],
                    }
                ]
            },
            headers=AUTH_HEADERS,
        )

    assert save.call_args.kwargs["file_name"] == "https://example.test/a (+1 pages)"
    assert save.call_args.kwargs["primary_url"] == "https://example.test/a"


def test_custom_file_name_overrides_the_derived_one(client, authenticated):
    with patch(f"{SERVICE}.fetch_and_parse_url", return_value="text"), patch(
        f"{SERVICE}.extract_business_knowledge", return_value="REFINED"
    ), patch(
        f"{SERVICE}.save_refined_knowledge_chunks",
        return_value={"file_name": "Company site", "message": "ok"},
    ) as save:
        client.post(
            INGEST_URL,
            json={
                "sources": [
                    {"url": "https://example.test", "file_name": "Company site"}
                ]
            },
            headers=AUTH_HEADERS,
        )

    assert save.call_args.kwargs["file_name"] == "Company site"


# ── 7. Composition, not replacement ───────────────────────────────────────


def test_the_four_stage_endpoints_are_still_registered(client):
    app = create_app()
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert {
        "/api/knowledge/scrape-analyze",
        "/api/knowledge/scrape-batch",
        "/api/knowledge/scrape-extract",
        "/api/knowledge/scrape-embed",
        "/api/knowledge/ingest",
    } <= rules
