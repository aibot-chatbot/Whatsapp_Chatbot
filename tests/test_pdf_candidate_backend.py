import io
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app import create_app
from app.services.document_ocr_service import ExtractionResult


AUTH_HEADERS = {"Authorization": "Bearer test-token"}
COMPANY_ID = 28
CHATBOT_ID = 29
USER_ID = 31

CURRENT_USER = {
    "id": USER_ID,
    "company_id": COMPANY_ID,
    "email": "tenant-28@example.test",
    "role": "admin",
    "status": "active",
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _vec(primary_axis=1.0, unrelated_axis=0.0, extra_axis=0.0):
    return [float(primary_axis), float(unrelated_axis), float(extra_axis)]


def _vec768(primary_axis=1.0, unrelated_axis=0.0, extra_axis=0.0):
    return [float(primary_axis), float(unrelated_axis), float(extra_axis)] + [0.0] * 765


def _embedded_chunk(content, vector=None, chunk_index=0):
    return {
        "id": 100 + chunk_index,
        "content": content,
        "embedding": vector or _vec(),
        "metadata": {"chunk_index": chunk_index},
    }


def _keyword_embedder(texts, expected_dimension=3):
    vectors = []
    for text in texts:
        lowered = text.casefold()
        if any(word in lowered for word in ("restaurant", "kitchen", "food", "recipe")):
            base = _vec(0.0, 1.0, 0.0)
        elif any(word in lowered for word in ("branch", "branches", "franchise", "partner", "materials")):
            base = _vec(0.92, 0.04, 0.04)
        else:
            base = _vec(0.96, 0.02, 0.02)
        vectors.append(base + [0.0] * max(0, expected_dimension - len(base)))
    return vectors, {"embedding_request_count": len(texts)}


class _ConfigApp:
    def __init__(self):
        self.config = {}


def _fake_config_getenv(overrides=None):
    overrides = overrides or {}

    def getenv(key, default=None):
        if key in overrides:
            return overrides[key]
        if key == "FLASK_DEBUG":
            return "1"
        return default

    return getenv


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["PDF_SUPPORTING_RELEVANCE_THRESHOLD"] = 0.45
    return app.test_client()


@pytest.fixture()
def authenticated():
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={"user_id": USER_ID, "company_id": COMPANY_ID, "role": "admin"},
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value=CURRENT_USER,
    ), patch(
        "app.routes.knowledge_routes.verify_chatbot_access",
    ), patch(
        "app.routes.knowledge_routes.can_upload_knowledge_file",
    ), patch(
        "app.routes.knowledge_routes.can_upload_knowledge_storage",
    ):
        yield


def test_default_supporting_pdf_threshold_is_initial_calibrated_value():
    from app import config as app_config

    app = _ConfigApp()
    with patch.object(app_config, "load_dotenv"), patch.object(
        app_config.os,
        "getenv",
        side_effect=_fake_config_getenv(),
    ):
        app_config.load_configurations(app)

    assert app.config["PDF_SUPPORTING_RELEVANCE_THRESHOLD"] == 0.65


def test_supporting_pdf_threshold_environment_override_is_preserved():
    from app import config as app_config

    app = _ConfigApp()
    with patch.object(app_config, "load_dotenv"), patch.object(
        app_config.os,
        "getenv",
        side_effect=_fake_config_getenv({"PDF_SUPPORTING_RELEVANCE_THRESHOLD": "0.72"}),
    ):
        app_config.load_configurations(app)

    assert app.config["PDF_SUPPORTING_RELEVANCE_THRESHOLD"] == 0.72


