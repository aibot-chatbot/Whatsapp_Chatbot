"""Read real PDF/XLSX bytes back; no network, credentials, or model calls."""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
import unicodedata
import zipfile

import pytest

from app.services import analysis_export_service as service
from app.services.analysis_report_service import AnalysisReportError


@pytest.fixture
def report():
    snapshot = {
        "schema_version": 1,
        "scope": {"company_id": 28, "chatbot_id": 7, "bot_name": "餐厅 Bot", "kind": "business",
                  "timezone": "Asia/Kuala_Lumpur", "period_start": "2026-09-01", "period_end": "2026-09-07"},
        "captured_at": "2026-09-08T00:00:00+00:00",
        "industry": {"id": "restaurant", "name": "Restaurant", "confirmed": True, "version": "1.0.0"},
        "role": {"business_description": "Family dining"},
        "sources": {"business_events": {"available": True, "row_count": 1, "truncated": False, "error_code": None},
                    "messages": {"available": False, "row_count": None, "truncated": False, "error_code": "read_failed"}},
        "metrics": [{"key": "booking_confirmed", "label": "Confirmed bookings", "value": 1,
                     "status": "available", "source": "business_events"},
                    {"key": "revenue", "label": "Revenue", "value": None, "status": "unavailable", "source": "payments"}],
        "records": [{"id": 3, "action_type": "booking", "status": "confirmed", "record_id": "record-1",
                     "source": "business_service", "conversation_id": 99, "evidence_message_ids": [44],
                     "occurred_at": "2026-09-02T05:00:00Z"}],
        "documents": [{"file_id": 55, "name": "菜单.pdf", "status": "available", "truncated": False,
                       "excerpts": [{"chunk_id": 88, "text": "营业时间 9am 至 9pm"}]}],
        "limitations": ["Payments source is not connected.", "Messages could not be read."],
        "coverage": "partial",
    }
    sign(snapshot)
    return {"status": "partial", "snapshot": snapshot, "narrative": "预约报告\nOne verified booking.\n\nRevenue is unavailable.", "sections": []}


def sign(snapshot):
    snapshot.pop("snapshot_sha256", None)
    text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    snapshot["snapshot_sha256"] = hashlib.sha256(text.encode()).hexdigest()


def test_json_retains_exact_snapshot_and_unknown_values(report):
    result = service.export_report(report, "json")
    restored = json.loads(result["content"])
    assert restored["snapshot"] == report["snapshot"]
    assert restored["snapshot"]["metrics"][1]["value"] is None
    assert restored["status"] == "partial"
    assert result["content_type"] == "application/json; charset=utf-8"
    assert result["filename"].endswith(".json")


def test_xlsx_is_real_workbook_with_same_metrics_and_evidence(report):
    from openpyxl import load_workbook
    result = service.export_report(report, "xlsx")
    assert zipfile.is_zipfile(BytesIO(result["content"]))
    workbook = load_workbook(BytesIO(result["content"]), data_only=False)
    assert workbook["Metrics"]["C2"].value == 1
    assert workbook["Metrics"]["C3"].value == "Unavailable"
    assert workbook["Report"]["B2"].value == "partial"
    assert workbook["Business records"]["F2"].value == 99
    assert workbook["Business records"]["G2"].value == "[44]"
    assert workbook["Documents"]["B2"].value == "菜单.pdf"
    assert workbook["Documents"]["E2"].value == "[88]"
    assert result["content_type"].endswith("spreadsheetml.sheet")
    assert result["filename"].endswith(".xlsx")


@pytest.mark.parametrize("payload", ["=HYPERLINK(\"https://evil.invalid\",\"click\")", "+CMD|' /C calc'!A0", "@SUM(1+1)", "-1+2"])
def test_xlsx_formula_injection_remains_literal_text(report, payload):
    from openpyxl import load_workbook
    report["narrative"] = payload
    result = service.export_report(report, "xlsx")
    workbook = load_workbook(BytesIO(result["content"]), data_only=False)
    cell = workbook["Commentary"]["A2"]
    assert cell.value == payload
    assert cell.data_type == "s"
    assert not workbook._external_links


def test_pdf_is_real_document_with_readable_cjk_and_snapshot(report):
    import pymupdf
    result = service.export_report(report, "pdf")
    assert result["content"].startswith(b"%PDF")
    with pymupdf.open(stream=result["content"], filetype="pdf") as document:
        text = unicodedata.normalize("NFKC", " ".join(" ".join(page.get_text() for page in document).split()))
        assert "Partial report" in text
        assert "Confirmed bookings" in text
        assert "Unavailable" in text
        assert "预约报告" in text
        assert "餐厅" in text
        assert "55" in text and "88" in text
        assert not any(page.get_links() for page in document)


