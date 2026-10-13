"""Each Analysis report type has its own layout and its own numbers.

Seam: app/services/analysis_report_types.py, pure functions over rows the report service
has already scoped and cleaned. Money is integer micro-MYR (RM 1 = 1,000,000).
"""

from datetime import timedelta, timezone

import pytest

from app.services import analysis_report_types as types

MYT = timezone(timedelta(hours=8))
SOURCE = {"available": True, "truncated": False}


def metric(key, label, value, name, source):
    return {"key": key, "label": label, "value": value if source["available"] else None,
            "status": "available" if source["available"] else "unavailable", "source": name}


def booking(status, *, price=None, name="Haircut", people=1, created="2026-09-02T02:00:00+00:00", when=None):
    return {"id": 1, "status": status, "service_name": name, "party_size": people, "price_micro_myr": price,
            "created_at": created, "scheduled_for": when or created}


@pytest.mark.parametrize("spec,text,expected", [
    ({"kind": "operations"}, "Generate CRM Report", "crm"),
    ({"kind": "business"}, "Generate booking report", "bookings"),
    ({"kind": "business"}, "Sales report for September", "sales"),
    ({"kind": "business"}, "Laporan jualan bulan lepas", "sales"),
    ({"kind": "documents"}, "Summarize the price list", "documents"),
    ({"kind": "business", "report_type": "sales"}, "anything", "sales"),
    ({"kind": "business"}, "Wholesale orders this month", "bookings"),
])
def test_the_report_type_comes_from_the_choice_or_else_the_request(spec, text, expected):
    assert types.resolve_report_type(spec, text) == expected


def test_every_type_has_its_own_title_cards_and_sections():
    layouts = {name: types.build_layout(name) for name in types.REPORT_TYPES}

    assert len({layout["title"] for layout in layouts.values()}) == 4
    assert len({tuple(layout["cards"]) for layout in layouts.values()}) == 4
    assert len({tuple(s["title"] for s in layout["sections"]) for layout in layouts.values()}) == 4


def test_bookings_are_counted_by_status_with_people_and_most_booked_first():
    rows = [booking("confirmed", people=2), booking("requested"), booking("cancelled", name="Colour"),
            booking("confirmed", name="Colour", people=3), booking("confirmed", people=1)]
    source = dict(SOURCE, rows=rows)

    metrics = {m["key"]: m["value"] for m in types.booking_metrics(metric, source)}
    tables = {t["key"]: t for t in types.booking_tables(source, dict(SOURCE, rows=[]), MYT)}

    assert metrics == {"bookings_created": 5, "bookings_requested": 1, "bookings_confirmed": 3,
                       "bookings_completed": 0, "bookings_cancelled": 1}
    assert tables["booking_status"]["rows"][1] == ["Confirmed", 3, 6]
    assert tables["booking_services"]["rows"][0] == ["Haircut", 3, 4]


def test_coming_up_lists_times_in_malaysia_time_soonest_first():
    upcoming = dict(SOURCE, rows=[booking("confirmed", when="2026-10-06T03:00:00+00:00", name="Colour"),
                                  booking("requested", when="2026-10-05T02:00:00+00:00", people=2)])

    table = {t["key"]: t for t in types.booking_tables(dict(SOURCE, rows=[]), upcoming, MYT)}["upcoming"]

    assert table["rows"] == [["Mon 5 Oct 10:00", "Haircut", 2, "Waiting for your team"],
                             ["Tue 6 Oct 11:00", "Colour", 1, "Confirmed"]]


def test_sales_adds_only_priced_confirmed_and_completed_bookings():
    rows = [booking("confirmed", price=35_000_000), booking("completed", price=45_000_000, name="Colour"),
            booking("requested", price=99_000_000), booking("cancelled", price=99_000_000),
            booking("confirmed", price=None)]
    events = dict(SOURCE, rows=[])
    records = [{"action_type": "order", "status": "confirmed", "source": "business_service", "record_id": "A1"},
               {"action_type": "order", "status": "requested", "source": "observation", "record_id": None}]

    metrics = {m["key"]: m for m in types.sales_metrics(metric, dict(SOURCE, rows=rows), events, records)}

    assert metrics["booking_value"]["value"] == 80_000_000 and metrics["booking_value"]["unit"] == "micro_myr"
    assert metrics["priced_bookings"]["value"] == 2
    assert metrics["average_booking_value"]["value"] == 40_000_000
    assert metrics["unpriced_bookings"]["value"] == 1
    assert metrics["orders_confirmed"]["value"] == 1


