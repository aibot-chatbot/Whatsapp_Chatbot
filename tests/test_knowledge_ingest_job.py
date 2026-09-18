"""Deferred document ingest: the upload returns before the work does.

``POST /upload-pdf`` used to hold the request open for the whole pipeline --
OCR, one embedding per section, one billed LLM call per section for the
knowledge graph, and one more for the persona. These tests lock the three
properties that made it safe to move that off the request thread:

1. the request returns as soon as the file is durable, and the ingest is
   started;
2. the runner derives the persona **before** the graph, because the client's
   next screen is the settings form and the graph is the longest phase;
3. a failure in the background is recorded, not swallowed -- the row is marked
   failed and the reason is retrievable.
"""

from unittest.mock import Mock, patch
import time

import pytest

from app.services import knowledge_ingest_job_service as jobs
from app.services import knowledge_service


ACCEPTED = {
    "chatbot_id": 7,
    "file_id": 55,
    "filepath": "/data/bot_7_guide.pdf",
    "file_name": "bot_7_guide.pdf",
    "original_file_name": "guide.pdf",
    "relative_pdf_path": "data/bot_7_guide.pdf",
    "target_role": "primary",
}

COMPLETED = {
    "status": "completed",
    "processing_status": "completed",
    "chunk_count": 3,
    "file_id": 55,
    "extraction": {"page_count": 2, "ocr_used": False},
    "message": "PDF uploaded and set as primary knowledge.",
}


@pytest.fixture(autouse=True)
def clear_registry():
    jobs._jobs.clear()
    yield
    jobs._jobs.clear()


def _run_and_wait(monkeypatch, **overrides):
    """Run one ingest synchronously by replacing the thread with a direct call."""
    started = {}

    class _Immediate:
        def __init__(self, target, args=(), **_kwargs):
            started["target"] = target
            started["args"] = args

        def start(self):
            started["target"](*started["args"])

    monkeypatch.setattr(jobs.threading, "Thread", _Immediate)
    jobs.start_pdf_ingest({**ACCEPTED, **overrides})
    return jobs.get_ingest_status(ACCEPTED["chatbot_id"], ACCEPTED["file_id"])


# ── 1. The request returns before the work ────────────────────────────────


def test_deferred_upload_returns_processing_without_reading_the_document(monkeypatch):
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", Mock(return_value={"id": 55}))
    monkeypatch.setattr(knowledge_service, "validate_saved_pdf", Mock(return_value=1024))
    monkeypatch.setattr(knowledge_service.document_storage, "persist_file", Mock())
    process = Mock()
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", process)
    start = Mock()
    monkeypatch.setattr(jobs, "start_pdf_ingest", start)

    upload = Mock()
    upload.filename = "guide.pdf"
    result = knowledge_service.save_uploaded_pdf(upload, 7, defer_processing=True)

    assert result["status"] == "processing"
    assert result["processing_status"] == "processing"
    assert result["file_id"] == 55
    # The expensive half must not have run inside the call.
    process.assert_not_called()
    start.assert_called_once()


def test_synchronous_upload_still_processes_inline(monkeypatch):
    """The candidate-confirm path reads the terminal status, so it must stay sync."""
    monkeypatch.setattr(knowledge_service, "save_knowledge_file", Mock(return_value={"id": 55}))
    monkeypatch.setattr(knowledge_service, "validate_saved_pdf", Mock(return_value=1024))
    monkeypatch.setattr(knowledge_service.document_storage, "persist_file", Mock())
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", Mock(return_value=COMPLETED))

    upload = Mock()
    upload.filename = "guide.pdf"

    assert knowledge_service.save_uploaded_pdf(upload, 7)["status"] == "completed"


# ── 2. Phase order: answerable, then persona, then the graph ──────────────


def test_persona_is_derived_before_the_graph_is_built(monkeypatch):
    order = []

    monkeypatch.setattr(
        knowledge_service, "process_uploaded_pdf",
        Mock(side_effect=lambda *_a, **_kw: order.append("read") or COMPLETED),
    )
    monkeypatch.setattr(
        jobs, "_saved_chunk_texts", Mock(return_value=["a chunk"]),
    )
    monkeypatch.setattr(
        knowledge_service, "extract_and_store_graph_supabase",
        Mock(side_effect=lambda *_a: order.append("graph")),
    )

    derivation = Mock(status="succeeded", error_code=None, values={"tone": "Friendly"})
    with patch(
        "app.services.persona_derivation_service.derive_persona_for_upload",
        Mock(side_effect=lambda _bot: order.append("persona") or derivation),
    ):
        job = _run_and_wait(monkeypatch)

    assert order == ["read", "persona", "graph"]
    assert job["status"] == "completed"
    assert job["phase"] == jobs.PHASE_DONE
    assert job["persona_derivation"]["status"] == "succeeded"


