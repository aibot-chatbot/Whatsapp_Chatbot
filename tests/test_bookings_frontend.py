"""The Bookings dashboard page: its wiring, its safety rules, and its logic run for real in Node.

Two kinds of check. Static contract tests pin the things that fail silently in a browser (a
missing script tag leaves the page on its skeleton; a mistyped element id throws on load; an
innerHTML write turns customer text into markup). The Node tests execute the page's pure block,
the same code the browser runs, against the server's own date parser.
"""

import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services import booking_service

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
HTML = (FRONTEND / "bookings.html").read_text(encoding="utf-8")
JS = (FRONTEND / "assets" / "js" / "bookings.js").read_text(encoding="utf-8")
CSS = (FRONTEND / "assets" / "css" / "bookings.css").read_text(encoding="utf-8")
SIDEBAR = (FRONTEND / "sidebar-component.js").read_text(encoding="utf-8")
NODE = shutil.which("node") or shutil.which("nodejs")
NOW = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)


# --- wiring --------------------------------------------------------------------------

def test_the_page_loads_what_every_control_room_page_needs_in_order():
    order = [HTML.index(marker) for marker in (
        "assets/js/shared-ui.js", "assets/js/kw-a11y.js", "assets/js/auth.js",
        "requireLogin();", "sidebar-component.js")]

    assert order == sorted(order)
    assert "<chatbot-sidebar></chatbot-sidebar>" in HTML


def test_resilient_load_is_loaded_before_the_page_script():
    # Without it every read throws a ReferenceError and the page sits on its skeleton forever.
    assert HTML.index("assets/js/resilient-load.js") < HTML.index("assets/js/bookings.js")


def test_page_css_loads_last_and_no_third_party_script_is_pulled_in():
    stylesheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', HTML)

    assert stylesheets[-1] == "assets/css/bookings.css"
    assert stylesheets.index("assets/css/dashboard-control-room.css") < len(stylesheets) - 1
    assert not re.search(r"<script[^>]+src=\"https?://", HTML), \
        "external scripts need integrity pins; the sidebar already loads its own pinned icons"


def test_modals_sit_outside_main_and_actions_stay_out_of_the_header_slot():
    assert HTML.index("</main>") < HTML.index('id="bk-edit-modal"') < HTML.index('id="bk-confirm-modal"')
    assert "kw-header-aside" not in HTML, "the account menu covers the header's right slot"
    assert HTML.index('id="bk-download"') > HTML.index('class="kw-toolbar')


def test_every_element_the_script_looks_up_exists():
    used = set(re.findall(r"\$\(\"([a-z0-9-]+)\"\)", JS))
    declared = set(re.findall(r'\bid="([a-z0-9-]+)"', HTML))

    assert used, "no element lookups found"
    assert used <= declared, sorted(used - declared)


def test_every_dialog_is_labelled_and_modal():
    dialogs = re.findall(r'<div class="kw-modal[^"]*" ([^>]*)>', HTML)

    assert len(dialogs) == 3  # edit booking, confirm cancel, package editor
    for attributes in dialogs:
        assert 'role="dialog"' in attributes and 'aria-modal="true"' in attributes and "aria-labelledby=" in attributes


def test_the_status_line_and_notes_are_polite_live_regions():
    assert re.search(r'id="bk-status"[^>]*role="status"[^>]*aria-live="polite"', HTML)
    assert re.search(r'id="bk-intake-note"[^>]*role="status"[^>]*aria-live="polite"', HTML)
    assert re.search(r'id="bk-error"[^>]*role="alert"', HTML)


def test_the_sidebar_links_to_the_page_keeping_the_bot_context():
    assert 'href="bookings.html${botQuery}"' in SIDEBAR


def test_the_owner_email_link_points_at_a_real_page():
    assert "/bookings.html" in Path(booking_service.__file__).read_text(encoding="utf-8")
    assert (FRONTEND / "bookings.html").is_file()


# --- safety --------------------------------------------------------------------------

@pytest.mark.parametrize("forbidden", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                                       "eval(", "new Function", "setTimeout(\"", "javascript:"])
def test_customer_text_can_never_become_markup(forbidden):
    assert forbidden not in JS


def test_the_script_only_talks_to_the_bookings_and_bots_apis():
    # "/api/bookings/" is the item route; the id is appended in code.
    paths = {path.rstrip("/") for path in re.findall(r"\"(/api/[^\"?]*)", JS)}

    assert paths == {"/api/bookings", "/api/bookings/settings", "/api/bookings/export.csv", "/api/bots"}


def test_writes_are_single_shot_and_guarded_and_reads_may_retry():
    assert set(re.findall(r'send\("(PATCH|PUT|POST|DELETE)"', JS)) == {"PATCH", "PUT"}
    assert "expected_version: booking.version" in JS
    assert "resilientLoad.loadJson(" in JS
    assert not re.search(r"loadJson\([^)]*method", JS), "mutations must not go through the retrying reader"


def test_the_tenant_is_never_sent_from_the_browser():
    assert "company_id" not in JS and "company_id" not in HTML


def test_the_stylesheet_uses_the_shared_tokens_only():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS), "no raw hex colours"
    assert "!important" not in CSS
    assert "var(--control-" in CSS


# --- the page's pure logic, run in Node ----------------------------------------------

def _pure_block():
    start = JS.index("/* pure:start")
    end = JS.index("/* pure:end */")
    return JS[start:end]


def _run(expression):
    if NODE is None:
        pytest.skip("Node.js not available")
    script = _pure_block() + f"\nconsole.log(JSON.stringify({expression}));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        path = handle.name
    try:
        done = subprocess.run([NODE, path], capture_output=True, text=True, timeout=20, check=True, encoding="utf-8")
    finally:
        Path(path).unlink(missing_ok=True)
    return json.loads(done.stdout)