def test_pdf_paginates_long_report_without_losing_end(report):
    import pymupdf
    report["narrative"] = ("Administrative operational findings. " * 18 + "\n\n") * 75 + "END OF REPORT"
    result = service.export_report(report, "pdf")
    with pymupdf.open(stream=result["content"], filetype="pdf") as document:
        assert len(document) > 1
        text = "\n".join(page.get_text() for page in document)
        assert "END OF REPORT" in text


def test_pdf_escapes_model_html_and_does_not_load_remote_resources(report):
    import pymupdf
    report["narrative"] = '<img src="https://evil.invalid/secret"><script>secret()</script>'
    result = service.export_report(report, "pdf")
    with pymupdf.open(stream=result["content"], filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)
        assert "<img" in text and "<script>" in text
        assert not any(page.get_images() for page in document)


@pytest.mark.parametrize("state", ["queued", "running", "needs_input", "needs_review", "failed"])
def test_nonfinal_reports_cannot_export(report, state):
    report["status"] = state
    with pytest.raises(AnalysisReportError) as error:
        service.export_report(report, "json")
    assert error.value.code == "report_not_ready"


def test_export_rejects_tampered_snapshot(report):
    report["snapshot"]["metrics"][0]["value"] = 100000
    with pytest.raises(AnalysisReportError) as error:
        service.export_report(report, "json")
    assert error.value.code == "snapshot_integrity_error"


def test_partial_snapshot_cannot_be_downloaded_as_complete(report):
    report["status"] = "complete"
    with pytest.raises(AnalysisReportError) as error:
        service.export_report(report, "json")
    assert error.value.code == "report_coverage_mismatch"


def test_export_does_not_mutate_snapshot_and_uses_server_filename(report):
    before = deepcopy(report)
    report["snapshot"]["scope"]["bot_name"] = "../../secret/evil.pdf"
    sign(report["snapshot"])
    result = service.export_report(report, "json")
    assert result["filename"].startswith("bot-7-report-20260908-")
    assert ".." not in result["filename"] and "/" not in result["filename"]
    original = service.export_report(before, "json")
    assert json.loads(original["content"])["snapshot"] == before["snapshot"]


def test_facts_only_partial_exports_keep_billing_review_notice(report):
    import pymupdf
    from openpyxl import load_workbook
    report.update(narrative="", sections=[], analysis_status="needs_review",
                  limitations=["AI analysis could not be confirmed. Facts are available; billing needs review."])
    restored = json.loads(service.export_report(report, "json")["content"])
    assert restored["analysis_status"] == "needs_review"
    assert restored["snapshot"] == report["snapshot"]
    workbook = load_workbook(BytesIO(service.export_report(report, "xlsx")["content"]))
    values = " ".join(str(cell.value) for sheet in workbook for row in sheet for cell in row)
    assert "needs_review" in values and "billing needs review" in values
    with pymupdf.open(stream=service.export_report(report, "pdf")["content"], filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text() for page in document).split())
        assert "billing needs review" in text and "Partial report" in text


def test_question_evidence_survives_all_export_formats(report):
    import pymupdf
    from openpyxl import load_workbook
    report["snapshot"]["customer_questions"] = {"excerpts": [{"message_id": 901, "conversation_id": 99,
        "text": "Can I book a table?", "created_at": "2026-09-02T05:00:00Z", "truncated": False}]}
    sign(report["snapshot"])
    restored = json.loads(service.export_report(report, "json")["content"])
    assert restored["snapshot"]["customer_questions"] == report["snapshot"]["customer_questions"]
    workbook = load_workbook(BytesIO(service.export_report(report, "xlsx")["content"]))
    assert workbook["Customer question samples"]["A2"].value == 901
    assert workbook["Customer question samples"]["D2"].value == "Can I book a table?"
    with pymupdf.open(stream=service.export_report(report, "pdf")["content"], filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text() for page in document).split())
        assert "Message 901; conversation 99" in text and "Can I book a table?" in text


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def grid(key, label, status="available"):
    matrix = None
    if status != "unavailable":
        matrix = [[0] * 24 for _ in DAYS]
        matrix[1][9], matrix[6][0] = 3, 1
    return {"key": key, "label": label, "source": "messages", "timezone": "Asia/Kuala_Lumpur", "days": DAYS,
            "note": "Timestamps only.", "status": status, "matrix": matrix,
            "total": 4 if matrix else None, "unreadable_count": 0 if matrix else None}


@pytest.fixture
def grids(report):
    report["snapshot"]["distributions"] = [
        grid("customer_inquiry_hours", "Customer inquiry times (local day and hour)"),
        grid("trial_booked_slots", "When booked trial sessions take place", "unavailable")]
    sign(report["snapshot"])
    return report


