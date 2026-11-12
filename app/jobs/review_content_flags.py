"""Nightly review per Client (plan A5): one email to the platform owner listing each Client's
safety flags from the last 24 hours. Quiet days send nothing. Counts only, never customer text.

"Stopped" flags are what Filter 1 (and Filter 2 in block mode) acted on. "Review only" are Filter 2
verdicts in log mode: reading them each day is how false alarms are found before block mode.
Run by the billing scheduler once a day (job ``review_content_flags``).
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

REVIEW_HOURS = 24


def _counts(counter):
    return ", ".join(f"{category} {count}" for category, count in sorted(counter.items()))


def build_lines(rows):
    stopped, review_only, self_harm = defaultdict(Counter), defaultdict(Counter), Counter()
    for row in rows:
        flag = row["payload"]["content_flag"]
        company, category = row.get("company_id"), flag.get("category")
        if category == "self_harm":
            self_harm[company] += 1
        elif flag.get("mode") == "log":
            review_only[company][category] += 1
        else:
            stopped[company][category] += 1
    lines = []
    for company in sorted(set(stopped) | set(review_only) | set(self_harm), key=str):
        parts = []
        if stopped[company]:
            parts.append(f"stopped {sum(stopped[company].values())} ({_counts(stopped[company])})")
        if review_only[company]:
            parts.append(f"review only {sum(review_only[company].values())} ({_counts(review_only[company])})")
        if self_harm[company]:
            parts.append(f"self-harm {self_harm[company]}")
        lines.append(f"Company {company}: " + "; ".join(parts))
    return lines


def main(argv):
    from app.database import agent_action_repository
    from app.services import email_service

    since = (datetime.now(timezone.utc) - timedelta(hours=REVIEW_HOURS)).isoformat()
    try:
        rows = agent_action_repository.get_content_flags_since(since=since)
    except Exception as error:
        logging.error("[ContentFlagReview] lookup failed (%s)", type(error).__name__)
        return 1
    lines = build_lines(rows)
    if not lines:
        return 0
    email_service._send_platform_alert(
        f"Omnexa: safety flags for {len(lines)} Clients in the last 24 hours",
        ["Safety flags per Client in the last 24 hours (counts only):", "", *lines, "",
         "Stopped: no AI saw the text. Review only: Filter 2 in log mode, recorded but not stopped; "
         "check these for false alarms. Self-harm: the customer was given the helpline and staff were alerted.",
         "A Client's owner is warned at 5 stopped flags in 7 days; at 10 you are asked to approve a pause."],
    )
    return 0
