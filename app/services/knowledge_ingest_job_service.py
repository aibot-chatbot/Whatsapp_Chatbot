"""Run a document ingest off the upload request thread.

``POST /upload-pdf`` used to do the whole pipeline inside the HTTP request:
OCR (one to three seconds per page, up to ``OCR_PAGE_LIMIT`` pages), one
embedding call per section, one **billed LLM call per section** for the
knowledge graph, and one more for the persona -- two to eight minutes of
browser spinner for a scanned document, most of it graph extraction.

This module runs that work after the response has gone out, in the order the
client actually needs it:

1. ``process_uploaded_pdf(build_graph=False)`` -- read, embed, promote. When
   this finishes the bot can answer from the document.
2. ``derive_persona_for_upload`` -- one LLM call that fills company name,
   business description and tone from the document, so the settings form is
   already filled in when the client reaches it. Deliberately ahead of the
   graph: it is one call, and it is the thing the client sees next.
3. ``extract_and_store_graph_supabase`` -- pure enrichment, one billed call
   per chunk, and by far the longest phase. Last, so nothing the client is
   waiting for sits behind it.

**Why a thread and not a queue.** The repo already runs background work this
way -- ``wasender_retry_service``, ``billing_scheduler_service`` and
``tenant_support_service`` all spawn daemon threads -- and the deployment is
deliberately a single machine running a single gunicorn worker with eight
threads (Dockerfile, fly.toml invariant 1). Adding a broker for this would be
a new moving part for a problem the process already solves.

**What is NOT deferred.** Access control (``verify_chatbot_access``) and the
billing gates (``can_upload_knowledge_file`` / ``can_upload_knowledge_storage``)
run in the request, before the file is accepted, exactly as before. A denied
upload never reaches this module. The AI calls made here resolve the tenant
from the bot record rather than from ``flask.g``
(``ai_router.generate_system_response`` -> ``_get_system_provider_for_enforcement``,
``billing_guard`` seam note at :423), so plan and credit enforcement still
apply with no request context.

**Status.** ``knowledge_files.processing_status`` is the durable record and is
already exposed by ``GET /api/knowledge/files``. The registry below adds what
that column cannot carry: the human-readable reason a read failed, what was
extracted, and the persona outcome. It is in-process and bounded.

ponytail: an in-memory registry loses its records on deploy or crash, so
:func:`get_ingest_status` falls back to the ``knowledge_files`` row and reports
``phase="unknown"``. Upgrade path is the ``knowledge_ingestion_jobs`` table in
``.omx/plans/guided-chatbot-creation-architecture.md`` §2b, which needs a
migration this change deliberately does not carry.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Final
import logging
import threading

# ── Phases, in the order the runner walks them ────────────────────────────
PHASE_READING: Final[str] = "reading"
PHASE_PERSONA: Final[str] = "persona"
PHASE_ENRICHING: Final[str] = "enriching"
PHASE_DONE: Final[str] = "done"
PHASE_UNKNOWN: Final[str] = "unknown"

#: Terminal statuses, shared with ``knowledge_files.processing_status`` so the
#: page renders one vocabulary whether the answer came from the registry or
#: from the row.
STATUS_PROCESSING: Final[str] = "processing"
STATUS_COMPLETED: Final[str] = "completed"
STATUS_FAILED: Final[str] = "failed"

#: Records kept before the oldest is dropped. One per upload, and only the
#: most recent matter -- the page polls within seconds of uploading.
MAX_TRACKED_JOBS: Final[int] = 50

_jobs: "OrderedDict[tuple[int, int], dict]" = OrderedDict()
_lock = threading.Lock()


def _record(chatbot_id: int, file_id: int, **fields: Any) -> None:
    """Create or update the record for one ingest, oldest evicted first."""
    key = (int(chatbot_id), int(file_id))

    with _lock:
        job = _jobs.pop(key, None) or {
            "chatbot_id": int(chatbot_id),
            "file_id": int(file_id),
            "status": STATUS_PROCESSING,
            "phase": PHASE_READING,
            "chunk_count": 0,
            "extraction": {},
            "persona_derivation": {"status": "pending", "error_code": None},
            "message": "",
        }
        job.update(fields)
        _jobs[key] = job

        while len(_jobs) > MAX_TRACKED_JOBS:
            _jobs.popitem(last=False)


def _run(accepted: dict) -> None:
    """Read, embed, derive and enrich. Never raises -- this is a thread body.

    A crash here must still be visible: the ``knowledge_files`` row is marked
    ``failed`` so the file list shows a broken source instead of a silently
    empty knowledge base, the record carries the reason, and the traceback is
    logged (and so reaches Sentry, which is wired to logging in
    ``app/observability.py``).
    """
    from app.services.knowledge_service import (
        extract_and_store_graph_supabase,
        process_uploaded_pdf,
    )

    chatbot_id = accepted["chatbot_id"]
    file_id = accepted["file_id"]

    try:
        result = process_uploaded_pdf(accepted, build_graph=False)
    except Exception as exc:
        logging.exception(
            "[Ingest] Reading the uploaded document failed for chatbot_id=%s, file_id=%s",
            chatbot_id,
            file_id,
        )
        _mark_row_failed(chatbot_id, file_id)
        _record(
            chatbot_id,
            file_id,
            status=STATUS_FAILED,
            phase=PHASE_DONE,
            error_code="ingest_failed",
            message=(
                "We could not finish reading this document. Nothing about your "
                "current knowledge has changed - please try uploading it again."
            ),
            error_message=str(exc),
        )
        return

    status = result.get("status", STATUS_COMPLETED)

    _record(
        chatbot_id,
        file_id,
        phase=PHASE_PERSONA,
        chunk_count=result.get("chunk_count", 0),
        extraction=result.get("extraction", {}),
        message=result.get("message", ""),
    )

    if status != STATUS_COMPLETED:
        # Nothing readable came out of the document, which process_uploaded_pdf
        # has already recorded on the row and explained in `message`. There is
        # no text to derive a persona from and no chunks to build a graph from.
        _record(chatbot_id, file_id, status=status, phase=PHASE_DONE)
        return

    _derive_persona(chatbot_id, file_id)

    # Terminal only now, one LLM call after the document became answerable.
    # The client's next step is the settings form, and it must find the values
    # this derivation wrote - so "processing" covers the derivation too, while
    # the graph enrichment below is left running behind the answer.
    _record(chatbot_id, file_id, status=status, phase=PHASE_ENRICHING)

    try:
        chunks = _saved_chunk_texts(chatbot_id, file_id)
        if chunks:
            extract_and_store_graph_supabase(chunks, chatbot_id, file_id)
    except Exception as graph_error:
        # The graph is enrichment on top of a document that already answers, so
        # its failure is logged and reported, never promoted to an ingest
        # failure. This is also where an out-of-credit tenant lands: the
        # extraction loop re-raises a billing error and the chunks it already
        # wrote are kept.
        logging.warning(
            "[Ingest] Knowledge graph enrichment failed for chatbot_id=%s, file_id=%s: %s",
            chatbot_id,
            file_id,
            graph_error,
        )
        _record(chatbot_id, file_id, graph_error=str(graph_error))

    _record(chatbot_id, file_id, phase=PHASE_DONE)


def _derive_persona(chatbot_id: int, file_id: int) -> None:
    """Fill the persona from the document just ingested, and record the outcome.

    ``derive_persona_for_upload`` is the seam that never raises, so this only
    has to carry its terminal report into the registry -- the page uses it to
    tell "your settings were filled in for you" apart from "we could not read a
    company name out of it, please type one".
    """
    from app.services.persona_derivation_service import derive_persona_for_upload

    derivation = derive_persona_for_upload(chatbot_id)

    _record(
        chatbot_id,
        file_id,
        persona_derivation={
            "status": derivation.status,
            "error_code": derivation.error_code,
            # Only the field names, never the values: the caller re-reads the
            # stored persona through /api/profiles, which is the one place
            # tenancy is checked for it.
            "fields": sorted(derivation.values.keys()),
        },
    )


def _saved_chunk_texts(chatbot_id: int, file_id: int) -> list:
    """The chunk text this ingest stored, read back for graph extraction.

    Re-read rather than carried across the phase boundary so the graph step
    works from what retrieval will actually search, and so it can be retried
    from the row alone.
    """
    from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot

    chunks = get_chunks_by_file_for_chatbot(chatbot_id, file_id) or []

    return [
        (chunk.get("content") or "").strip()
        for chunk in chunks
        if isinstance(chunk, dict) and (chunk.get("content") or "").strip()
    ]


def _mark_row_failed(chatbot_id: int, file_id: int) -> None:
    from app.database.knowledge_file_repository import update_knowledge_file_status

    try:
        update_knowledge_file_status(file_id, processing_status=STATUS_FAILED)
    except Exception:
        logging.exception(
            "[Ingest] Could not mark file_id=%s as failed for chatbot_id=%s",
            file_id,
            chatbot_id,
        )


def start_pdf_ingest(accepted: dict) -> None:
    """Start processing an accepted upload in the background.

    Args:
        accepted: The record ``knowledge_service.save_uploaded_pdf`` produces
            once the file is durable and the ``knowledge_files`` row exists.
            The caller must already have verified access and the billing gates.
    """
    _record(
        accepted["chatbot_id"],
        accepted["file_id"],
        status=STATUS_PROCESSING,
        phase=PHASE_READING,
        file_name=accepted.get("file_name", ""),
        original_file_name=accepted.get("original_file_name", ""),
    )

    threading.Thread(
        target=_run,
        args=(accepted,),
        name=f"knowledge-ingest-{accepted['file_id']}",
        daemon=True,
    ).start()


def get_ingest_status(chatbot_id: int, file_id: int) -> dict | None:
    """Report where one ingest got to, or ``None`` if nothing is known.

    Falls back to ``knowledge_files.processing_status`` when the process no
    longer holds the record -- after a deploy, or for a document ingested
    before this ran. The fallback can say whether it finished, not why.

    Args:
        chatbot_id: Owning chatbot. The caller must have verified access to it.
        file_id: The knowledge file being ingested.
    """
    with _lock:
        job = _jobs.get((int(chatbot_id), int(file_id)))
        if job is not None:
            return dict(job)

    from app.database.knowledge_file_repository import get_knowledge_file_by_name_or_id

    row = get_knowledge_file_by_name_or_id(chatbot_id, file_id)

    if not row:
        return None

    return {
        "chatbot_id": int(chatbot_id),
        "file_id": int(file_id),
        "status": row.get("processing_status") or STATUS_PROCESSING,
        "phase": PHASE_UNKNOWN,
        "chunk_count": 0,
        "extraction": {},
        "persona_derivation": {"status": "unknown", "error_code": None},
        "message": "",
    }
