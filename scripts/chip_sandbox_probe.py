"""Opt-in CHIP sandbox smoke check; no Flask, database, or dotenv loading.

Set CHIP_TEST_API_KEY and CHIP_TEST_BRAND_ID (or CHIP_BRAND_ID) in the
process environment. Default: retrieve and validate the callback public key.
--create-checkout additionally requires CHIP_REDIRECT_URL and CHIP_WEBHOOK_URL.
It creates one synthetic RM1.01 checkout. --purchase-id only retrieves status.
Never retry an ambiguous creation without checking the merchant portal first.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import uuid4


def _load_adapter():
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "chip_service.py"
    spec = importlib.util.spec_from_file_location("_chip_sandbox_adapter", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--create-checkout", action="store_true", help="Create one synthetic test checkout for RM1.01")
    action.add_argument("--purchase-id", help="Retrieve one test purchase UUID without changing it")
    args = parser.parse_args(argv)
    adapter = None
    try:
        adapter = _load_adapter()
        if os.environ.get("CHIP_ENV", "test").strip().lower() != "test":
            raise adapter.ChipConfigError("This probe only supports test mode")
        config = adapter.ChipConfig(
            enabled=True, environment="test", live_enabled=False,
            api_key=os.environ.get("CHIP_TEST_API_KEY", "").strip(),
            brand_id=(os.environ.get("CHIP_TEST_BRAND_ID") or os.environ.get("CHIP_BRAND_ID", "")).strip(),
            redirect_url=os.environ.get("CHIP_REDIRECT_URL", "").strip(),
            webhook_url=os.environ.get("CHIP_WEBHOOK_URL", "").strip(),
        )
        config.validate_for_api()
        if args.create_checkout:
            result = adapter.create_purchase(
                config, order_reference=f"chip-test-{uuid4()}", amount_sen=101,
                description="CHIP integration test", customer_name="Integration Test",
                customer_email="chip-test@example.com", customer_phone=None,
            )
            output = {
                "purchase_id": result["gateway_order_id"], "checkout_url": result["checkout_url"],
                "status": result["gateway_status"], "is_test": result["is_test"],
                "brand_validated": result["brand_id"] == config.brand_id,
            }
        elif args.purchase_id:
            purchase = adapter.get_purchase(config, args.purchase_id)
            result = adapter.normalize_purchase(purchase)
            output = {
                "purchase_id": result["gateway_order_id"], "status": result["gateway_status"],
                "is_test": result["is_test"], "brand_validated": result["brand_id"] == config.brand_id,
                "paid": result["paid"], "amount_sen": result["amount_sen"],
                "currency": result["currency"], "paid_at": result["paid_at"],
            }
        else:
            adapter.get_public_key(config)
            # A public key lookup authenticates the key but cannot prove its mode.
            output = {"public_key_valid": True, "test_mode_requested": True, "purchase_mode_verified": False}
        print(json.dumps(output, sort_keys=True))
        return 0
    except Exception as exc:
        ambiguous = adapter is not None and isinstance(exc, adapter.ChipAmbiguousError)
        # Never print exception text or tracebacks: network exceptions can retain secrets.
        print(json.dumps({"ok": False, "manual_reconciliation_required": ambiguous}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
