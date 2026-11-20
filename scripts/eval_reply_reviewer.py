"""Evaluate the reply reviewer on the synthetic rulebook chats."""

import argparse
import json
import math
import os
import statistics
import sys
import time
import types
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/reply_check_chats.json"

# As in content_review_compare, the standalone CLI needs no Flask app, DB or other provider clients.
if __name__ == "__main__":
    for name, directory in (("app", ROOT / "app"), ("app.services", ROOT / "app/services")):
        package = types.ModuleType(name)
        package.__path__ = [str(directory)]
        sys.modules[name] = package

from app.services import cloudflare_service, reply_review_service
from app.services.reply_review_service import DEFAULT_REVIEW_MODEL
from app.services.reply_check_service import check_reply


def summarize(rows):
    confusion = defaultdict(Counter)
    accuracy = {}
    false_alarms, misses = [], []
    for row in rows:
        expected, actual = row["expected"], row["verdict"]
        prediction = "error" if actual == "error" else f"{actual}/{row['predicted_category']}"
        confusion[f"{expected}/{row['category']}"][prediction] += 1
        if expected == "filter":
            continue  # These grade incoming moderation, outside reviewer sections A-C.
        counts = accuracy.setdefault(row["language"], {"scored": 0, "verdict_correct": 0, "category_correct": 0})
        counts["scored"] += 1
        counts["verdict_correct"] += actual == expected
        counts["category_correct"] += actual == expected and row["predicted_category"] == row["category"]
        if expected == "hold" and actual != "hold":
            misses.append(row["id"])
        if expected == "pass" and actual == "hold":
            false_alarms.append(row["id"])
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "confusion": confusion, "accuracy_by_language": accuracy, "false_alarms": false_alarms, "misses": misses,
        "calls": len(rows), "returned_none": sum(row["verdict"] == "error" for row in rows),
        "median_ms": statistics.median(latencies), "p95_ms": latencies[math.ceil(0.95 * len(rows)) - 1],
        "needs_review": sum(row["needs_review"] for row in rows),
    }


def evaluate():
    rows = []
    for case in json.loads(FIXTURES.read_text(encoding="utf-8")):
        draft = case["bot_reply"]
        evidence = dict(knowledge=case["knowledge"], profile=case["business_profile"],
                        history=case["history"], customer_message=case["customer_message"])
        findings = check_reply(draft, **evidence)
        gated = reply_review_service.needs_review(draft, findings)
        started = time.perf_counter()
        result = reply_review_service.review_reply(draft, **evidence, code_findings=findings)
        rows.append({
            "id": case["id"], "language": case["language"], "expected": case["expected"],
            "category": case["category"], "verdict": result["verdict"] if result else "error",
            "predicted_category": result["category"] if result else None,
            "predicted_subtype": result["subtype"] if result else None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2), "needs_review": gated,
        })
    return rows


def print_summary(summary):
    columns = ("pass/none", "hold/facts", "hold/leak", "hold/promise", "error")
    print(f"{'Expected':16}", *(f"{label:>12}" for label in columns))
    for label, counts in sorted(summary["confusion"].items()):
        print(f"{label:16}", *(f"{counts[col]:12d}" for col in columns))
    print("Accuracy by language (A-C only, errors included):")
    for lang, counts in sorted(summary["accuracy_by_language"].items()):
        total = counts["scored"]
        print(f"  {lang}: verdict {counts['verdict_correct']}/{total}, verdict + category {counts['category_correct']}/{total}")
    print("False alarms on pass chats:", ", ".join(summary["false_alarms"]) or "none")
    print("Misses on hold chats:", ", ".join(summary["misses"]) or "none")
    print(f"Latency (ms): median={summary['median_ms']:.2f} p95={summary['p95_ms']:.2f}")
    print(f"calls={summary['calls']} returned_none={summary['returned_none']} "
          f"needs_review={summary['needs_review']}/{summary['calls']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("REPLY_REVIEW_MODEL", DEFAULT_REVIEW_MODEL))
    parser.add_argument("--env-file", type=Path, help="Read only the Workers AI account ID and API token from this file")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Exercise grading and reporting with an always-pass stub")
    args = parser.parse_args()
    if args.out.resolve() in (FIXTURES, args.env_file.resolve() if args.env_file else None):
        parser.error("Choose a separate results file.")
    if not args.model.startswith("@cf/"):
        parser.error("Select a native Workers AI chat model.")
    if not args.dry_run:
        names = ("CLOUDFLARE_AI_ACCOUNT_ID", "CLOUDFLARE_AI_API_TOKEN")
        if args.env_file:
            from dotenv import dotenv_values
            try:
                with args.env_file.open(encoding="utf-8-sig") as stream:
                    credentials = dotenv_values(stream=stream, interpolate=False)
            except (OSError, UnicodeError):
                parser.error("Cannot read the Workers AI env file.")
        else:
            credentials = os.environ
        if not all((credentials.get(name) or "").strip() for name in names):
            parser.error("Both Workers AI credentials are required for a live evaluation.")
        os.environ.update({name: credentials[name] for name in names})
    os.environ["REPLY_REVIEW_MODEL"] = args.model
    transport = nullcontext()
    if args.dry_run:
        print("DRY RUN: always-pass stub (zero network calls).")
        answer = dict(verdict="pass", category="none", subtype="none", reason="Offline stub.")
        transport = patch.object(cloudflare_service, "request",
                                 return_value={"choices": [{"message": {"content": json.dumps(answer)}}]})
    with transport:
        rows = evaluate()
    summary = summarize(rows)
    report = {"dry_run": args.dry_run, "model": args.model, "summary": summary, "rows": rows}
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print_summary(summary)


if __name__ == "__main__":
    main()