def test_an_average_with_nothing_priced_is_unavailable_not_zero():
    metrics = {m["key"]: m for m in types.sales_metrics(metric, dict(SOURCE, rows=[booking("confirmed")]),
                                                         dict(SOURCE, rows=[]), [])}

    assert metrics["average_booking_value"]["value"] is None
    assert metrics["average_booking_value"]["status"] == "unavailable"


def test_sales_tables_group_value_by_package_and_by_monday_week():
    rows = [booking("confirmed", price=35_000_000, created="2026-09-01T02:00:00+00:00"),   # Tue 1 Sep
            booking("confirmed", price=35_000_000, created="2026-09-06T15:30:00+00:00"),   # Sun 6 Sep 23:30 MYT
            booking("completed", price=45_000_000, name="Colour", created="2026-09-07T02:00:00+00:00")]  # Mon 7 Sep

    tables = {t["key"]: t for t in types.sales_tables(dict(SOURCE, rows=rows), MYT)}

    assert tables["sales_by_package"]["rows"] == [["Haircut", 2, 70_000_000], ["Colour", 1, 45_000_000]]
    assert tables["sales_by_week"]["rows"] == [["2026-08-31", 2, 70_000_000], ["2026-09-07", 1, 45_000_000]]
    assert tables["sales_by_week"]["money_columns"] == [2]


def test_crm_tables_are_read_from_the_frozen_metrics():
    metrics = [{"key": "crm_status_new", "value": 4}, {"key": "crm_status_won", "value": 1},
               {"key": "channel_whatsapp", "value": 7}, {"key": "channel_mix", "value": None},
               {"key": "customer_messages", "label": "Customer messages", "value": 30}]

    tables = {t["key"]: t for t in types.crm_tables(metrics)}

    assert tables["crm_stages"]["rows"] == [["new", 4], ["won", 1]]
    assert tables["channels"]["rows"] == [["whatsapp", 7]]
    assert tables["replies"]["rows"] == [["Customer messages", 30]]


def test_an_unreadable_source_makes_its_tables_unavailable_not_empty():
    tables = types.booking_tables({"available": False, "truncated": False, "rows": []},
                                  {"available": False, "truncated": False, "rows": []}, MYT)

    assert all(table["available"] is False for table in tables)


def test_a_long_sales_period_keeps_the_newest_weeks():
    rows = [booking("confirmed", price=10_000_000, created=f"2026-{month:02d}-{day:02d}T02:00:00+00:00")
            for month in range(1, 9) for day in (5, 20) for _ in range(1)]
    rows += [booking("confirmed", price=10_000_000, created=f"2026-{month:02d}-12T02:00:00+00:00") for month in range(1, 9)]

    weeks = {t["key"]: t for t in types.sales_tables(dict(SOURCE, rows=rows), MYT)}["sales_by_week"]

    assert len(weeks["rows"]) == types.MAX_TABLE_ROWS and weeks["truncated"] is True
    assert weeks["rows"][-1][0] == "2026-08-17"  # the newest week is always shown


def test_a_booking_with_an_unreadable_time_is_skipped_not_fatal():
    bad = [booking("confirmed", price=10_000_000, created=None), booking("confirmed", when="not a time")]
    upcoming = dict(SOURCE, rows=[booking("confirmed", when="not a time")])

    tables = {t["key"]: t for t in types.sales_tables(dict(SOURCE, rows=bad), MYT)
              + types.booking_tables(dict(SOURCE, rows=bad), upcoming, MYT)}

    assert tables["sales_by_week"]["rows"] == [] and tables["upcoming"]["rows"] == []


def test_crm_tables_are_unavailable_when_their_data_could_not_be_read():
    metrics = [{"key": "crm_leads", "value": None, "status": "unavailable"},
               {"key": "channel_mix", "value": None, "status": "unavailable"}]

    tables = {t["key"]: t for t in types.crm_tables(metrics)}

    assert tables["crm_stages"]["available"] is False and tables["channels"]["available"] is False
