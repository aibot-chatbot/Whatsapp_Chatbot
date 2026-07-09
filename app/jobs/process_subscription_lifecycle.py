"""process_subscription_lifecycle.py - Production-safe lifecycle processing command.

Usage:
    python -m app.jobs.process_subscription_lifecycle [--batch-size N] [--dry-run]

Processes due subscription expiries in batches. Safe to run repeatedly
via cron or scheduler. Idempotent - subscriptions already expired are
skipped.

Exit codes:
    0 - completed successfully (possibly with per-company errors)
    1 - unrecoverable setup failure (configuration missing, etc.)
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from app.services.subscription_lifecycle_service import process_due_subscriptions

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace with batch_size and dry_run attributes.
    """
    parser = argparse.ArgumentParser(
        description="Process due subscription expiries in batches.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of subscriptions to process per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without modifying any data. Overrides the batch size to 10.",
    )
    parsed = parser.parse_args(argv)

    if parsed.batch_size < 1:
        parser.error("batch-size must be a positive integer")

    if parsed.dry_run:
        parsed.batch_size = min(parsed.batch_size, 10)

    return parsed


def main(argv: list[str] | None = None) -> int:
    """Run the subscription lifecycle batch processor.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        0 on success, 1 on unrecoverable setup failure.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S UTC",
    )

    args = parse_args(argv)
    batch_size = args.batch_size
    is_dry_run = args.dry_run

    logger.info(
        "Starting subscription lifecycle processing (batch_size=%d%s)",
        batch_size,
        ", DRY RUN" if is_dry_run else "",
    )

    try:
        now = datetime.now(timezone.utc)

        if is_dry_run:
            from app.database.company_subscription_repository import (
                get_due_subscriptions as _get_due,
            )
            due = _get_due(now_iso=now.isoformat(), batch_size=batch_size)
            logger.info(
                "DRY RUN: Found %d due subscription(s) that would be processed",
                len(due),
            )
            for sub in due:
                logger.info(
                    "  DRY: company=%s, status=%s, trial_ends=%s, period_end=%s",
                    sub.get("company_id"),
                    sub.get("status"),
                    sub.get("trial_ends_at"),
                    sub.get("current_period_end"),
                )
            return 0

        result = process_due_subscriptions(now=now, batch_size=batch_size)
    except Exception as exc:
        logger.exception("Unrecoverable error during lifecycle processing: %s", exc)
        return 1

    total_processed = result.get("total_processed", 0)
    errors = result.get("errors", [])
    due_count = result.get("due_count", 0)

    logger.info(
        "Lifecycle processing complete: %d scanned, %d expired, %d unchanged, %d failed",
        due_count,
        total_processed,
        due_count - total_processed - len(errors),
        len(errors),
    )

    if errors:
        for err in errors:
            logger.warning(
                "  Failed: company=%s, error=%s",
                err.get("company_id"),
                err.get("error"),
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