def test_the_document_is_not_reported_ready_before_the_persona_is_written(monkeypatch):
    """The client's next screen is the settings form, so it waits for the persona."""
    seen = []

    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", Mock(return_value=COMPLETED))
    monkeypatch.setattr(jobs, "_saved_chunk_texts", Mock(return_value=[]))

    def _derive(_bot):
        seen.append(jobs.get_ingest_status(7, 55)["status"])
        return Mock(status="succeeded", error_code=None, values={})

    with patch(
        "app.services.persona_derivation_service.derive_persona_for_upload", _derive
    ):
        job = _run_and_wait(monkeypatch)

    assert seen == ["processing"]
    assert job["status"] == "completed"


def test_a_document_that_read_as_nothing_skips_persona_and_graph(monkeypatch):
    failed = {**COMPLETED, "status": "failed", "chunk_count": 0,
              "message": "No readable text could be extracted from this PDF."}
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", Mock(return_value=failed))
    graph = Mock()
    monkeypatch.setattr(knowledge_service, "extract_and_store_graph_supabase", graph)

    with patch(
        "app.services.persona_derivation_service.derive_persona_for_upload"
    ) as derive:
        job = _run_and_wait(monkeypatch)

    derive.assert_not_called()
    graph.assert_not_called()
    assert job["status"] == "failed"
    assert "No readable text" in job["message"]


# ── 3. Background failures stay visible ───────────────────────────────────


def test_a_crash_marks_the_row_failed_and_keeps_the_reason(monkeypatch):
    monkeypatch.setattr(
        knowledge_service, "process_uploaded_pdf",
        Mock(side_effect=RuntimeError("supabase down")),
    )
    mark = Mock()
    monkeypatch.setattr(
        "app.database.knowledge_file_repository.update_knowledge_file_status", mark
    )

    job = _run_and_wait(monkeypatch)

    mark.assert_called_once_with(55, processing_status="failed")
    assert job["status"] == "failed"
    assert job["error_code"] == "ingest_failed"
    assert job["error_message"] == "supabase down"
    # The client gets a sentence, never the internal error.
    assert "supabase" not in job["message"]


def test_a_failed_graph_does_not_fail_a_document_that_answers(monkeypatch):
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", Mock(return_value=COMPLETED))
    monkeypatch.setattr(jobs, "_saved_chunk_texts", Mock(return_value=["a chunk"]))
    monkeypatch.setattr(
        knowledge_service, "extract_and_store_graph_supabase",
        Mock(side_effect=RuntimeError("ai credit exhausted")),
    )

    with patch(
        "app.services.persona_derivation_service.derive_persona_for_upload",
        Mock(return_value=Mock(status="succeeded", error_code=None, values={})),
    ):
        job = _run_and_wait(monkeypatch)

    assert job["status"] == "completed"
    assert job["graph_error"] == "ai credit exhausted"


def test_status_falls_back_to_the_stored_row_when_the_record_is_gone(monkeypatch):
    monkeypatch.setattr(
        "app.database.knowledge_file_repository.get_knowledge_file_by_name_or_id",
        Mock(return_value={"id": 55, "processing_status": "completed"}),
    )

    job = jobs.get_ingest_status(7, 55)

    assert job["status"] == "completed"
    assert job["phase"] == jobs.PHASE_UNKNOWN


def test_the_registry_does_not_grow_without_bound(monkeypatch):
    for file_id in range(jobs.MAX_TRACKED_JOBS + 10):
        jobs._record(7, file_id, status="completed")

    assert len(jobs._jobs) == jobs.MAX_TRACKED_JOBS
    # Oldest evicted first.
    assert (7, 0) not in jobs._jobs
    assert (7, jobs.MAX_TRACKED_JOBS + 9) in jobs._jobs


# ── 4. Embedding concurrency keeps every chunk, in order ──────────────────


def test_embedding_chunks_concurrently_preserves_order_and_content(monkeypatch):
    chunks = [f"chunk {index}" for index in range(25)]

    def slow_embed(text):
        # Sleep so a sequential implementation cannot pass the timing check
        # below by accident, and so out-of-order completion is possible.
        time.sleep(0.02)
        return [float(len(text))]

    with patch("app.services.rag_service.generate_embedding", slow_embed):
        started = time.perf_counter()
        embedded = knowledge_service._embed_chunks(chunks)
        elapsed = time.perf_counter() - started

    assert [index for index, _chunk, _embedding in embedded] == list(range(25))
    assert [chunk for _index, chunk, _embedding in embedded] == chunks
    assert all(embedding for _index, _chunk, embedding in embedded)
    # 25 serial calls would be 0.5s; eight at a time is a quarter of that.
    assert elapsed < 0.3


def test_a_chunk_whose_embedding_failed_is_kept_out_of_the_index(monkeypatch):
    with patch("app.services.rag_service.generate_embedding", Mock(return_value=[])):
        embedded = knowledge_service._embed_chunks(["only chunk"])

    assert embedded == [(0, "only chunk", [])]
