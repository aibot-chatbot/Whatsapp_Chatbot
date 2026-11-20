"""The Analysis page draws each report type its own way, and can clear finished reports.

Seam: the page source, plus analysis-layout.js's pure helpers run in Node (the pure:start
block), as tests/test_bookings_frontend.py does for bookings.js.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.services import analysis_report_types as report_types
from tests.frontend_pages import page_source_path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
HTML = page_source_path("analysis.html").read_text(encoding="utf-8")
PAGE_JS = (FRONTEND / "assets" / "js" / "analysis.js").read_text(encoding="utf-8")
LAYOUT_JS = (FRONTEND / "assets" / "js" / "analysis-layout.js").read_text(encoding="utf-8")
NODE = shutil.which("node") or shutil.which("nodejs")


def _run(expression):
    if NODE is None:
        pytest.skip("Node.js not available")
    block = LAYOUT_JS[LAYOUT_JS.index("/* pure:start"):LAYOUT_JS.index("/* pure:end */")]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(block + f"\nconsole.log(JSON.stringify({expression}));\n")
        path = handle.name
    try:
        done = subprocess.run([NODE, path], capture_output=True, text=True, timeout=20, check=True, encoding="utf-8")
    finally:
        Path(path).unlink(missing_ok=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("micro,text", [(70_000_000, "RM 70.00"), (1_234_567_890_000, "RM 1,234,567.89"), (0, "RM 0.00")])
def test_money_reads_as_ringgit(micro, text):
    assert _run(f"formatMyr({micro})") == text


def test_a_money_column_is_ringgit_and_a_missing_value_says_so():
    table = {"money_columns": [2]}
    assert _run(f"cellValue({json.dumps(table)}, 2, 35000000)") == "RM 35.00"
    assert _run(f"cellValue({json.dumps(table)}, 1, 3)") == "3"
    assert _run(f"cellValue({json.dumps(table)}, 0, null)") == "Unavailable"


def test_sections_follow_the_frozen_layout_and_skip_what_the_report_lacks():
    snapshot = {"layout": report_types.build_layout("sales"),
                "tables": [{"key": "sales_by_week", "rows": []}, {"key": "sales_by_package", "rows": []}],
                "metrics": [{"key": "revenue", "value": None, "status": "unavailable"}]}

    sections = _run(f"layoutSections({json.dumps(snapshot)}).map(s => [s.title, s.parts.map(p => p.kind)])")

    assert sections == [["Value by package", ["table"]], ["Value by week", ["table"]], ["Not included", ["metrics"]]]


def test_a_report_without_a_layout_has_no_typed_sections():
    assert _run('layoutSections({"metrics": []})') == []


def test_the_page_loads_the_layout_script_before_its_own_and_never_writes_html():
    assert HTML.index('src="assets/js/analysis-layout.js"') < HTML.index('src="assets/js/analysis.js"')
    for script in (LAYOUT_JS, PAGE_JS):
        assert "innerHTML" not in script and "insertAdjacentHTML" not in script and "outerHTML" not in script


def test_the_report_type_picker_offers_exactly_the_server_types():
    picker = HTML[HTML.index('id="report-type"'):HTML.index("</select>", HTML.index('id="report-type"'))]
    offered = {value for value in report_types.REPORT_TYPES if f'value="{value}"' in picker}
    assert offered == set(report_types.REPORT_TYPES) and 'value=""' in picker
    assert 'id="report-period"' in HTML


def test_clearing_uses_the_hide_endpoint_for_one_report_or_all_finished_ones():
    assert 'id="clear-reports"' in HTML
    assert '"/reports/hide"' in PAGE_JS and "all_finished: true" in PAGE_JS and "report_ids: ids" in PAGE_JS
    assert "Remove from list" in PAGE_JS and "window.confirm(" in PAGE_JS
