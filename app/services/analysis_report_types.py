"""analysis_report_types.py - What each kind of Analysis report shows, and in what order.

A report's type (crm, bookings, sales, documents) picks its layout: the headline numbers
(cards) and the sections that follow the AI summary. The layout is frozen into the snapshot,
so the page, the PDF and the Excel file draw the same plan and a report never changes look
later. Every number here is computed from rows the report service has already scoped and
cleaned; the model only writes the commentary. Money is integer micro-MYR.
"""

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

REPORT_TYPES = {"crm": "operations", "bookings": "business", "sales": "business", "documents": "documents"}
TITLES = {"crm": "Conversations and CRM report", "bookings": "Bookings report", "sales": "Sales report",
          "documents": "Document summary"}
# One line added to the commentary prompt, so each type's text has its own angle.
FOCUS = {
    "crm": "This is a conversations and CRM report: cover conversation volume by channel, who replied, "
           "CRM lead stages and the customer-question themes.",
    "bookings": "This is a bookings report: cover booking demand, bookings still waiting for the team, "
                "cancellations, the most booked services and busy booking times.",
    "sales": "This is a sales report: cover booking value by package and by week. Booking value is the price "
             "saved on confirmed and completed bookings made in chat, not total business revenue.",
    "documents": "This is a document summary: summarize each document in turn from its excerpts.",
}
_SALES_WORDS = re.compile(r"\b(?:sales?|revenue|income|earnings?|jualan|pendapatan)\b|销售|营业额|收入", re.IGNORECASE)
UPCOMING_DAYS = 14
MAX_TABLE_ROWS = 20
STATUS_LABELS = {"requested": "Waiting for your team", "confirmed": "Confirmed",
                 "completed": "Completed", "cancelled": "Cancelled"}
# Headline labels say "bookings" so they never read like the business-record "Confirmed bookings".
METRIC_LABELS = {"requested": "Bookings waiting for your team", "confirmed": "Bookings confirmed",
                 "completed": "Bookings completed", "cancelled": "Bookings cancelled"}
VALUE_STATUSES = frozenset({"confirmed", "completed"})


def resolve_report_type(spec, request_text=""):
    """The owner's choice when given, else from the planned kind and the request's words."""
    chosen = spec.get("report_type")
    if chosen in REPORT_TYPES:
        return chosen
    if spec.get("kind") == "documents":
        return "documents"
    if spec.get("kind") == "operations":
        return "crm"
    return "sales" if _SALES_WORDS.search(str(request_text or "")) else "bookings"


# --- layouts ------------------------------------------------------------------------------

def _table_item(key):
    return {"kind": "table", "key": key}


def _grid_item(key):
    return {"kind": "distribution", "key": key}


def _metrics_item(keys=(), prefix=None):
    return {"kind": "metrics", "keys": list(keys), **({"prefix": prefix} if prefix else {})}


def _section(title, *items):
    return {"title": title, "items": list(items)}


CARDS = {
    "crm": ["conversations", "active_conversations", "crm_leads", "customer_messages"],
    "bookings": ["bookings_created", "bookings_requested", "bookings_confirmed", "bookings_cancelled"],
    "sales": ["booking_value", "priced_bookings", "average_booking_value", "orders_confirmed"],
    "documents": ["documents_used", "document_excerpts"],
}
SECTIONS = {
    "crm": [
        _section("Leads by stage", _table_item("crm_stages")),
        _section("Conversations by channel", _table_item("channels")),
        _section("Who sent messages", _table_item("replies")),
        _section("When customers write", _grid_item("customer_inquiry_hours")),
        _section("Customer questions", {"kind": "questions"}),
        _section("Trial lessons", _metrics_item(prefix="trial_"), _grid_item("trial_booked_slots")),
        _section("Documents used", {"kind": "documents"}),
    ],
    "bookings": [
        _section("Bookings by status", _table_item("booking_status")),
        _section("Most booked", _table_item("booking_services")),
        _section("When customers book", _grid_item("booking_created_hours")),
        _section("Coming up", _table_item("upcoming")),
        _section("Trial lessons", _metrics_item(prefix="trial_"), _grid_item("trial_booked_slots")),
        _section("Interest seen in chats", _metrics_item(["booking_interest_expressed", "booking_interest_requested"]),
                 _grid_item("booking_interest_hours")),
        _section("Confirmed by your system", _metrics_item([
            "business_actions_confirmed", "booking_confirmed", "registration_confirmed", "business_intent",
            "business_requested", "business_failed", "business_cancelled", "business_rescheduled"])),
    ],
    "sales": [
        _section("Value by package", _table_item("sales_by_package")),
        _section("Value by week", _table_item("sales_by_week")),
        _section("Not included", _metrics_item(["unpriced_bookings", "revenue"])),
    ],
    "documents": [_section("Documents", {"kind": "documents"})],
}


def build_layout(report_type):
    return {"type": report_type, "title": TITLES[report_type], "cards": list(CARDS[report_type]),
            "sections": [dict(section, items=[dict(item) for item in section["items"]])
                         for section in SECTIONS[report_type]]}


# --- tables -------------------------------------------------------------------------------

def _table(key, label, columns, rows, source, *, money=(), newest=False):
    kept = rows[-MAX_TABLE_ROWS:] if newest else rows[:MAX_TABLE_ROWS]
    return {"key": key, "label": label, "columns": list(columns), "rows": kept,
            "money_columns": list(money), "available": bool(source["available"]),
            "truncated": len(rows) > MAX_TABLE_ROWS or bool(source.get("truncated"))}