def test_local_relevance_score_passes_related_and_fails_unrelated():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [
        _embedded_chunk("Enterprise mathematics education competitions courses and franchise support.", _vec(), 0),
        _embedded_chunk("Learning programmes branch operations partner support and learning materials.", _vec(), 1),
    ]
    related = (
        "This supporting document expands branch details, franchise partner support, "
        "learning materials, and programme delivery for the mathematics education company."
    )
    unrelated = "Garden maintenance schedule, yoga class timetable, and home recipe collection."

    related_result = compare_candidate_to_primary(
        related,
        primary,
        threshold=0.45,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )
    unrelated_result = compare_candidate_to_primary(
        unrelated,
        primary,
        threshold=0.45,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert 0.0 <= related_result["score"] <= 1.0
    assert 0.0 <= unrelated_result["score"] <= 1.0
    assert related_result["passed"] is True
    assert unrelated_result["passed"] is False
    assert related_result["features"]["semantic_candidate_coverage"] > related_result["features"]["lexical_overlap_score"]


def test_exact_primary_content_duplicate_is_not_confirmable():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    text = "Refund policy and onboarding support escalation procedure."
    with patch("app.services.pdf_relevance_validation_service.embed_validation_chunks") as embedder:
        result = compare_candidate_to_primary(
            text,
            [_embedded_chunk(text, _vec(), 0)],
            threshold=0.1,
            embedder=embedder,
            embedding_dimension=3,
        )

    assert result["score"] == 1.0
    assert result["passed"] is False
    assert result["duplicate_status"] == "exact_content_duplicate"
    embedder.assert_not_called()


def test_threshold_boundary_uses_score_without_calibrating_threshold():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Enterprise refund policy onboarding support escalation workflow.", _vec(), 0)]
    candidate = "Enterprise refund policy onboarding support escalation workflow plus warranty notes."
    baseline = compare_candidate_to_primary(
        candidate,
        primary,
        threshold=0.0,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )
    score = baseline["score"]

    assert compare_candidate_to_primary(
        candidate,
        primary,
        threshold=max(0.0, score - 0.001),
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )["passed"] is True
    assert compare_candidate_to_primary(
        candidate,
        primary,
        threshold=min(1.0, score + 0.001),
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )["passed"] is False


def test_initial_calibrated_threshold_accepts_score_above_065_and_rejects_below():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Mathematics education programme details.", _vec(), 0)]
    above = compare_candidate_to_primary(
        "Branch programme details and partner support.",
        primary,
        threshold=0.65,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )
    below = compare_candidate_to_primary(
        "Restaurant kitchen food safety recipe handling.",
        primary,
        threshold=0.65,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert above["score"] > 0.65
    assert above["passed"] is True
    assert below["score"] < 0.65
    assert below["passed"] is False


def test_exact_boundary_is_inclusive_and_duplicate_still_blocks():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Mathematics education programme details.", _vec(), 0)]
    result = compare_candidate_to_primary(
        "Branch programme details and partner support.",
        primary,
        threshold=0.0,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )
    boundary = compare_candidate_to_primary(
        "Branch programme details and partner support.",
        primary,
        threshold=result["score"],
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )
    duplicate = compare_candidate_to_primary(
        "Mathematics education programme details.",
        primary,
        threshold=0.65,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert boundary["passed"] is True
    assert duplicate["score"] == 1.0
    assert duplicate["duplicate_status"] == "exact_content_duplicate"
    assert duplicate["passed"] is False


def test_unicode_normalization_preserves_non_ascii_terms():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Política de devolución para café premium y garantía de atención al cliente.", _vec(), 0)]
    candidate = "Guía de garantía, devolución, atención al cliente, y café premium."

    result = compare_candidate_to_primary(
        candidate,
        primary,
        threshold=0.1,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert result["score"] > 0
    assert any(term in result["matched_topics"] for term in ["política", "devolución", "café", "garantía"])


def test_validation_route_creates_candidate_but_no_normal_knowledge_or_ai(client, authenticated):
    from app.services import pdf_relevance_validation_service as svc

    created = {}

    def create_candidate(row):
        created.update(row)
        return dict(row)

    def update_candidate(_candidate_id, _chatbot_id, _company_id, fields):
        updated = dict(created)
        updated.update(fields)
        return updated

    extraction = ExtractionResult(
        markdown=(
            "Enterprise refund policy, onboarding support, escalation procedures, "
            "WhatsApp chatbot setup, analytics dashboard, and product catalog service tiers."
        ),
        page_count=2,
        character_count=130,
    )

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        svc, "CANDIDATE_DATA_FOLDER", tmpdir
    ), patch(
        "app.routes.knowledge_routes.get_active_knowledge_file",
        return_value={"id": 77, "file_name": "bot_29_primary.pdf"},
    ), patch.object(
        svc, "create_candidate", side_effect=create_candidate
    ) as candidate_insert, patch.object(
        svc, "mark_candidate_validated", side_effect=update_candidate
    ), patch.object(
        svc, "extract_pdf_markdown", return_value=extraction
    ), patch.object(
        svc, "get_chunks_by_file_for_chatbot",
        return_value=[
            _embedded_chunk("Enterprise refund policy and onboarding support escalation procedures.", _vec768(), 0),
            _embedded_chunk("WhatsApp chatbot setup analytics dashboard product catalog service tiers.", _vec768(), 1),
        ],
    ), patch.object(
        svc, "embed_validation_chunks", side_effect=_keyword_embedder
    ) as validation_embedding, patch(
        "app.services.knowledge_service.generate_and_save_knowledge_readme"
    ) as readme, patch(
        "app.services.knowledge_service.save_knowledge_file"
    ) as knowledge_file_insert, patch(
        "app.database.knowledge_chunk_repository.save_knowledge_chunk"
    ) as chunk_insert, patch(
        "app.services.knowledge_service.extract_and_store_graph_supabase"
    ) as graph_ai, patch(
        "app.services.persona_derivation_service.derive_persona_for_upload"
    ) as persona:
        response = client.post(
            f"/api/knowledge/pdf-candidates/validate?chatbot_id={CHATBOT_ID}",
            data={"pdf_file": (io.BytesIO(b"%PDF-1.4\ncontent"), "support.pdf")},
            headers=AUTH_HEADERS,
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["validation_status"] == "validated_passed", body.get("reason")
    assert body["can_confirm"] is True
    candidate_insert.assert_called_once()
    validation_embedding.assert_called_once()
    knowledge_file_insert.assert_not_called()
    chunk_insert.assert_not_called()
    graph_ai.assert_not_called()
    persona.assert_not_called()
    readme.assert_not_called()


def test_validation_route_fails_closed_when_primary_embeddings_missing(client, authenticated):
    from app.services import pdf_relevance_validation_service as svc

    created = {}

    def create_candidate(row):
        created.update(row)
        return dict(row)

    def update_candidate(_candidate_id, _chatbot_id, _company_id, fields):
        updated = dict(created)
        updated.update(fields)
        return updated

    extraction = ExtractionResult(
        markdown="Supporting branch details and programme delivery notes.",
        page_count=1,
        character_count=60,
    )

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        svc, "CANDIDATE_DATA_FOLDER", tmpdir
    ), patch(
        "app.routes.knowledge_routes.get_active_knowledge_file",
        return_value={"id": 77, "file_name": "bot_29_primary.pdf", "file_type": "pdf"},
    ), patch.object(
        svc, "create_candidate", side_effect=create_candidate
    ), patch.object(
        svc, "mark_candidate_validated", side_effect=update_candidate
    ), patch.object(
        svc, "extract_pdf_markdown", return_value=extraction
    ), patch.object(
        svc, "get_chunks_by_file_for_chatbot",
        return_value=[{"content": "Mathematics education programme details.", "metadata": {"chunk_index": 0}}],
    ), patch.object(
        svc, "embed_validation_chunks"
    ) as validation_embedding:
        response = client.post(
            f"/api/knowledge/pdf-candidates/validate?chatbot_id={CHATBOT_ID}",
            data={"pdf_file": (io.BytesIO(b"%PDF-1.4\ncontent"), "support.pdf")},
            headers=AUTH_HEADERS,
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["validation_status"] == "validated_failed"
    assert body["can_confirm"] is False
    assert body["error_code"] == "primary_embeddings_unavailable"
    assert "validation data" in body["reason"]
    validation_embedding.assert_not_called()


def test_validation_route_exposes_embedding_system_failure_code(client, authenticated):
    from app.services import pdf_relevance_validation_service as svc

    created = {}

    def create_candidate(row):
        created.update(row)
        return dict(row)

    def update_candidate(_candidate_id, _chatbot_id, _company_id, fields):
        updated = dict(created)
        updated.update(fields)
        return updated

    def failing_embedder(_texts, expected_dimension=768):
        raise svc.CandidateStateError("validation_embedding_failed", "We could not complete document validation. Please try again.")

    extraction = ExtractionResult(
        markdown="Supporting branch details and programme delivery notes.",
        page_count=1,
        character_count=60,
    )

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        svc, "CANDIDATE_DATA_FOLDER", tmpdir
    ), patch(
        "app.routes.knowledge_routes.get_active_knowledge_file",
        return_value={"id": 77, "file_name": "bot_29_primary.pdf", "file_type": "pdf"},
    ), patch.object(
        svc, "create_candidate", side_effect=create_candidate
    ), patch.object(
        svc, "mark_candidate_validated", side_effect=update_candidate
    ), patch.object(
        svc, "extract_pdf_markdown", return_value=extraction
    ), patch.object(
        svc, "get_chunks_by_file_for_chatbot",
        return_value=[_embedded_chunk("Mathematics education programme details.", _vec768(), 0)],
    ), patch.object(
        svc, "embed_validation_chunks", side_effect=failing_embedder
    ):
        response = client.post(
            f"/api/knowledge/pdf-candidates/validate?chatbot_id={CHATBOT_ID}",
            data={"pdf_file": (io.BytesIO(b"%PDF-1.4\ncontent"), "support.pdf")},
            headers=AUTH_HEADERS,
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["validation_status"] == "validated_failed"
    assert body["can_confirm"] is False
    assert body["error_code"] == "validation_embedding_failed"
    assert "unrelated" not in body["reason"].lower()


def test_dimension_mismatch_fails_closed_without_lexical_approval():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Mathematics education programme details.", [1.0, 0.0], 0)]
    result = compare_candidate_to_primary(
        "Mathematics education programme details and branches.",
        primary,
        threshold=0.1,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert result["passed"] is False
    assert result["features"]["error_code"] == "primary_embeddings_unavailable"


def test_provider_embedding_failure_fails_closed_without_side_effects():
    from app.services.pdf_relevance_validation_service import CandidateStateError, compare_candidate_to_primary

    def failing_embedder(_texts, expected_dimension=3):
        raise CandidateStateError("validation_embedding_failed", "Could not complete semantic validation for this PDF. Please try again.")

    primary = [_embedded_chunk("Mathematics education programme details.", _vec(), 0)]
    result = compare_candidate_to_primary(
        "Branch programme details and partner support.",
        primary,
        threshold=0.1,
        embedder=failing_embedder,
        embedding_dimension=3,
    )

    assert result["passed"] is False
    assert result["features"]["error_code"] == "validation_embedding_failed"


def test_cost_cap_limits_candidate_embedding_count_and_characters():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Mathematics education programme details.", _vec(), 0)]
    candidate = "\n\n".join(f"Branch programme details section {index} partner support materials." for index in range(20))
    seen = {}

    def capped_embedder(texts, expected_dimension=3):
        seen["count"] = len(texts)
        seen["chars"] = sum(len(text) for text in texts)
        return [_vec(0.95, 0.03, 0.02) for _ in texts], {"embedding_request_count": len(texts)}

    result = compare_candidate_to_primary(
        candidate,
        primary,
        threshold=0.1,
        embedder=capped_embedder,
        embedding_dimension=3,
        max_embedded_chunks=5,
        max_embedded_chars=180,
    )

    assert seen["count"] <= 5
    assert seen["chars"] <= 180
    assert result["features"]["candidate_embedded_chunk_count"] <= 5
    assert result["features"]["candidate_embedded_character_count"] <= 180
    assert result["features"]["representation_truncated"] is True


def test_topic_noise_and_domain_anchors_are_cleaned():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Olympic Edu IoMaths maths olympiad programme franchise support.", _vec(), 0)]
    candidate = (
        "Section: Supporting document\n"
        "Page 1 https://iomaths.example.com trigger question chatbot\n"
        "Olympic Edu IoMaths learning programme franchise partner support."
    )

    result = compare_candidate_to_primary(
        candidate,
        primary,
        threshold=0.1,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    noisy = {"section", "page", "com", "trigger"}
    assert not noisy & set(result["matched_topics"])
    assert result["features"]["domain_anchor_score"] > 0
    assert any("olympic edu" in topic or "iomaths" in topic for topic in result["matched_topics"])


def test_primary_embedding_reuse_embeds_only_candidate_chunks():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Mathematics education programme details.", _vec768(), 0)]

    with patch("app.services.rag_service.generate_embedding", return_value=_vec768()) as generate_embedding:
        result = compare_candidate_to_primary(
            "Branch programme details and partner support.",
            primary,
            threshold=0.1,
        )

    assert result["passed"] is True
    assert generate_embedding.call_count == result["features"]["candidate_embedded_chunk_count"]


def test_near_duplicate_requires_bidirectional_high_coverage_not_supporting_subset():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [
        _embedded_chunk("Mathematics education programme courses competitions.", _vec(1.0, 0.0, 0.0), 0),
        _embedded_chunk("Franchise partner support branches and materials.", _vec(0.9, 0.1, 0.0), 1),
        _embedded_chunk("Billing operations unrelated to the candidate subset.", _vec(0.0, 1.0, 0.0), 2),
    ]
    result = compare_candidate_to_primary(
        "Franchise partner support branch materials and programme details.",
        primary,
        threshold=0.1,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert result["passed"] is True
    assert result["duplicate_status"] == "none"


def test_whole_document_sampling_reaches_late_candidate_sections():
    from app.services import pdf_relevance_validation_service as svc

    chunks = [f"Early programme overview {index}" for index in range(svc.MAX_DOCUMENT_CHUNKS + 80)]
    chunks[-1] = "Late section branch franchise partner support materials"
    seen = {}

    def recording_embedder(texts, expected_dimension=3):
        seen["texts"] = list(texts)
        return [_vec(0.95, 0.03, 0.02) for _ in texts], {"embedding_request_count": len(texts)}

    with patch.object(svc, "_split_candidate_text", return_value=chunks):
        result = svc.compare_candidate_to_primary(
            "unused",
            [_embedded_chunk("Mathematics education franchise partner support.", _vec(), 0)],
            threshold=0.1,
            embedder=recording_embedder,
            embedding_dimension=3,
            max_embedded_chunks=6,
        )

    assert result["features"]["candidate_total_chunk_count"] == len(chunks)
    assert result["features"]["candidate_lexical_chunk_count"] == svc.MAX_DOCUMENT_CHUNKS
    assert result["features"]["candidate_embedded_chunk_count"] <= 6
    assert any("Late section" in text for text in seen["texts"])
    assert result["features"]["representation_truncated"] is True


def test_large_exact_duplicate_uses_full_candidate_hash_before_embeddings():
    from app.services import pdf_relevance_validation_service as svc

    chunks = [f"Primary source section {index} mathematics programme support" for index in range(svc.MAX_DOCUMENT_CHUNKS + 25)]
    primary_hash = svc.content_sha256("\n".join(chunks))
    primary_chunks = [_embedded_chunk(content, _vec(), index) for index, content in enumerate(chunks)]

    with patch.object(svc, "_split_candidate_text", return_value=chunks), patch.object(
        svc, "embed_validation_chunks"
    ) as embedder:
        result = svc.compare_candidate_to_primary(
            "unused",
            primary_chunks,
            threshold=0.1,
            embedder=embedder,
            embedding_dimension=3,
            canonical_primary_hash=primary_hash,
        )

    assert result["duplicate_status"] == "exact_content_duplicate"
    assert result["content_sha256"] == primary_hash
    embedder.assert_not_called()


def test_late_section_change_changes_canonical_candidate_hash():
    from app.services import pdf_relevance_validation_service as svc

    primary_chunks_text = [
        f"Primary source section {index} mathematics programme support"
        for index in range(svc.MAX_DOCUMENT_CHUNKS + 25)
    ]
    candidate_chunks = list(primary_chunks_text)
    candidate_chunks[-1] = "Changed late section branch franchise support"
    primary_hash = svc.content_sha256("\n".join(primary_chunks_text))
    primary_chunks = [_embedded_chunk(content, _vec(), index) for index, content in enumerate(primary_chunks_text)]

    with patch.object(svc, "_split_candidate_text", return_value=candidate_chunks):
        result = svc.compare_candidate_to_primary(
            "unused",
            primary_chunks,
            threshold=0.1,
            embedder=_keyword_embedder,
            embedding_dimension=3,
            canonical_primary_hash=primary_hash,
        )

    assert result["content_sha256"] != primary_hash
    assert result["duplicate_status"] != "exact_content_duplicate"


def test_embedding_cardinality_mismatch_fails_closed():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Mathematics education programme details.", _vec(), 0)]

    def fewer_vectors(texts, expected_dimension=3):
        return [_vec() for _ in texts[:-1]], {"embedding_request_count": 1}

    def more_vectors(texts, expected_dimension=3):
        return [_vec() for _ in texts] + [_vec()], {"embedding_request_count": len(texts)}

    candidate = "Branch programme details.\n\nPartner support materials."
    fewer = compare_candidate_to_primary(candidate, primary, threshold=0.1, embedder=fewer_vectors, embedding_dimension=3)
    more = compare_candidate_to_primary(candidate, primary, threshold=0.1, embedder=more_vectors, embedding_dimension=3)

    assert fewer["passed"] is False
    assert fewer["features"]["error_code"] == "validation_embedding_cardinality_mismatch"
    assert more["passed"] is False
    assert more["features"]["error_code"] == "validation_embedding_cardinality_mismatch"


def test_malformed_candidate_embedding_fails_closed():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    primary = [_embedded_chunk("Mathematics education programme details.", _vec(), 0)]

    def malformed_vectors(texts, expected_dimension=3):
        return [[1.0, "bad", 0.0] for _ in texts], {"embedding_request_count": len(texts)}

    result = compare_candidate_to_primary(
        "Branch programme details and partner support.",
        primary,
        threshold=0.1,
        embedder=malformed_vectors,
        embedding_dimension=3,
    )

    assert result["passed"] is False
    assert result["features"]["error_code"] == "validation_embedding_failed"


def test_exact_embedding_cardinality_scores_normally():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    result = compare_candidate_to_primary(
        "Branch programme details and partner support.",
        [_embedded_chunk("Mathematics education programme details.", _vec(), 0)],
        threshold=0.1,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert result["passed"] is True
    assert "error_code" not in result["features"]


def test_below_threshold_semantic_result_is_relevance_failure_not_system_failure():
    from app.services.pdf_relevance_validation_service import compare_candidate_to_primary

    result = compare_candidate_to_primary(
        "Restaurant kitchen food safety recipe handling.",
        [_embedded_chunk("Mathematics education programme details.", _vec(), 0)],
        threshold=0.8,
        embedder=_keyword_embedder,
        embedding_dimension=3,
    )

    assert result["passed"] is False
    assert "error_code" not in result["features"]
    assert "semantic coverage" in result["reason"]


def test_candidate_temp_file_cleaned_when_candidate_creation_fails():
    from app.services import pdf_relevance_validation_service as svc

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        svc, "CANDIDATE_DATA_FOLDER", tmpdir
    ), patch.object(
        svc, "create_candidate", side_effect=RuntimeError("db down")
    ):
        with pytest.raises(RuntimeError):
            svc.validate_supporting_pdf_candidate(
                file=_MemoryUpload("support.pdf", b"%PDF-1.4\ncontent"),
                chatbot_id=CHATBOT_ID,
                company_id=COMPANY_ID,
                created_by_user_id=USER_ID,
                threshold=0.5,
                primary_file={"id": 77, "file_name": "primary.pdf", "file_type": "pdf"},
            )

        assert list(os.scandir(os.path.join(tmpdir, str(COMPANY_ID), str(CHATBOT_ID)))) == []


def test_candidate_temp_file_cleaned_when_extraction_raises():
    from app.services import pdf_relevance_validation_service as svc

    created = {}

    def create_candidate(row):
        created.update(row)
        return dict(row)

    def mark_validated(_candidate_id, _chatbot_id, _company_id, fields):
        updated = dict(created)
        updated.update(fields)
        return updated

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        svc, "CANDIDATE_DATA_FOLDER", tmpdir
    ), patch.object(
        svc, "create_candidate", side_effect=create_candidate
    ), patch.object(
        svc, "extract_pdf_markdown", side_effect=RuntimeError("extract failed")
    ), patch.object(
        svc, "mark_candidate_validated", side_effect=mark_validated
    ):
        with pytest.raises(RuntimeError):
            svc.validate_supporting_pdf_candidate(
                file=_MemoryUpload("support.pdf", b"%PDF-1.4\ncontent"),
                chatbot_id=CHATBOT_ID,
                company_id=COMPANY_ID,
                created_by_user_id=USER_ID,
                threshold=0.5,
                primary_file={"id": 77, "file_name": "primary.pdf", "file_type": "pdf"},
            )

        assert list(os.scandir(os.path.join(tmpdir, str(COMPANY_ID), str(CHATBOT_ID)))) == []


def test_validation_route_without_primary_does_not_create_candidate(client, authenticated):
    from app.services import pdf_relevance_validation_service as svc

    with patch(
        "app.routes.knowledge_routes.get_active_knowledge_file",
        return_value=None,
    ), patch.object(svc, "create_candidate") as candidate_insert:
        response = client.post(
            f"/api/knowledge/pdf-candidates/validate?chatbot_id={CHATBOT_ID}",
            data={"pdf_file": (io.BytesIO(b"%PDF-1.4\ncontent"), "support.pdf")},
            headers=AUTH_HEADERS,
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["validation_status"] == "no_primary_source"
    candidate_insert.assert_not_called()


def test_validation_route_rejects_non_pdf_active_primary(client, authenticated):
    from app.services import pdf_relevance_validation_service as svc

    with patch(
        "app.routes.knowledge_routes.get_active_knowledge_file",
        return_value={"id": 77, "file_name": "https://example.test", "file_type": "url"},
    ), patch.object(svc, "create_candidate") as candidate_insert:
        response = client.post(
            f"/api/knowledge/pdf-candidates/validate?chatbot_id={CHATBOT_ID}",
            data={"pdf_file": (io.BytesIO(b"%PDF-1.4\ncontent"), "support.pdf")},
            headers=AUTH_HEADERS,
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["validation_status"] == "primary_not_pdf"
    assert body["can_confirm"] is False
    candidate_insert.assert_not_called()


def test_validation_route_denies_cross_chatbot_before_candidate_creation(client, authenticated):
    from app.services import pdf_relevance_validation_service as svc

    with patch(
        "app.routes.knowledge_routes.verify_chatbot_access",
        side_effect=PermissionError("You do not have access to this chatbot."),
    ), patch.object(svc, "create_candidate") as candidate_insert:
        response = client.post(
            f"/api/knowledge/pdf-candidates/validate?chatbot_id={CHATBOT_ID}",
            data={"pdf_file": (io.BytesIO(b"%PDF-1.4\ncontent"), "support.pdf")},
            headers=AUTH_HEADERS,
            content_type="multipart/form-data",
        )

    assert response.status_code == 403
    candidate_insert.assert_not_called()


def test_confirm_supporting_candidate_ingests_as_supporting_without_persona():
    from app.services import pdf_relevance_validation_service as svc

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
        handle.write(b"%PDF-1.4\nvalidated")
        temp_path = handle.name
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "validated_passed",
        "passed": True,
        "duplicate_status": "none",
        "expires_at": expires_at,
        "temp_file_path": temp_path,
        "safe_file_name": "support.pdf",
        "file_size": os.path.getsize(temp_path),
        "primary_file_id": 77,
        "primary_content_sha256": svc.content_sha256("primary source content"),
    }

    try:
        with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
            svc, "claim_candidate_for_confirmation", return_value=candidate
        ), patch.object(
            svc, "get_knowledge_file_by_source_candidate", return_value=None
        ), patch.object(
            svc, "can_upload_knowledge_file"
        ), patch.object(
            svc, "can_upload_knowledge_storage"
        ), patch.object(
            svc, "get_active_knowledge_file",
            return_value={"id": 77, "file_type": "pdf", "file_name": "primary.pdf"},
        ), patch.object(
            svc, "get_chunks_by_file_for_chatbot",
            return_value=[{"content": "primary source content"}],
        ), patch.object(
            svc, "save_uploaded_pdf",
            return_value={
                "status": "completed",
                "file_id": 88,
                "file_name": "bot_29_support.pdf",
                "message": "PDF uploaded as supporting knowledge.",
            },
        ) as save_pdf, patch.object(
            svc, "mark_candidate_ingested", return_value={**candidate, "validation_status": "ingested_supporting"}
        ), patch(
            "app.services.persona_derivation_service.derive_persona_for_upload"
        ) as persona:
            result = svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    assert result["validation_status"] == "ingested_supporting"
    assert result["ingested_knowledge_file_id"] == 88
    save_pdf.assert_called_once()
    assert save_pdf.call_args.kwargs["target_role"] == "supporting"
    assert save_pdf.call_args.kwargs["source_pdf_candidate_id"] == "candidate-1"
    persona.assert_not_called()


def test_primary_changed_after_validation_blocks_confirmation():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "validated_passed",
        "passed": True,
        "duplicate_status": "none",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "temp_file_path": "",
        "file_size": 10,
        "primary_file_id": 77,
        "primary_content_sha256": svc.content_sha256("old primary content"),
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "get_knowledge_file_by_source_candidate", return_value=None
    ), patch.object(
        svc, "get_active_knowledge_file", return_value={"id": 78, "file_type": "pdf", "file_name": "new.pdf"}
    ), patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "primary_changed_revalidation_required"
    save_pdf.assert_not_called()


def test_primary_removed_after_validation_blocks_confirmation():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "validated_passed",
        "passed": True,
        "duplicate_status": "none",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "temp_file_path": "",
        "file_size": 10,
        "primary_file_id": 77,
        "primary_content_sha256": svc.content_sha256("old primary content"),
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "get_knowledge_file_by_source_candidate", return_value=None
    ), patch.object(
        svc, "get_active_knowledge_file", return_value=None
    ), patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "primary_changed_revalidation_required"
    save_pdf.assert_not_called()


def test_primary_content_hash_change_blocks_confirmation():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "validated_passed",
        "passed": True,
        "duplicate_status": "none",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "temp_file_path": "",
        "file_size": 10,
        "primary_file_id": 77,
        "primary_content_sha256": svc.content_sha256("old primary content"),
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "get_knowledge_file_by_source_candidate", return_value=None
    ), patch.object(
        svc, "get_active_knowledge_file", return_value={"id": 77, "file_type": "pdf", "file_name": "primary.pdf"}
    ), patch.object(
        svc, "get_chunks_by_file_for_chatbot", return_value=[{"content": "new primary content"}]
    ), patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "primary_changed_revalidation_required"
    save_pdf.assert_not_called()


def test_primary_snapshot_hash_is_deterministic_across_chunk_order():
    from app.services import pdf_relevance_validation_service as svc

    ordered = [
        {"id": 300, "content": "first", "metadata": {"chunk_index": 0}},
        {"id": 301, "content": "second", "metadata": {"chunk_index": 1}},
        {"id": 302, "content": "third", "metadata": {"chunk_index": 2}},
    ]
    shuffled = [ordered[2], ordered[0], ordered[1]]
    primary = {"id": 77, "file_type": "pdf", "file_name": "primary.pdf"}

    with patch.object(svc, "get_chunks_by_file_for_chatbot", return_value=ordered):
        _texts, ordered_hash = svc._load_primary_snapshot(CHATBOT_ID, primary)
    with patch.object(svc, "get_chunks_by_file_for_chatbot", return_value=shuffled):
        _texts, shuffled_hash = svc._load_primary_snapshot(CHATBOT_ID, primary)

    assert ordered_hash == shuffled_hash


def test_large_primary_validation_persists_canonical_full_snapshot_hash():
    from app.services import pdf_relevance_validation_service as svc

    primary = {"id": 77, "file_type": "pdf", "file_name": "primary.pdf"}
    primary_chunks = [
        {
            "id": 1000 + index,
            "content": f"primary section {index} refund policy support workflow",
            "embedding": _vec768(),
            "metadata": {"chunk_index": index},
        }
        for index in range(svc.MAX_DOCUMENT_CHUNKS + 15)
    ]
    shuffled = list(reversed(primary_chunks))
    canonical_hash = svc.content_sha256("\n".join(chunk["content"] for chunk in primary_chunks))
    captured_update = {}

    def create_candidate(row):
        return dict(row)

    def mark_validated(_candidate_id, _chatbot_id, _company_id, fields):
        captured_update.update(fields)
        return {"id": _candidate_id, "original_file_name": "support.pdf", "expires_at": "later", **fields}

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        svc, "CANDIDATE_DATA_FOLDER", tmpdir
    ), patch.object(
        svc, "create_candidate", side_effect=create_candidate
    ), patch.object(
        svc, "mark_candidate_validated", side_effect=mark_validated
    ), patch.object(
        svc, "extract_pdf_markdown",
        return_value=ExtractionResult(
            markdown="refund policy support workflow",
            page_count=1,
            character_count=30,
        ),
    ), patch.object(
        svc, "get_chunks_by_file_for_chatbot", return_value=shuffled
    ), patch.object(
        svc, "embed_validation_chunks", side_effect=_keyword_embedder
    ):
        svc.validate_supporting_pdf_candidate(
            file=_MemoryUpload("support.pdf", b"%PDF-1.4\ncontent"),
            chatbot_id=CHATBOT_ID,
            company_id=COMPANY_ID,
            created_by_user_id=USER_ID,
            threshold=0.0,
            primary_file=primary,
        )

    assert captured_update["primary_content_sha256"] == canonical_hash

    candidate = {
        "id": "candidate-1",
        "primary_file_id": 77,
        "primary_content_sha256": canonical_hash,
    }
    with patch.object(svc, "get_active_knowledge_file", return_value=primary), patch.object(
        svc, "get_chunks_by_file_for_chatbot", return_value=shuffled
    ):
        svc._assert_current_primary_matches_candidate(candidate, CHATBOT_ID)


def test_primary_snapshot_hash_changes_when_chunk_content_changes():
    from app.services import pdf_relevance_validation_service as svc

    primary = {"id": 77, "file_type": "pdf", "file_name": "primary.pdf"}
    original = [
        {"id": 1, "content": "first", "metadata": {"chunk_index": 0}},
        {"id": 2, "content": "second", "metadata": {"chunk_index": 1}},
    ]
    changed = [
        {"id": 1, "content": "first", "metadata": {"chunk_index": 0}},
        {"id": 2, "content": "changed", "metadata": {"chunk_index": 1}},
    ]

    with patch.object(svc, "get_chunks_by_file_for_chatbot", return_value=original):
        _texts, original_hash = svc._load_primary_snapshot(CHATBOT_ID, primary)
    with patch.object(svc, "get_chunks_by_file_for_chatbot", return_value=changed):
        _texts, changed_hash = svc._load_primary_snapshot(CHATBOT_ID, primary)

    assert original_hash != changed_hash


def test_pdf_primary_detection_requires_type_or_pdf_evidence():
    from app.services import pdf_relevance_validation_service as svc

    assert svc._is_pdf_primary({"file_type": "pdf", "file_name": "source.bin"}) is True
    assert svc._is_pdf_primary({"file_type": "url", "file_name": "source.pdf"}) is False
    assert svc._is_pdf_primary({"file_type": "", "file_name": "legacy.pdf"}) is True
    assert svc._is_pdf_primary({"file_type": None, "file_path": "data/bot_1_legacy.pdf"}) is True
    assert svc._is_pdf_primary({"file_type": None, "file_name": "legacy-source"}) is False


def test_expired_candidate_cannot_confirm_and_is_marked_expired():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "validated_passed",
        "passed": True,
        "duplicate_status": "none",
        "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "temp_file_path": "",
        "file_size": 10,
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "get_knowledge_file_by_source_candidate", return_value=None
    ), patch.object(
        svc, "mark_candidate_expired"
    ) as expired, patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "candidate_expired"
    expired.assert_called_once_with("candidate-1", CHATBOT_ID, COMPANY_ID)
    save_pdf.assert_not_called()


def test_invalid_candidate_state_cannot_ingest():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "validated_failed",
        "passed": False,
        "duplicate_status": "none",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "temp_file_path": "",
        "file_size": 10,
        "primary_file_id": 77,
        "primary_content_sha256": svc.content_sha256("primary source content"),
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "get_knowledge_file_by_source_candidate", return_value=None
    ), patch.object(
        svc, "can_upload_knowledge_file"
    ), patch.object(
        svc, "can_upload_knowledge_storage"
    ), patch.object(
        svc, "claim_candidate_for_confirmation", return_value=None
    ), patch.object(
        svc, "get_active_knowledge_file", return_value={"id": 77, "file_type": "pdf", "file_name": "primary.pdf"}
    ), patch.object(
        svc, "get_chunks_by_file_for_chatbot", return_value=[{"content": "primary source content"}]
    ), patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "candidate_not_confirmable"
    save_pdf.assert_not_called()


