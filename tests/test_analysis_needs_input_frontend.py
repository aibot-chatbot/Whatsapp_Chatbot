"""A report that needs more detail can be answered in one step on the Analysis page.

Production, 2026-10-03: five requests ("Generate CRM Report", "Generate booking report")
stopped at "Needs more detail" and the page offered nothing but "send a new request", which
asked the same question again. Seam: the page source, plus the script's pure helpers run in
Node (the pure:start block), as tests/test_bookings_frontend.py does for bookings.js.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

JS = (Path(__file__).resolve().parents[1] / "frontend" / "assets" / "js" / "analysis.js").read_text(encoding="utf-8")
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


@pytest.mark.parametrize("choice,expected", [
    ("last_30", {"period_start": "2026-09-05", "period_end": "2026-10-05"}),
    ("last_7", {"period_start": "2026-09-28", "period_end": "2026-10-05"}),
    ("this_month", {"period_start": "2026-10-01", "period_end": "2026-10-05"}),
    ("last_month", {"period_start": "2026-09-01", "period_end": "2026-10-01"}),
])
def test_each_period_choice_becomes_malaysia_dates_with_an_exclusive_end(choice, expected):
    assert _run(f'reportPeriod("{choice}", "2026-10-04")') == expected


def test_last_month_in_january_is_last_december():
    assert _run('reportPeriod("last_month", "2027-01-15")') == {"period_start": "2026-12-01", "period_end": "2027-01-01"}


@pytest.mark.parametrize("text,kind", [
    ("Generate booking report", "business"),
    ("Sales report for last month", "business"),
    ("Generate CRM Report", "operations"),
    ("Analyze common customer questions", "operations"),
])
def test_the_report_type_starts_on_a_sensible_guess(text, kind):
    assert _run(f"guessKind({json.dumps(text)})") == kind


def test_the_answer_is_sent_as_a_complete_request_spec_on_the_same_endpoint():
    assert "request_spec: {kind" in JS and "reportPeriod(" in JS
    assert '"Needs more detail"' in JS and "Send a new request with the period and topic." not in JS
