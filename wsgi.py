"""
WSGI entry point for production deployment.

Usage:
    gunicorn wsgi:app
    waitress-serve wsgi:app

For local development, use run.py instead.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.services.document_storage_migration import migrate_before_startup

migrate_before_startup()
app = create_app()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes")


# run.py starts this inside its `__main__` guard, which never executes under a
# WSGI server. Without this the Wasender retry worker silently never runs in
# production, and a failed send is never retried.
#
# Guarded by an env flag because the loop must run in exactly ONE process. With
# more than one gunicorn worker, every worker would retry the same messages and
# the customer would receive duplicates. Set WASENDER_RETRY_WORKER_ENABLED=false
# on the extra workers, or move the loop to its own process.
if _env_flag("WASENDER_RETRY_WORKER_ENABLED", default=True):
    try:
        from app.services.wasender_retry_service import start_wasender_retry_worker

        start_wasender_retry_worker()
    except Exception as worker_error:
        # A dead retry worker must not stop the app from serving requests.
        logging.error("Wasender retry worker failed to start: %s", worker_error)


# Same reasoning as above, for the billing jobs under app/jobs/. The runbook
# prescribes cron for them, but fly.toml has no [processes] and Fly has no
# built-in cron, so nothing ever ran them: subscriptions were never transitioned
# to past_due/expired, stuck orders were never reconciled, and no expiry notice
# was ever generated. Single-process only - see billing_scheduler_service.
if _env_flag("BILLING_SCHEDULER_ENABLED", default=True):
    try:
        from app.services.billing_scheduler_service import start_billing_scheduler

        start_billing_scheduler()
    except Exception as scheduler_error:
        logging.error("Billing scheduler failed to start: %s", scheduler_error)


# The ingest consumer also starts on the first publish, but that alone leaves
# the queue unattended after a deploy: a message left in flight waits for the
# next upload before anyone pulls it, which on a quiet day is hours. Starting it
# here drains that backlog at boot instead.
#
# Deliberately NOT behind its own flag. The loop re-reads INGEST_QUEUE_ENABLED
# every iteration, so with the feature off this is one sleeping thread, and
# turning the feature on stays a secret change rather than a deploy. Unlike the
# two workers above, a second consumer would also be harmless: Cloudflare hands
# each puller a distinct batch, and the conditional claim in
# knowledge_ingest_queue means only one delivery can run the billed work.
try:
    from app.services.knowledge_ingest_queue import start_consumer

    start_consumer()
except Exception as consumer_error:
    logging.error("Knowledge ingest consumer failed to start: %s", consumer_error)
