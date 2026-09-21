"""Optional Cloudflare Queue transport for the document ingest.

The in-process daemon thread that runs an ingest dies with its process: a
deploy in the middle of a two-to-eight minute pipeline loses the work and the
reason for it. Routing the job through a queue makes the work durable.

What these tests actually guard is the hazard that comes with it. Cloudflare
Queues deliver **at least once**, and this pipeline makes one billed LLM call
per chunk -- so a redelivered message that re-ran the pipeline would bill the
tenant twice for one document. The claim, not the visibility timeout, is what
stops that, and :func:`test_a_redelivered_duplicate_does_not_re_run_the_billed_phases`
is the test that proves it.

Nothing here performs real network or database I/O: ``cf_queue``'s three
transport functions are replaced per test, and the ``knowledge_files`` row is a
dict in a fake that models PostgREST's conditional update.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services import cf_queue
from app.services import knowledge_ingest_job_service as jobs
from app.services import knowledge_ingest_queue as ingest_queue
from app.services import knowledge_service


ACCOUNT_ID = "synthetic-cloudflare-account-id"
API_TOKEN = "synthetic-cf-queue-token"
QUEUE_ID = "synthetic-ingest-queue"

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


# ── Fakes ─────────────────────────────────────────────────────────────────


class _FakeUpdate:
    """One PostgREST update, including the predicate that makes it a claim."""

    def __init__(self, rows, payload):
        self._rows = rows
        self._payload = payload
        self._filters = []

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def execute(self):
        matched = [
            row
            for row in self._rows
            if all(row.get(column) == value for column, value in self._filters)
        ]
        for row in matched:
            row.update(self._payload)
        return SimpleNamespace(data=[dict(row) for row in matched])


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "knowledge_files", f"unexpected table {name}"
        return SimpleNamespace(update=lambda payload: _FakeUpdate(self.rows, payload))


def _lease(*, attempts=1, lease_id="lease-1", body=None):
    return cf_queue.Lease(
        lease_id=lease_id,
        body=dict(body if body is not None else ingest_queue._descriptor(ACCEPTED)),
        attempts=attempts,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate():
    jobs._jobs.clear()
    ingest_queue._started = False
    yield
    jobs._jobs.clear()
    ingest_queue._started = False


@pytest.fixture
def queue_on(monkeypatch):
    monkeypatch.setenv("INGEST_QUEUE_ENABLED", "true")
    monkeypatch.setenv("CF_QUEUE_INGEST_ID", QUEUE_ID)
    monkeypatch.setenv("CF_QUEUE_ENABLED", "true")
    monkeypatch.setenv("R2_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setenv("CF_QUEUE_API_TOKEN", API_TOKEN)


@pytest.fixture
def row(monkeypatch):
    """The ``knowledge_files`` row an accepted upload has just created."""
    rows = [
        {
            "id": ACCEPTED["file_id"],
            "chatbot_id": ACCEPTED["chatbot_id"],
            "processing_status": jobs.STATUS_PROCESSING,
        }
    ]
    monkeypatch.setattr("app.database.db.supabase", _FakeSupabase(rows))
    return rows[0]


@pytest.fixture
def settled(monkeypatch):
    """Record how each delivery was settled instead of calling Cloudflare."""
    calls = []

    def _ack(queue_id, *, acks, retries):
        calls.append((list(acks), list(retries)))
        return True

    monkeypatch.setattr(cf_queue, "ack", _ack)
    return calls


def _deliver(monkeypatch, *batches):
    """Make ``pull`` hand back these batches, one per ``_consume_once`` call."""
    remaining = list(batches)

    def _pull(queue_id, *, batch_size, visibility_timeout_ms):
        return remaining.pop(0) if remaining else []

    monkeypatch.setattr(cf_queue, "pull", _pull)


def _capture_threads(monkeypatch):
    """Record in-process ingest threads without running them."""
    started = []

    class _Recorded:
        def __init__(self, target=None, args=(), **_kwargs):
            started.append((target, args))

        def start(self):
            return None

    monkeypatch.setattr(jobs.threading, "Thread", _Recorded)
    return started


# ── 1. The flag is off, and off means today's code path ───────────────────


def test_the_flag_off_keeps_the_in_process_thread(monkeypatch):
    monkeypatch.delenv("INGEST_QUEUE_ENABLED", raising=False)
    send = Mock()
    monkeypatch.setattr(cf_queue, "send", send)
    started = _capture_threads(monkeypatch)

    jobs.start_pdf_ingest(dict(ACCEPTED))

    send.assert_not_called()
    assert len(started) == 1


def test_the_queue_stays_off_when_cloudflare_itself_is_off(monkeypatch):
    monkeypatch.setenv("INGEST_QUEUE_ENABLED", "true")
    monkeypatch.setenv("CF_QUEUE_INGEST_ID", QUEUE_ID)
    monkeypatch.delenv("CF_QUEUE_ENABLED", raising=False)

    assert ingest_queue.enabled() is False


def test_the_queue_stays_off_without_a_queue_id(monkeypatch, queue_on):
    monkeypatch.delenv("CF_QUEUE_INGEST_ID", raising=False)

    assert ingest_queue.enabled() is False


# ── 2. What gets published is a descriptor, never the document ────────────


def test_the_published_descriptor_carries_ids_not_the_document(monkeypatch, queue_on):
    sent = []
    monkeypatch.setattr(cf_queue, "send", lambda queue_id, body: sent.append((queue_id, body)) or True)
    monkeypatch.setattr(ingest_queue, "_ensure_started", Mock())
    started = _capture_threads(monkeypatch)

    jobs.start_pdf_ingest(dict(ACCEPTED))

    queue_id, body = sent[0]
    assert queue_id == QUEUE_ID
    assert set(body) == set(ingest_queue._DESCRIPTOR_FIELDS)
    assert not any(isinstance(value, (bytes, bytearray)) for value in body.values())
    assert len(json.dumps(body).encode("utf-8")) < cf_queue.MAX_BODY_BYTES
    # The queue owns the work now, so nothing runs in this process.
    assert started == []


def test_a_publish_failure_falls_back_to_the_in_process_thread(monkeypatch, queue_on):
    monkeypatch.setattr(cf_queue, "send", Mock(return_value=False))
    monkeypatch.setattr(ingest_queue, "_ensure_started", Mock())
    started = _capture_threads(monkeypatch)

    jobs.start_pdf_ingest(dict(ACCEPTED))

    assert len(started) == 1


def test_a_publish_that_raises_falls_back_to_the_in_process_thread(monkeypatch, queue_on):
    monkeypatch.setattr(cf_queue, "send", Mock(side_effect=RuntimeError("cloudflare down")))
    monkeypatch.setattr(ingest_queue, "_ensure_started", Mock())
    started = _capture_threads(monkeypatch)

    jobs.start_pdf_ingest(dict(ACCEPTED))

    assert len(started) == 1


# ── 3. The hazard: at-least-once delivery must not bill twice ─────────────


def test_a_redelivered_duplicate_does_not_re_run_the_billed_phases(
    monkeypatch, queue_on, row, settled
):
    """The claim, not the visibility timeout, is what stops the second run."""

    def _read(accepted, **_kwargs):
        # The real phase 1 records the terminal status on the row.
        row["processing_status"] = jobs.STATUS_COMPLETED
        return COMPLETED

    read = Mock(side_effect=_read)
    persona = Mock(return_value=Mock(status="succeeded", error_code=None, values={}))
    graph = Mock()

    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", read)
    monkeypatch.setattr(knowledge_service, "extract_and_store_graph_supabase", graph)
    monkeypatch.setattr(jobs, "_saved_chunk_texts", Mock(return_value=["a chunk"]))

    lease = _lease()
    _deliver(monkeypatch, [lease], [cf_queue.Lease(lease_id="lease-2", body=lease.body, attempts=2)])

    with patch(
        "app.services.persona_derivation_service.derive_persona_for_upload", persona
    ):
        ingest_queue._consume_once()
        ingest_queue._consume_once()

    # One billed persona call and one billed graph pass across two deliveries.
    assert read.call_count == 1
    assert persona.call_count == 1
    assert graph.call_count == 1
    # Both deliveries were acknowledged; neither was left to be redelivered.
    assert settled == [(["lease-1"], []), (["lease-2"], [])]


def test_a_delivery_for_a_document_already_being_ingested_is_acknowledged(
    monkeypatch, queue_on, row, settled
):
    row["processing_status"] = jobs.STATUS_INGESTING
    read = Mock()
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", read)
    _deliver(monkeypatch, [_lease(attempts=2)])

    ingest_queue._consume_once()

    read.assert_not_called()
    assert settled == [(["lease-1"], [])]


# ── 4. A message that keeps failing stops, visibly ────────────────────────


def test_a_message_past_the_retry_budget_marks_the_file_failed(
    monkeypatch, queue_on, row, settled
):
    read = Mock()
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", read)
    _deliver(monkeypatch, [_lease(attempts=ingest_queue.MAX_INGEST_ATTEMPTS + 1)])

    ingest_queue._consume_once()

    read.assert_not_called()
    assert row["processing_status"] == jobs.STATUS_FAILED

    job = jobs.get_ingest_status(ACCEPTED["chatbot_id"], ACCEPTED["file_id"])
    assert job["status"] == jobs.STATUS_FAILED
    assert "try uploading it again" in job["message"]
    # Acknowledged, not redelivered: looping on billed work is the thing to avoid.
    assert settled == [(["lease-1"], [])]


def test_a_claim_that_cannot_reach_the_database_is_redelivered_later(
    monkeypatch, queue_on, row, settled
):
    read = Mock()
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", read)
    monkeypatch.setattr(
        ingest_queue, "_transition", Mock(side_effect=RuntimeError("supabase down"))
    )
    _deliver(monkeypatch, [_lease()])

    ingest_queue._consume_once()

    read.assert_not_called()
    assert settled == [([], [("lease-1", ingest_queue.RETRY_DELAY_SECONDS)])]


def test_a_body_that_is_not_a_job_descriptor_is_discarded(
    monkeypatch, queue_on, row, settled
):
    read = Mock()
    monkeypatch.setattr(knowledge_service, "process_uploaded_pdf", read)
    _deliver(monkeypatch, [_lease(body={"chatbot_id": "not-a-number"})])

    ingest_queue._consume_once()

    read.assert_not_called()
    # Acked: no number of redeliveries will make a malformed body succeed.
    assert settled == [(["lease-1"], [])]


# ── 5. The claim window has to outlast the pipeline ───────────────────────


def test_the_visibility_timeout_outlasts_the_longest_pipeline():
    # The module docstring puts a scanned document at two to eight minutes.
    assert ingest_queue.VISIBILITY_TIMEOUT_MS >= 8 * 60 * 1000
    # Cloudflare's ceiling is twelve hours.
    assert ingest_queue.VISIBILITY_TIMEOUT_MS <= 12 * 60 * 60 * 1000


def test_one_message_is_claimed_at_a_time_for_the_whole_timeout(monkeypatch, queue_on):
    captured = {}

    def _pull(queue_id, *, batch_size, visibility_timeout_ms):
        captured.update(
            queue_id=queue_id,
            batch_size=batch_size,
            visibility_timeout_ms=visibility_timeout_ms,
        )
        return []

    monkeypatch.setattr(cf_queue, "pull", _pull)

    assert ingest_queue._consume_once() == 0
    assert captured["queue_id"] == QUEUE_ID
    # One consumer, minutes per message: a bigger batch would hold leases idle.
    assert captured["batch_size"] == 1
    assert captured["visibility_timeout_ms"] == ingest_queue.VISIBILITY_TIMEOUT_MS


# ── 6. Status reporting survives the new intermediate row state ───────────


def test_status_reports_a_claimed_ingest_as_processing(monkeypatch):
    monkeypatch.setattr(
        "app.database.knowledge_file_repository.get_knowledge_file_by_name_or_id",
        Mock(return_value={"id": 55, "processing_status": jobs.STATUS_INGESTING}),
    )

    job = jobs.get_ingest_status(7, 55)

    # The page renders one vocabulary; "ingesting" is an internal claim marker.
    assert job["status"] == jobs.STATUS_PROCESSING
    assert job["phase"] == jobs.PHASE_UNKNOWN


# ── 7. The consumer comes up at boot, not only on the first upload ────────


def test_start_consumer_is_idempotent_and_independent_of_the_flag(monkeypatch):
    monkeypatch.delenv("INGEST_QUEUE_ENABLED", raising=False)
    names = []

    class _Recorded:
        def __init__(self, **kwargs):
            names.append(kwargs.get("name"))

        def start(self):
            pass

    monkeypatch.setattr(ingest_queue.threading, "Thread", _Recorded)

    # wsgi.py calls this at boot with the feature off -- it must still start,
    # because _loop re-reads the flag and an operator turning it on should not
    # need a deploy. publish() then calls it again on the first upload.
    ingest_queue.start_consumer()
    ingest_queue.start_consumer()

    assert names == ["knowledge-ingest-consumer"]