def test_confirming_candidate_cannot_be_cancelled_or_delete_temp_file():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "confirming",
        "temp_file_path": "owned-by-ingestion.pdf",
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "mark_candidate_cancelled"
    ) as cancel, patch.object(
        svc, "cleanup_candidate_file"
    ) as cleanup:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.cancel_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "candidate_confirmation_in_progress"
    cancel.assert_not_called()
    cleanup.assert_not_called()


def test_cancel_does_not_delete_when_repository_rejects_state_transition():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "validated_passed",
        "temp_file_path": "candidate.pdf",
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "mark_candidate_cancelled", return_value=None
    ), patch.object(
        svc, "cleanup_candidate_file"
    ) as cleanup:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.cancel_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "candidate_not_cancellable"
    cleanup.assert_not_called()


def test_interrupted_post_ingestion_finalization_recovers_without_duplicate_ingest():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "confirming",
        "temp_file_path": "",
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc,
        "get_knowledge_file_by_source_candidate",
        return_value={"id": 88, "file_name": "bot_29_uuid_support.pdf", "is_active": False, "is_enabled": True},
    ), patch.object(
        svc, "recover_candidate_ingested", return_value={**candidate, "validation_status": "ingested_supporting"}
    ) as recover, patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        result = svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert result["ingested_knowledge_file_id"] == 88
    recover.assert_called_once_with("candidate-1", CHATBOT_ID, COMPANY_ID, 88)
    save_pdf.assert_not_called()