def _squash(text):
    return " ".join(text.split())  # newer ICU puts a narrow no-break space before am/pm


def test_times_show_in_malaysia_time():
    assert _squash(_run('formatWhen("2026-10-05T11:00:00+00:00")')) == "5 Oct 2026, 7:00 pm"
    assert _squash(_run('formatWhen("2026-10-05T17:30:00+00:00")')) == "6 Oct 2026, 1:30 am"
    assert _run('formatWhen("not a date")') == "" and _run("formatWhen(null)") == ""


@pytest.mark.parametrize("iso,local", [
    ("2026-10-05T11:00:00+00:00", "2026-10-05T19:00"),
    ("2026-10-05T17:30:00+00:00", "2026-10-06T01:30"),
    ("2026-12-31T16:00:00+00:00", "2027-01-01T00:00"),
    ("garbage", ""), (None, "")])
def test_the_edit_field_value_is_the_malaysia_wall_clock(iso, local):
    assert _run(f"toLocalInput({json.dumps(iso)})") == local


def test_what_the_form_sends_is_the_instant_the_server_reads_back():
    iso = "2026-10-05T11:00:00+00:00"
    local = _run(f'toLocalInput("{iso}")')

    parsed = booking_service.parse_when(local, NOW, bounded=False)

    assert parsed == datetime.fromisoformat(iso)


def test_unchanged_form_sends_nothing():
    booking = {"customer_name": "Ada", "service_name": "Dinner", "notes": None, "kind": "reservation",
               "party_size": 4, "scheduled_for": "2026-10-05T11:00:00+00:00"}
    form = {"customer_name": " Ada ", "service_name": "Dinner", "notes": "  ", "kind": "reservation",
            "party_size": "4", "scheduled_for": "2026-10-05T19:00"}

    result = _run(f"buildChanges({json.dumps(booking)}, {json.dumps(form)})")

    assert result == {"changes": {}, "errors": {}}


def test_only_the_fields_that_changed_are_sent_and_cleared_fields_become_null():
    booking = {"customer_name": "Ada", "service_name": "Dinner", "notes": "Window", "kind": "booking",
               "party_size": 4, "scheduled_for": "2026-10-05T11:00:00+00:00"}
    form = {"customer_name": "Ada", "service_name": "Lunch", "notes": "", "kind": "appointment",
            "party_size": "", "scheduled_for": ""}

    result = _run(f"buildChanges({json.dumps(booking)}, {json.dumps(form)})")

    assert result["errors"] == {}
    assert result["changes"] == {"service_name": "Lunch", "notes": None, "kind": "appointment",
                                 "party_size": None, "scheduled_for": None}


def test_a_new_time_is_sent_as_the_local_wall_clock_the_server_expects():
    booking = {"customer_name": None, "service_name": "Cut", "notes": None, "kind": "other",
               "party_size": None, "scheduled_for": None}
    form = {"customer_name": "", "service_name": "Cut", "notes": "", "kind": "other",
            "party_size": "", "scheduled_for": "2026-10-06T20:30"}

    result = _run(f"buildChanges({json.dumps(booking)}, {json.dumps(form)})")

    assert result["changes"] == {"scheduled_for": "2026-10-06T20:30"}
    assert booking_service.parse_when("2026-10-06T20:30", NOW, bounded=False) == datetime(
        2026, 10, 6, 12, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("size", ["0", "-1", "1.5", "abc", "10001", "1e3", "4 people"])
def test_a_bad_party_size_is_caught_before_any_request(size):
    booking = {"party_size": 4, "kind": "other", "scheduled_for": None}
    form = {"kind": "other", "party_size": size, "scheduled_for": ""}

    result = _run(f"buildChanges({json.dumps(booking)}, {json.dumps(form)})")

    assert "party_size" in result["errors"] and "party_size" not in result["changes"]


@pytest.mark.parametrize("size", ["1", "10000", "007"])
def test_the_party_size_bounds_match_the_server(size):
    booking = {"party_size": None, "kind": "other", "scheduled_for": None}
    form = {"kind": "other", "party_size": size, "scheduled_for": ""}

    result = _run(f"buildChanges({json.dumps(booking)}, {json.dumps(form)})")

    assert result["errors"] == {} and result["changes"]["party_size"] == int(size)
    assert booking_service.clean_party_size(int(size)) == int(size)


def test_the_actions_offered_follow_the_status_rules_the_server_enforces():
    allowed = {status: _run(f'allowedActions("{status}")') for status in booking_service.STATUSES}

    assert allowed == {"requested": ["confirm", "edit", "cancel"], "confirmed": ["complete", "edit", "cancel"],
                       "completed": [], "cancelled": []}
    for status, actions in allowed.items():
        for action, target in (("confirm", "confirmed"), ("complete", "completed"), ("cancel", "cancelled")):
            assert (action in actions) == (target in booking_service.TRANSITIONS[status]), (status, action)
        assert ("edit" in actions) == bool(booking_service.TRANSITIONS[status])


def test_unknown_statuses_and_kinds_degrade_safely():
    assert _run('statusMeta("mystery")') == {"label": "Unknown", "tone": "off"}
    assert _run('allowedActions("mystery")') == []
    assert _run('kindLabel("mystery")') == "Request"


def test_every_server_status_has_a_label_and_a_tone():
    tones = {status: _run(f'statusMeta("{status}")')["tone"] for status in booking_service.STATUSES}

    assert tones == {"requested": "review", "confirmed": "ready", "cancelled": "off", "completed": "ready"}