def test_activity_grids_are_exported_as_day_by_hour_rows_in_xlsx(grids):
    from openpyxl import load_workbook
    workbook = load_workbook(BytesIO(service.export_report(grids, "xlsx")["content"]))
    rows = list(workbook["Activity grids"].iter_rows(values_only=True))
    header = rows[0]
    assert header[:4] == ("Grid", "Timezone", "Coverage", "Day") and header[4] == "00" and header[27] == "23"
    tuesday = next(row for row in rows if row[0].startswith("Customer inquiry") and row[3] == "Tue")
    assert tuesday[4 + 9] == 3 and tuesday[-1] == 3
    unavailable = next(row for row in rows if row[0].startswith("When booked"))
    assert unavailable[2] == "unavailable" and "not zero" in unavailable[3]


def test_activity_grids_are_readable_in_pdf(grids):
    import pymupdf
    with pymupdf.open(stream=service.export_report(grids, "pdf")["content"], filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text() for page in document).split())
    assert "Customer inquiry times" in text and "Asia/Kuala_Lumpur" in text and "Tue" in text
    assert "When booked trial sessions take place" in text and "unknown, not zero" in text


def test_snapshots_without_grids_still_export(report):
    from openpyxl import load_workbook
    workbook = load_workbook(BytesIO(service.export_report(report, "xlsx")["content"]))
    assert list(workbook["Activity grids"].iter_rows(values_only=True))[1:] == []
    assert service.export_report(report, "pdf")["content"].startswith(b"%PDF")


from app.services import analysis_report_types as report_types  # noqa: E402


def typed(report, report_type, metrics=(), tables=()):
    snapshot = report["snapshot"]
    snapshot["scope"]["report_type"] = report_type
    snapshot["layout"] = report_types.build_layout(report_type)
    snapshot["metrics"] += list(metrics)
    snapshot["tables"] = list(tables)
    sign(snapshot)
    return report


SALES_TABLE = {"key": "sales_by_package", "label": "Value by package", "columns": ["Package", "Bookings", "Value"],
               "rows": [["Set lunch", 2, 70_000_000]], "money_columns": [2], "available": True, "truncated": False}
CRM_TABLE = {"key": "crm_stages", "label": "Leads by stage", "columns": ["Stage", "Leads"],
             "rows": [["won", 1]], "money_columns": [], "available": True, "truncated": False}
VALUE = {"key": "booking_value", "label": "Booking value", "value": 70_000_000, "unit": "micro_myr",
         "status": "available", "source": "service_bookings"}


def pdf_text(result):
    import pymupdf
    with pymupdf.open(stream=result["content"], filetype="pdf") as document:
        return unicodedata.normalize("NFKC", "".join(page.get_text() for page in document))


def sheet_names(result):
    from openpyxl import load_workbook
    return load_workbook(BytesIO(result["content"])).sheetnames


def test_a_sales_pdf_has_its_own_title_sections_and_ringgit_values(report):
    text = pdf_text(service.export_report(typed(report, "sales", [VALUE], [SALES_TABLE]), "pdf"))

    assert "Sales report" in text and "Key numbers" in text and "Value by package" in text
    assert "RM 70.00" in text and "Set lunch" in text
    assert "Leads by stage" not in text


def test_a_crm_pdf_differs_from_a_sales_pdf(report):
    crm = pdf_text(service.export_report(typed(deepcopy(report), "crm", [], [CRM_TABLE]), "pdf"))
    sales = pdf_text(service.export_report(typed(deepcopy(report), "sales", [VALUE], [SALES_TABLE]), "pdf"))

    assert "Conversations and CRM report" in crm and "Leads by stage" in crm
    assert "Value by package" not in crm and "Leads by stage" not in sales
    assert "Key numbers" not in crm  # none of the CRM headline numbers are in this snapshot, so no empty table


def test_each_type_gets_its_own_workbook_sheets(report):
    sales = sheet_names(service.export_report(typed(deepcopy(report), "sales", [VALUE], [SALES_TABLE]), "xlsx"))
    crm = sheet_names(service.export_report(typed(deepcopy(report), "crm", [], [CRM_TABLE]), "xlsx"))

    assert "Key numbers" in sales and "Value by package" in sales and "Value by package" not in crm
    assert "Leads by stage" in crm and sales != crm


def test_money_in_a_workbook_table_is_written_in_ringgit(report):
    from openpyxl import load_workbook
    result = service.export_report(typed(report, "sales", [VALUE], [SALES_TABLE]), "xlsx")
    rows = list(load_workbook(BytesIO(result["content"]))["Value by package"].values)

    assert rows[0] == ("Package", "Bookings", "Value") and rows[1] == ("Set lunch", 2, "RM 70.00")


def test_a_report_made_before_layouts_keeps_the_original_format(report):
    text = pdf_text(service.export_report(report, "pdf"))

    assert "Verified metrics" in text and "Key numbers" not in text
    assert "Metrics" in sheet_names(service.export_report(report, "xlsx"))
