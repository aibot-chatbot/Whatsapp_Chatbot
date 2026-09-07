"""reconcile_subscription_orders.py

Production-safe command to reconcile paid-but-not-completed subscription orders.

Usage:
    python -m app.jobs.reconcile_subscription_orders [--batch-size N] [--dry-run]
    python -m app.jobs.reconcile_subscription_orders --order-reference <ref>
    python -m app.jobs.reconcile_subscription_orders --company-id <id>

Safe to run repeatedly via cron or scheduler. Idempotent.

Exit codes:
    0 - completed successfully (possibly with per-order errors)
    1 - unrecoverable setup failure (configuration missing, etc.)
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from app.services.subscription_reconciliation_service import reconcile_subscription_order
from app.database.company_subscription_order_repository import (
    get_pending_hitpay_orders,
    get_reconcilable_subscription_orders,
)
from app.services.hitpay_service import HitPayConfig

logger = logging.getLogger(__name__)


DEFAULT_BATCH_SIZE = 100


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Reconcile paid-but-not-completed subscription orders.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Max orders to process per run")
    parser.add_argument("--dry-run", action="store_true", help="Log what would be done without making changes")
    parser.add_argument("--order-reference", type=str, default=None, help="Reconcile a specific order by reference")
    parser.add_argument("--company-id", type=int, default=None, help="Filter by company ID (used with --order-reference)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.batch_size is not None and (not isinstance(args.batch_size, int) or args.batch_size < 1):
        logger.error("batch-size must be a positive integer, got %r", args.batch_size)
        return 1

    if args.dry_run:
        logger.info("DRY RUN: No changes will be made.")

    if args.order_reference:
        orders_to_process = [{"order_reference": args.order_reference}]
    else:
        try:
            raw_orders = get_reconcilable_subscription_orders(limit=args.batch_size)
            if HitPayConfig.from_env().enabled:
                raw_orders.extend(get_pending_hitpay_orders(limit=args.batch_size))
                by_reference = {
                    order.get("order_reference"): order
                    for order in raw_orders
                    if isinstance(order, dict) and order.get("order_reference")
                }
                raw_orders = sorted(
                    by_reference.values(),
                    key=lambda order: order.get("updated_at") or order.get("created_at") or "",
                )[:args.batch_size]
        except Exception as exc:
            logger.error("Failed to fetch reconcilable orders: %s", exc)
            return 1
        orders_to_process = raw_orders

    if not orders_to_process:
        logger.info("No orders require reconciliation.")
        return 0

    scanned = 0
    completed = 0
    already_completed = 0
    conflicts = 0
    failed = 0

    for order in orders_to_process:
        ref = order.get("order_reference") if isinstance(order, dict) else order
        if not ref:
            continue
        scanned += 1

        if args.dry_run:
            logger.info("[DRY RUN] Would reconcile order %s (status=%s, activation=%s)",
                       ref, order.get("status"), order.get("activation_status"))
            continue

        try:
            result = reconcile_subscription_order(
                order_reference=ref,
                company_id=args.company_id,
            )
            outcome = result.get("outcome", "unknown")
            logger.info("Order %s: outcome=%s status=%s msg=%s",
                       ref, outcome, result.get("order_status"), result.get("message"))
            if outcome == "already_completed":
                already_completed += 1
            elif outcome in ("reconciled_and_completed", "credit_retry_completed"):
                completed += 1
            elif outcome in ("activation_already_claimed", "source_subscription_changed"):
                conflicts += 1
            else:
                failed += 1
        except Exception as exc:
            logger.error("Order %s reconciliation failed with exception: %s", ref, exc)
            failed += 1

    logger.info("Reconciliation complete: scanned=%d completed=%d already_completed=%d conflicts=%d failed=%d",
               scanned, completed, already_completed, conflicts, failed)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    sys.exit(main())