def test_ingest_failed_candidate_recovers_when_linked_knowledge_file_exists():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "ingest_failed",
        "temp_file_path": "",
    }
    persisted = {**candidate, "validation_status": "ingested_supporting", "ingested_knowledge_file_id": 88}

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc,
        "get_knowledge_file_by_source_candidate",
        return_value={
            "id": 88,
            "file_name": "bot_29_uuid_support.pdf",
            "original_file_name": "support.pdf",
            "is_active": False,
            "is_enabled": True,
        },
    ), patch.object(
        svc, "recover_candidate_ingested", return_value=persisted
    ) as recover, patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        result = svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert result["validation_status"] == "ingested_supporting"
    assert result["ingested_knowledge_file_id"] == 88
    assert result["candidate"]["validation_status"] == "ingested_supporting"
    assert result["knowledge_file"]["display_name"] == "support.pdf"
    recover.assert_called_once_with("candidate-1", CHATBOT_ID, COMPANY_ID, 88)
    save_pdf.assert_not_called()


def test_recovery_update_conflict_reloads_persisted_success_without_reingesting():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "ingest_failed",
        "temp_file_path": "",
    }
    reloaded = {**candidate, "validation_status": "ingested_supporting", "ingested_knowledge_file_id": 88}

    with patch.object(svc, "get_candidate", side_effect=[candidate, reloaded]), patch.object(
        svc,
        "get_knowledge_file_by_source_candidate",
        return_value={"id": 88, "file_name": "bot_29_uuid_support.pdf", "is_active": False, "is_enabled": True},
    ), patch.object(
        svc, "recover_candidate_ingested", return_value=None
    ) as recover, patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        result = svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert result["validation_status"] == "ingested_supporting"
    assert result["candidate"]["validation_status"] == "ingested_supporting"
    recover.assert_called_once_with("candidate-1", CHATBOT_ID, COMPANY_ID, 88)
    save_pdf.assert_not_called()