def _utc(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _readable(value):
    """The UTC moment of a timestamp string, or None when it is missing or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        return _utc(value)
    except ValueError:
        return None


def _when(value, tz):
    local = _utc(value).astimezone(tz)
    return f"{local:%a} {local.day} {local:%b} {local:%H:%M}"


def _people(rows):
    return sum(row.get("party_size") if type(row.get("party_size")) is int else 1 for row in rows)


def _name(row):
    return row.get("service_name") or "Unnamed"


def crm_tables(metrics):
    """Leads by stage, channels and senders, read from the metrics already in the snapshot.
    A table is unavailable (unknown, not empty) when the metrics it comes from could not be read."""
    by_key = {item["key"]: item for item in metrics}

    def readable(key):
        return {"available": key in by_key and by_key[key].get("status") != "unavailable"}

    stages = [[item["key"][len("crm_status_"):], item["value"]] for item in metrics if item["key"].startswith("crm_status_")]
    channels = [[item["key"][len("channel_"):], item["value"]] for item in metrics
                if item["key"].startswith("channel_") and item["key"] != "channel_mix"]
    replies = [[by_key[key]["label"], by_key[key]["value"]] for key in
               ("customer_messages", "bot_messages", "staff_messages", "unattributed_messages") if key in by_key]
    channels_read = {"available": "channel_mix" not in by_key}  # channel_mix only appears when unreadable
    return [_table("crm_stages", "Leads by stage", ["Stage", "Leads"], stages, readable("crm_leads")),
            _table("channels", "Conversations by channel", ["Channel", "Conversations"], channels, channels_read),
            _table("replies", "Who sent messages", ["Sender", "Messages"], replies, readable("customer_messages"))]


def booking_metrics(metric, bookings):
    counts = Counter(row.get("status") for row in bookings["rows"])
    return [metric("bookings_created", "Bookings made in the period", len(bookings["rows"]), "service_bookings", bookings),
            *(metric(f"bookings_{status}", label, counts[status], "service_bookings", bookings)
              for status, label in METRIC_LABELS.items())]


def booking_tables(bookings, upcoming, tz):
    rows = bookings["rows"]
    by_status = [[label, sum(row.get("status") == status for row in rows),
                  _people([row for row in rows if row.get("status") == status])]
                 for status, label in STATUS_LABELS.items()]
    grouped = defaultdict(list)
    for row in rows:
        grouped[_name(row)].append(row)
    services = sorted(([name, len(items), _people(items)] for name, items in grouped.items()),
                      key=lambda item: (-item[1], item[0]))
    soon = sorted((row for row in upcoming["rows"] if _readable(row.get("scheduled_for"))),
                  key=lambda row: _readable(row["scheduled_for"]))
    coming = [[_when(row["scheduled_for"], tz), _name(row), _people([row]), STATUS_LABELS.get(row.get("status"), "Unknown")]
              for row in soon]
    return [_table("booking_status", "Bookings by status", ["Status", "Bookings", "People"], by_status, bookings),
            _table("booking_services", "Most booked", ["Service", "Bookings", "People"], services, bookings),
            _table("upcoming", f"Coming up in the next {UPCOMING_DAYS} days", ["When", "Service", "People", "Status"],
                   coming, upcoming)]


def _priced(bookings):
    return [row for row in bookings["rows"]
            if row.get("status") in VALUE_STATUSES and type(row.get("price_micro_myr")) is int]


def _money(item):
    return dict(item, unit="micro_myr")


def sales_metrics(metric, bookings, events, records):
    valued = [row for row in bookings["rows"] if row.get("status") in VALUE_STATUSES]
    priced = _priced(bookings)
    total = sum(row["price_micro_myr"] for row in priced)
    average = _money(metric("average_booking_value", "Average booking value",
                            total // len(priced) if priced else None, "service_bookings", bookings))
    if bookings["available"] and not priced:
        average = dict(average, status="unavailable", reason="No priced bookings in this period.")
    orders = {row.get("record_id") for row in records if row.get("action_type") == "order"
              and row.get("status") in VALUE_STATUSES and row.get("source") == "business_service"}
    return [_money(metric("booking_value", "Booking value (confirmed and completed bookings)", total,
                          "service_bookings", bookings)),
            metric("priced_bookings", "Bookings with a price", len(priced), "service_bookings", bookings),
            average,
            metric("unpriced_bookings", "Confirmed bookings without a price (no price or on quote)",
                   len(valued) - len(priced), "service_bookings", bookings),
            metric("orders_confirmed", "Orders confirmed by your system", len(orders), "business_events", events)]


def sales_tables(bookings, tz):
    by_package, by_week = defaultdict(list), defaultdict(list)
    for row in _priced(bookings):
        by_package[_name(row)].append(row)
        moment = _readable(row.get("created_at"))
        if moment is None:
            continue  # counted in the package table and the totals, but has no week
        local = moment.astimezone(tz).date()
        by_week[(local - timedelta(days=local.weekday())).isoformat()].append(row)

    def totals(items):
        return [len(items), sum(row["price_micro_myr"] for row in items)]

    packages = sorted(([name, *totals(items)] for name, items in by_package.items()), key=lambda item: (-item[2], item[0]))
    weeks = sorted([week, *totals(items)] for week, items in by_week.items())
    return [_table("sales_by_package", "Value by package", ["Package", "Bookings", "Value"], packages, bookings, money=[2]),
            _table("sales_by_week", "Value by week (weeks start on Monday)", ["Week starting", "Bookings", "Value"],
                   weeks, bookings, money=[2], newest=True)]
