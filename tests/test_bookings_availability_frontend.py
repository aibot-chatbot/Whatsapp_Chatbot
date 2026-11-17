"""The Bookings page's Packages & availability panel (Pro).

Seam: the page source, plus the script's pure helpers run in Node (the pure:start block),
the same way tests/test_bookings_frontend.py covers bookings.js.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.frontend_pages import page_source_path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
HTML = page_source_path("bookings.html").read_text(encoding="utf-8")
JS = (FRONTEND / "assets" / "js" / "bookings-availability.js").read_text(encoding="utf-8")
NODE = shutil.which("node") or shutil.which("nodejs")


def _run(expression):
    if NODE is None:
        pytest.skip("Node.js not available")
    block = JS[JS.index("/* pure:start"):JS.index("/* pure:end */")]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(block + f"\nconsole.log(JSON.stringify({expression}));\n")
        path = handle.name
    try:
        done = subprocess.run([NODE, path], capture_output=True, text=True, timeout=20, check=True, encoding="utf-8")
    finally:
        Path(path).unlink(missing_ok=True)
    return json.loads(done.stdout)


def test_the_page_has_the_panel_a_pro_lock_and_loads_its_script_after_bookings_js():
    for element in ('id="av-panel"', 'id="av-locked"', 'id="av-content"', 'id="av-package-modal"'):
        assert element in HTML
    assert "Pro plan" in HTML
    assert HTML.index('src="assets/js/bookings.js"') < HTML.index('src="assets/js/bookings-availability.js"')


def test_the_price_rules_offered_match_the_backend():
    for mode in ("none", "fixed", "per_person", "quote"):
        assert f'value="{mode}"' in HTML


def test_the_script_uses_the_availability_api_and_shows_the_lock_without_pro():
    for path in ("/api/bookings/availability?chatbot_id=", "/api/bookings/packages", "/hours",
                 "/api/bookings/closures", "/api/bookings/slots", "/api/bookings/availability/settings"):
        assert path in JS
    assert "feature_not_available" in JS


def test_customer_and_owner_text_is_never_written_as_html():
    assert "innerHTML" not in JS and "insertAdjacentHTML" not in JS and "outerHTML" not in JS


def test_open_days_become_weekly_hours_and_closed_days_are_left_out():
    rows = [{"weekday": 1, "open": True, "start": "09:00", "end": "18:00", "every": "60"},
            {"weekday": 2, "open": False, "start": "09:00", "end": "18:00", "every": "60"}]

    assert _run(f"hoursPayload({json.dumps(rows)})") == {
        "hours": [{"weekday": 1, "start": "09:00", "end": "18:00", "interval_minutes": 60}], "error": None}


def test_closing_before_opening_is_caught_before_anything_is_sent():
    rows = [{"weekday": 3, "open": True, "start": "18:00", "end": "09:00", "every": "60"}]

    result = _run(f"hoursPayload({json.dumps(rows)})")

    assert result["hours"] is None and "Wed" in result["error"]


@pytest.mark.parametrize("package,label", [
    ({"price_mode": "fixed", "price_micro_myr": 35000000}, "RM 35.00"),
    ({"price_mode": "per_person", "price_micro_myr": 10000000}, "RM 10.00 per person"),
    ({"price_mode": "quote", "price_micro_myr": None}, "Quote only"),
    ({"price_mode": "none", "price_micro_myr": None}, "No price shown"),
])
def test_each_price_rule_has_an_owner_facing_label(package, label):
    assert _run(f"priceLabel({json.dumps(package)})") == label


def test_seats_read_as_booked_out_of_total():
    assert _run('seatsLabel({"booked_seats": 1, "capacity": 2})') == "1 of 2 seats booked"


def test_a_closed_date_reads_as_the_same_calendar_day():
    assert _run('dateLabel("2026-10-20")') == "Tue 20 Oct 2026"


def test_a_picked_date_and_time_is_sent_as_malaysia_local_time():
    assert _run('apiMoment("2026-10-10T15:00")') == "2026-10-10 15:00"
