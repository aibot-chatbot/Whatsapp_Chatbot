"""Per-Client limits on document jobs, reports and email (Phase 5 items 8-10).

One Client must not be able to slow or exhaust these for every other Client:
document jobs share one machine and one queue consumer, reports share one
worker, and every email leaves through one SMTP account.

Limits are checked when a job is accepted. A job that already has a durable
row (a ``processing`` document, a ``queued`` report) is counted from that row;
an in-memory slot covers a job while it runs inside a request, and while an
accepted job's row is being written.
"""
import logging
import os
import threading
import time
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app.services.billing_guard import BillingLimitError

logger = logging.getLogger(__name__)

DOCUMENT_JOBS_PER_CLIENT = int(os.getenv("CLIENT_DOCUMENT_JOB_LIMIT", "3"))
REPORT_JOBS_PER_CLIENT = int(os.getenv("CLIENT_REPORT_JOB_LIMIT", "2"))
EMAILS_PER_CLIENT_PER_HOUR = int(os.getenv("CLIENT_EMAIL_HOURLY_LIMIT", "30"))

#: A document row still ``processing`` after this long was stranded by a deploy
#: or crash; counting it would lock the Client out of uploads for good.
STALE_DOCUMENT_JOB = timedelta(minutes=30)


class ClientJobLimitError(BillingLimitError):
    """Over a per-Client limit. A BillingLimitError so routes that only know that
    type still show this message (as a 403) rather than a 500."""

    status_code = 429

    def __init__(self, message):
        super().__init__(message, code="client_job_limit")


# shortcut: in-memory, so it holds for the one Fly machine running one gunicorn worker, upgrade when Redis lands (Part B)
_lock = threading.Lock()
_held = Counter()
_emails = defaultdict(deque)


@contextmanager
def _slot(kind, company_id, limit, in_flight, message):
    key = (kind, company_id)
    with _lock:
        if _held[key] + in_flight >= limit:
            raise ClientJobLimitError(message)
        _held[key] += 1
    try:
        yield
    finally:
        with _lock:
            _held[key] -= 1
            if not _held[key]:
                del _held[key]


def _count(count, *args, **kwargs):
    # A failed count reads as nothing in flight: the limiter must not become an outage.
    try:
        return count(*args, **kwargs)
    except Exception as exc:
        logger.warning("[ClientLimits] in-flight count failed (%s)", type(exc).__name__)
        return 0


def document_job(company_id):
    """Hold one of the Client's document-job slots; raises ClientJobLimitError when full."""
    from app.database.knowledge_file_repository import count_company_files_in_flight

    since = (datetime.now(timezone.utc) - STALE_DOCUMENT_JOB).isoformat()
    return _slot("document", company_id, DOCUMENT_JOBS_PER_CLIENT,
                 _count(count_company_files_in_flight, company_id, since),
                 f"You already have {DOCUMENT_JOBS_PER_CLIENT} documents being processed. "
                 "Please wait for one to finish, then try again.")


def report_job(company_id, *, exclude_client_message_id=None):
    """Hold one of the Client's report slots; raises ClientJobLimitError when full.

    ``exclude_client_message_id`` lets a retried request reach its own existing row.
    """
    from app.database.analysis_repository import count_company_reports_in_flight

    return _slot("report", company_id, REPORT_JOBS_PER_CLIENT,
                 _count(count_company_reports_in_flight, company_id,
                        exclude_client_message_id=exclude_client_message_id),
                 f"You already have {REPORT_JOBS_PER_CLIENT} reports being prepared. "
                 "Please wait for one to finish, then try again.")


def allow_client_email(company_id, email_type):
    """True to send. False (logged as type + company id) once the Client's hourly budget is spent."""
    now = time.monotonic()
    with _lock:
        sent = _emails[company_id]
        while sent and now - sent[0] >= 3600:
            sent.popleft()
        allowed = len(sent) < EMAILS_PER_CLIENT_PER_HOUR
        if allowed:
            sent.append(now)
    if not allowed:
        logger.warning("[ClientLimits] %s email skipped for company_id=%s: hourly limit reached",
                       email_type, company_id)
    return allowed