def test_recovery_update_conflict_with_failed_reload_raises_without_reingesting():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "ingest_failed",
        "temp_file_path": "",
    }
    reloaded = dict(candidate)

    with patch.object(svc, "get_candidate", side_effect=[candidate, reloaded]), patch.object(
        svc,
        "get_knowledge_file_by_source_candidate",
        return_value={"id": 88, "file_name": "bot_29_uuid_support.pdf", "is_active": False, "is_enabled": True},
    ), patch.object(
        svc, "recover_candidate_ingested", return_value=None
    ), patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        with pytest.raises(svc.CandidateStateError) as ctx:
            svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert ctx.value.code == "candidate_recovery_state_conflict"
    save_pdf.assert_not_called()


def test_repeated_successful_confirm_returns_existing_file_id_without_reingesting():
    from app.services import pdf_relevance_validation_service as svc

    candidate = {
        "id": "candidate-1",
        "chatbot_id": CHATBOT_ID,
        "company_id": COMPANY_ID,
        "validation_status": "ingested_supporting",
        "ingested_knowledge_file_id": 88,
    }

    with patch.object(svc, "get_candidate", return_value=candidate), patch.object(
        svc, "save_uploaded_pdf"
    ) as save_pdf:
        result = svc.confirm_supporting_pdf_candidate("candidate-1", CHATBOT_ID, COMPANY_ID)

    assert result["ingested_knowledge_file_id"] == 88
    save_pdf.assert_not_called()


