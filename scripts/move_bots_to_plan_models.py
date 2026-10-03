"""Move every paid company's chatbots onto a model their plan still offers.

Why this exists: replies are refused, never silently re-routed, when a bot's saved
model is not on its plan (model_catalog.validate_plan_selection). When a plan's
model lineup changes, bots saved on a retired model stop answering until someone
re-saves them. The app only re-points bots when a plan is activated, so existing
subscribers need this one pass after a lineup change ships.

    python scripts/move_bots_to_plan_models.py            # show what would change
    python scripts/move_bots_to_plan_models.py --apply    # write it

A bot already on one of its plan's models is left alone; the rest move to the same
brand's model when the plan offers it (Claude stays Claude), else the plan default,
through billing_service.convert_trial_ai_configuration, the function plan activation uses. Safe to re-run: a second pass finds nothing.
Prints company and bot ids only, never names or customer data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from app.database.bot_repository import get_all_bots  # noqa: E402  (must follow load_dotenv)
from app.database.company_subscription_repository import get_company_subscription  # noqa: E402
from app.database.db import supabase  # noqa: E402
from app.database.subscription_plan_repository import get_plan_by_id  # noqa: E402
from app.services.billing_service import convert_trial_ai_configuration  # noqa: E402
from app.services.model_catalog import (  # noqa: E402
    OPENROUTER_PLAN_MODELS, is_plan_selection, plan_target_for,
)

PAGE = 1000  # PostgREST returns at most 1000 rows per request, silently


def company_ids_with_bots() -> list[int]:
    ids, start = set(), 0
    while True:
        page = (supabase.table("chatbots").select("company_id").is_("deleted_at", "null")
                .order("id").range(start, start + PAGE - 1).execute().data or [])
        ids.update(row["company_id"] for row in page if row.get("company_id"))
        if len(page) < PAGE:
            return sorted(ids)
        start += PAGE


def paid_plan_code(company_id: int) -> str | None:
    subscription = get_company_subscription(company_id)
    plan = get_plan_by_id(subscription.get("plan_id")) if subscription else None
    code = ((plan or {}).get("code") or "").strip().lower()
    return code if code in OPENROUTER_PLAN_MODELS else None


def stale_bots(plan_code: str, bots: list[dict]) -> list[dict]:
    return [bot for bot in bots
            if not is_plan_selection(plan_code, (bot.get("ai_provider") or "").strip().lower(),
                                     (bot.get("model_name") or "").strip())]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()
    print("Mode: " + ("APPLY" if args.apply else "dry run, pass --apply to write"))

    moved = failed = 0
    for company_id in company_ids_with_bots():
        plan_code = paid_plan_code(company_id)
        if plan_code is None:
            continue  # trial and unsubscribed companies keep the trial model
        stale = stale_bots(plan_code, get_all_bots(company_id))
        if not stale:
            continue
        for bot in stale:
            provider, model = plan_target_for(plan_code, (bot.get("ai_provider") or "").strip().lower())
            print(f"company {company_id} ({plan_code}) bot {bot['id']}: "
                  f"{bot.get('ai_provider')}/{bot.get('model_name')} -> {provider}/{model}")
        if not args.apply:
            moved += len(stale)
            continue
        try:
            convert_trial_ai_configuration(company_id, plan_code)
            moved += len(stale)
        except Exception as exc:  # report and continue; a re-run retries it
            failed += len(stale)
            print(f"company {company_id}: FAILED ({type(exc).__name__}: {exc})")

    print(f"Done: {'moved' if args.apply else 'would move'} {moved} bot(s), {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
