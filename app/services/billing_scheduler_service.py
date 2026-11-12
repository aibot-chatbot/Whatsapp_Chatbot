"""In-process scheduler for the billing jobs under app/jobs/.

The three jobs are written as CLI entry points and the deployment runbook
prescribes cron for them, but nothing ever ran them: fly.toml has no
[processes], the Dockerfile CMD is gunicorn only, and Fly has no built-in cron.
So subscriptions were never transitioned, stuck orders were never reconciled,
and no expiry notice was ever generated.

This reuses the pattern already established by wasender_retry_service: a daemon
thread with a sleep loop, started from wsgi.py behind an env flag. No new
dependency - APScheduler would buy cron expressions we do not need for three
fixed intervals.

Guarded by an env flag for the same reason the Wasender worker is: the loop must
run in exactly ONE process. The Dockerfile runs gunicorn with --workers 1 and
fly.toml pins min_machines_running = 1, so a single in-process scheduler is safe
here. If either of those changes, set BILLING_SCHEDULER_ENABLED=false on the
extra workers and move this to its own process, or every worker duplicates the
work.
"""

import logging
import os
import threading
import time


# The runbook asks for reconciliation every 15 minutes, lifecycle persistence
# every 10 minutes, and notification generation daily. Intervals are measured
# from process start rather than wall-clock times: a fixed cadence needs no cron
# parsing, and every job here is idempotent, so the phase it lands on does not
# matter.
RECONCILE_INTERVAL_SECONDS = 15 * 60
LIFECYCLE_INTERVAL_SECONDS = 10 * 60
NOTIFICATIONS_INTERVAL_SECONDS = 24 * 60 * 60
# Shared across every pooled tenant, so it is checked as often as reconciliation.
PROVIDER_BALANCE_INTERVAL_SECONDS = 15 * 60
# A disabled key stops up to MAX_CLIENTS_PER_KEY Clients, so it gets the same cadence.
OPENROUTER_KEYS_INTERVAL_SECONDS = 15 * 60

# How often the loop wakes to see whether anything is due.
TICK_SECONDS = 60

# Let the app finish booting and start serving before the first sweep.
STARTUP_DELAY_SECONDS = 120

_scheduler_started = False
_last_successful_run = {}


def get_last_successful_run(job_name):
    """Return process-local monotonic evidence for operator health."""
    return _last_successful_run.get(job_name)


def _run_reconcile():
    from app.jobs.reconcile_subscription_orders import main
    from app.services.chip_topup_payment_service import reconcile_chip_topups
    from app.observability import capture_payment_failure

    result = main([])
    try:
        if reconcile_chip_topups():
            return 1
    except Exception as exc:
        capture_payment_failure("reconciliation", reason="unexpected", exc=exc)
        return 1
    return result


def _run_lifecycle():
    from app.jobs.process_subscription_lifecycle import main

    return main([])


def _run_notifications():
    from app.jobs.generate_billing_notifications import main

    return main([])


def _run_provider_balance():
    from app.jobs.check_ai_provider_balance import main

    return main([])


def _run_openrouter_keys():
    from app.jobs.check_openrouter_keys import main

    return main([])


def _run_content_flag_review():
    from app.jobs.review_content_flags import main

    return main([])


# (name, callable, default interval). Imports are deferred into the callables so
# a broken job module cannot stop the web app from booting.
JOBS = (
    ("reconcile_subscription_orders", _run_reconcile, RECONCILE_INTERVAL_SECONDS),
    ("process_subscription_lifecycle", _run_lifecycle, LIFECYCLE_INTERVAL_SECONDS),
    ("generate_billing_notifications", _run_notifications, NOTIFICATIONS_INTERVAL_SECONDS),
    ("check_ai_provider_balance", _run_provider_balance, PROVIDER_BALANCE_INTERVAL_SECONDS),
    ("check_openrouter_keys", _run_openrouter_keys, OPENROUTER_KEYS_INTERVAL_SECONDS),
    # shortcut: runs 24 h after process start, not at a fixed hour, so each deploy sends one early;
    # pin it to a local hour if the timing matters.
    ("review_content_flags", _run_content_flag_review, 24 * 3600),
)


def _env_int(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logging.warning("%s is not an integer (%r); using %s", name, raw, default)
        return default
    # Zero or negative would busy-loop the job forever.
    return value if value > 0 else default


def run_due_jobs(now, last_run):
    """Run every job whose interval has elapsed. Returns the updated last_run.

    Pure bookkeeping plus the job calls, so it can be driven directly in a test
    without a thread or a real clock.
    """
    updated = dict(last_run)

    for name, job, default_interval in JOBS:
        interval = _env_int(
            "BILLING_SCHEDULER_%s_SECONDS" % name.upper(), default_interval
        )
        previous = updated.get(name)
        if previous is not None and (now - previous) < interval:
            continue

        try:
            exit_code = job()
            if exit_code:
                logging.warning("Billing job %s exited with code %s", name, exit_code)
            else:
                logging.info("Billing job %s completed", name)
                _last_successful_run[name] = now
        except Exception as job_error:
            # One failing job must not stop the others or kill the thread.
            logging.error("Billing job %s failed: %s", name, job_error)

        updated[name] = now

    return updated


def billing_scheduler_loop():
    logging.info("Billing scheduler started.")
    time.sleep(_env_int("BILLING_SCHEDULER_STARTUP_DELAY_SECONDS", STARTUP_DELAY_SECONDS))

    last_run = {}
    while True:
        try:
            last_run = run_due_jobs(time.monotonic(), last_run)
        except Exception as loop_error:
            logging.error("Billing scheduler error: %s", loop_error)

        time.sleep(_env_int("BILLING_SCHEDULER_TICK_SECONDS", TICK_SECONDS))


def start_billing_scheduler():
    global _scheduler_started

    if _scheduler_started:
        logging.info("Billing scheduler already running.")
        return

    worker = threading.Thread(
        target=billing_scheduler_loop,
        daemon=True,
    )

    worker.start()
    _scheduler_started = True