class _FakeUpload:
    filename = "support.pdf"

    def save(self, path):
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4\n")


class _MemoryUpload:
    def __init__(self, filename, content):
        self.filename = filename
        self.stream = io.BytesIO(content)

    def seek(self, *args):
        return self.stream.seek(*args)


def test_save_uploaded_pdf_supporting_role_does_not_promote_primary():
    from app.services import knowledge_service

    recorded = {}

    def save_file(**kwargs):
        recorded.update(kwargs)
        return {"id": 91}

    extraction = ExtractionResult(markdown="supporting text", page_count=1, character_count=20)

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        knowledge_service, "DATA_FOLDER", tmpdir
    ), patch.object(
        knowledge_service, "save_knowledge_file", side_effect=save_file
    ), patch.object(
        knowledge_service, "_index_pdf_chunks", return_value=(2, "", extraction)
    ), patch.object(
        knowledge_service, "update_knowledge_file_status"
    ) as status, patch.object(
        knowledge_service, "set_active_pdf_knowledge_file"
    ) as set_active, patch.object(
        knowledge_service, "update_chatbot_runtime"
    ) as runtime, patch.object(
        knowledge_service, "generate_and_save_knowledge_readme"
    ), patch.object(
        knowledge_service, "log_knowledge_modification"
    ):
        result = knowledge_service.save_uploaded_pdf(_FakeUpload(), CHATBOT_ID, target_role="supporting")

    assert result["status"] == "completed"
    assert result["file_id"] == 91
    assert recorded["is_enabled"] is True
    assert recorded["is_active"] is False
    assert recorded["original_file_name"] == "support.pdf"
    set_active.assert_not_called()
    runtime.assert_not_called()
    status.assert_called_once_with(91, processing_status="completed")


def test_same_original_pdf_filename_does_not_overwrite_existing_file():
    from app.services import knowledge_service

    saved_records = []

    def save_file(**kwargs):
        saved_records.append(kwargs)
        return {"id": 90 + len(saved_records)}

    extraction = ExtractionResult(markdown="supporting text", page_count=1, character_count=20)

    with tempfile.TemporaryDirectory() as tmpdir, patch.object(
        knowledge_service, "DATA_FOLDER", tmpdir
    ), patch.object(
        knowledge_service, "save_knowledge_file", side_effect=save_file
    ), patch.object(
        knowledge_service, "_index_pdf_chunks", return_value=(2, "", extraction)
    ), patch.object(
        knowledge_service, "update_knowledge_file_status"
    ), patch.object(
        knowledge_service, "set_active_pdf_knowledge_file"
    ), patch.object(
        knowledge_service, "update_chatbot_runtime"
    ), patch.object(
        knowledge_service, "generate_and_save_knowledge_readme"
    ), patch.object(
        knowledge_service, "log_knowledge_modification"
    ):
        first = knowledge_service.save_uploaded_pdf(_FakeUpload(), CHATBOT_ID, target_role="supporting")
        second = knowledge_service.save_uploaded_pdf(_FakeUpload(), CHATBOT_ID, target_role="supporting")

        assert first["file_name"] != second["file_name"]
        assert first["original_file_name"] == "support.pdf"
        assert second["original_file_name"] == "support.pdf"
        assert saved_records[0]["original_file_name"] == "support.pdf"
        assert saved_records[1]["original_file_name"] == "support.pdf"
        assert saved_records[0]["file_path"] != saved_records[1]["file_path"]
        assert os.path.exists(first["file_path"])
        assert os.path.exists(second["file_path"])


def test_list_uploaded_pdfs_exposes_display_name_with_safe_fallback():
    from app.services import knowledge_service

    rows = [
        {
            "id": 1,
            "file_name": "bot_29_uuid_policy.pdf",
            "original_file_name": "policy.pdf",
            "file_type": "pdf",
            "is_active": False,
            "is_enabled": True,
        },
        {
            "id": 2,
            "file_name": "legacy.pdf",
            "file_type": "pdf",
            "is_active": False,
            "is_enabled": True,
        },
    ]

    with patch.object(knowledge_service, "get_knowledge_files", return_value=rows):
        result = knowledge_service.list_uploaded_pdfs(CHATBOT_ID)

    assert result[0]["file_name"] == "bot_29_uuid_policy.pdf"
    assert result[0]["display_name"] == "policy.pdf"
    assert result[1]["display_name"] == "legacy.pdf"


def test_active_pdf_exposes_display_name_and_preserves_internal_file_name():
    from app.services import knowledge_service

    internal_name = "bot_53_a88bed7fee6f4c2f8a1f055318c6a5d0_Speedbot.pdf"

    with patch.object(
        knowledge_service,
        "get_active_knowledge_file",
        return_value={
            "id": 53,
            "file_name": internal_name,
            "original_file_name": "Speedbot.pdf",
            "file_type": "pdf",
            "file_path": "/safe/path/" + internal_name,
            "is_active": True,
            "is_enabled": True,
        },
    ):
        result = knowledge_service.get_active_pdf(CHATBOT_ID)

    assert result["file_name"] == internal_name
    assert result["original_file_name"] == "Speedbot.pdf"
    assert result["display_name"] == "Speedbot.pdf"
    assert result["role"] == "primary"
    assert result["is_active"] is True


def test_active_pdf_display_name_falls_back_to_internal_file_name_for_legacy_rows():
    from app.services import knowledge_service

    with patch.object(
        knowledge_service,
        "get_active_knowledge_file",
        return_value={
            "id": 54,
            "file_name": "legacy.pdf",
            "file_type": "pdf",
            "is_active": True,
            "is_enabled": True,
        },
    ):
        result = knowledge_service.get_active_pdf(CHATBOT_ID)

    assert result["file_name"] == "legacy.pdf"
    assert result["display_name"] == "legacy.pdf"
    assert result["original_file_name"] is None


def test_candidate_linkage_insert_fails_closed_if_column_missing():
    from app.database import knowledge_file_repository as repo

    class _Insert:
        def __init__(self):
            self.calls = []

        def insert(self, data):
            self.calls.append(data)
            return self

        def execute(self):
            raise Exception("column knowledge_files.source_pdf_candidate_id does not exist")

    fake = _Insert()
    with patch.object(repo, "supabase") as supabase:
        supabase.table.return_value = fake
        with pytest.raises(Exception, match="source_pdf_candidate_id"):
            repo.save_knowledge_file(
                chatbot_id=CHATBOT_ID,
                file_name="bot_29_uuid_support.pdf",
                source_pdf_candidate_id="candidate-1",
            )

    assert len(fake.calls) == 1
    assert fake.calls[0]["source_pdf_candidate_id"] == "candidate-1"


def test_legacy_insert_may_fallback_without_optional_display_column():
    from app.database import knowledge_file_repository as repo

    class _Insert:
        def __init__(self):
            self.calls = []

        def insert(self, data):
            self.calls.append(dict(data))
            return self

        def execute(self):
            if len(self.calls) == 1:
                raise Exception("column knowledge_files.original_file_name does not exist")
            return type("Result", (), {"data": [{"id": 1}]})()

    fake = _Insert()
    with patch.object(repo, "supabase") as supabase:
        supabase.table.return_value = fake
        result = repo.save_knowledge_file(
            chatbot_id=CHATBOT_ID,
            file_name="bot_29_uuid_support.pdf",
            original_file_name="support.pdf",
        )

    assert result["id"] == 1
    assert "original_file_name" in fake.calls[0]
    assert "original_file_name" not in fake.calls[1]


def test_candidate_migration_hardens_table_access_and_recovery_key():
    migration = (PROJECT_ROOT / "data" / "045_create_knowledge_pdf_candidates.sql").read_text(encoding="utf-8").lower()

    assert "create table if not exists public.knowledge_pdf_candidates" in migration
    assert "alter table public.knowledge_pdf_candidates enable row level security" in migration
    assert "revoke all privileges on table public.knowledge_pdf_candidates" in migration
    assert "grant select, insert, update, delete on table public.knowledge_pdf_candidates" in migration
    assert "references public.chatbots(id)" in migration
    assert "references public.companies(id)" in migration
    assert "references public.knowledge_files(id)" in migration
    assert "source_pdf_candidate_id uuid" in migration
    assert "original_file_name text" in migration
    assert "knowledge_files_source_pdf_candidate_unique_idx" in migration


def test_candidate_migration_046_restricts_service_role_to_crud_grants():
    migration = (PROJECT_ROOT / "data" / "046_harden_knowledge_pdf_candidate_grants.sql").read_text(encoding="utf-8")
    executable_sql = re.sub(r"/\*.*?\*/", "", migration, flags=re.DOTALL)
    executable_sql = re.sub(r"--[^\n]*", "", executable_sql)
    normalized = " ".join(executable_sql.lower().split())

    revoke = "revoke all privileges on table public.knowledge_pdf_candidates from service_role"
    grant = "grant select, insert, update, delete on table public.knowledge_pdf_candidates to service_role"

    assert revoke in normalized
    assert grant in normalized
    assert normalized.index(revoke) < normalized.index(grant)

    grant_match = re.search(
        r"grant\s+(?P<privileges>.*?)\s+on\s+table\s+public\.knowledge_pdf_candidates\s+to\s+service_role",
        executable_sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert grant_match is not None
    privileges = {
        privilege.strip().lower()
        for privilege in grant_match.group("privileges").split(",")
    }

    assert privileges == {"select", "insert", "update", "delete"}
    assert "references" not in privileges
    assert "trigger" not in privileges
    assert "truncate" not in privileges

    statement_verbs = [
        match.group("verb").lower()
        for match in re.finditer(r"(?:^|;)\s*(?P<verb>[a-z_]+)", executable_sql, flags=re.IGNORECASE)
    ]
    assert statement_verbs == ["revoke", "grant"]
    assert "create" not in statement_verbs
    assert "drop" not in statement_verbs
    assert "delete" not in statement_verbs
    assert "update" not in statement_verbs
    assert "insert" not in statement_verbs
