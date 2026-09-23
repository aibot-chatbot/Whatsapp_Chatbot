"""Private, in-memory exports of an already completed report snapshot.

No storage URLs or model calls are created here. The authenticated caller owns
download authorization and optional private storage of the returned bytes.
"""

from datetime import datetime
from html import escape
from io import BytesIO
import json
import re

from app.services.analysis_report_service import AnalysisReportError, validate_snapshot


FORMATS = {
    "json": "application/json; charset=utf-8",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _report(report):
    if not isinstance(report, dict) or report.get("status") not in {"complete", "partial"}:
        raise AnalysisReportError("Only complete or partial reports can be downloaded.", "report_not_ready", 409)
    snapshot = validate_snapshot(report.get("snapshot"))
    if snapshot.get("coverage") == "partial" and report["status"] != "partial":
        raise AnalysisReportError("Partial source coverage must remain visible in exports.", "report_coverage_mismatch", 409)
    narrative = report.get("narrative")
    if not isinstance(narrative, str):
        raise AnalysisReportError("Report commentary is unavailable.", "report_not_ready", 409)
    return {"status": report["status"], "snapshot": snapshot, "narrative": narrative,
            "sections": report.get("sections") or [], "analysis_status": report.get("analysis_status", "complete"),
            "limitations": report.get("limitations") or []}


def _scalar(value):
    if value is None:
        return "Unavailable"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


HOURS = [f"{hour:02d}" for hour in range(24)]
UNKNOWN_GRID = "Unavailable (unknown, not zero)"


def _grid_rows(grid):
    """Day rows of one activity grid; an unavailable grid is one explicit row, never zeros."""
    if not isinstance(grid.get("matrix"), list):
        return [[UNKNOWN_GRID]]
    return [[day, *counts, sum(counts)] for day, counts in zip(grid["days"], grid["matrix"])]


def _pdf_grids(snapshot):
    parts = []
    for grid in snapshot.get("distributions", []):
        rows = _grid_rows(grid)
        total = "" if len(rows[0]) == 1 else f" · total {escape(str(grid.get('total')))}"
        parts.append(f"<h3>{escape(grid['label'])}</h3><p>{escape(grid['timezone'])} · coverage {escape(grid['status'])}"
                     f"{total}. {escape(grid.get('note') or '')}</p>")
        if len(rows[0]) == 1:
            parts.append(f"<p>{UNKNOWN_GRID}</p>")
            continue
        parts.append('<table class="grid"><tr><th>Day</th>' + "".join(f"<th>{hour}</th>" for hour in HOURS)
                     + "<th>Total</th></tr>")
        parts.extend("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>" for row in rows)
        parts.append("</table>")
    return parts


def _pdf(report):
    import pymupdf

    snapshot = report["snapshot"]
    scope = snapshot["scope"]
    title = f"{'Partial report' if report['status'] == 'partial' else 'Report'} — {scope['bot_name']}"
    metadata = [f"Industry: {snapshot['industry']['name']}",
                f"Period: {scope.get('period_start') or 'Selected documents'} to {scope.get('period_end') or 'capture time'} (end exclusive, {scope['timezone']})",
                f"Captured: {snapshot['captured_at']}", f"Snapshot: {snapshot['snapshot_sha256']}"]
    parts = [f"<h1>{escape(title)}</h1>"]
    parts.extend(f"<p>{escape(line)}</p>" for line in metadata)
    parts.append("<h2>Verified metrics</h2><table><tr><th>Metric</th><th>Value</th><th>Coverage</th></tr>")
    for metric in snapshot["metrics"]:
        parts.append("<tr>" + "".join(f"<td>{escape(str(_scalar(value)))}</td>" for value in
                                     (metric["label"], metric["value"], metric["status"])) + "</tr>")
    parts.append("</table>")
    grids = _pdf_grids(snapshot)
    if grids:
        parts.append("<h2>Activity by day and hour</h2>")
        parts.extend(grids)
    parts.append("<h2>AI commentary</h2>")
    # Escape every byte of model/document text. Never render model HTML/images.
    parts.extend(f"<p>{escape(paragraph).replace(chr(10), '<br>')}</p>"
                 for paragraph in report["narrative"].split("\n\n"))
    parts.append("<h2>Source limitations</h2>")
    parts.extend(f"<p>{escape(item)}</p>" for item in snapshot["limitations"] + report["limitations"])
    parts.append("<h2>Sources</h2>")
    for name, source in snapshot["sources"].items():
        parts.append(f"<p>{escape(name)}: {escape(str(_scalar(source['row_count'])))} records; "
                     f"{'available' if source['available'] else 'unavailable'}; "
                     f"{'bounded' if source['truncated'] else 'not truncated'}</p>")
    for document in snapshot["documents"]:
        parts.append(f"<p>Document {document['file_id']}: {escape(document['name'])}; {escape(document['status'])}; "
                     f"chunks {escape(', '.join(str(item['chunk_id']) for item in document['excerpts']))}</p>")
    questions = snapshot.get("customer_questions", {})
    if questions.get("excerpts"):
        parts.append("<h2>Customer question samples</h2>")
        for sample in questions["excerpts"]:
            parts.append(f"<p>Message {sample['message_id']}; conversation {sample['conversation_id']}: "
                         f"{escape(sample['text'])}</p>")
    story = pymupdf.Story("<html><body>" + "".join(parts) + "</body></html>", user_css=(
        "body { font-family: sans-serif; font-size: 10pt; line-height: 1.4; } "
        "h1 { font-size: 18pt; } h2 { font-size: 13pt; margin-top: 16pt; } "
        "table { width: 100%; border-collapse: collapse; } th,td { border: 0.5pt solid #ccc; padding: 5pt; } "
        "h3 { font-size: 11pt; margin-top: 10pt; } table.grid th, table.grid td { font-size: 6pt; padding: 1pt; text-align: center; }"))
    buffer = BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    box = pymupdf.paper_rect("a4")
    try:
        for _ in range(200):
            device = writer.begin_page(box)
            more, _filled = story.place(box + (36, 36, -36, -36))
            story.draw(device)
            writer.end_page()
            if not more:
                break
        else:
            raise AnalysisReportError("PDF exceeded its page limit.", "export_too_large", 422)
    finally:
        writer.close()
    return buffer.getvalue()


def _xlsx(report):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    workbook.remove(workbook.active)
    snapshot, scope = report["snapshot"], report["snapshot"]["scope"]

    def sheet(title, headers, rows):
        target = workbook.create_sheet(title)
        target.append(headers)
        for values in rows:
            target.append([_scalar(value) for value in values])
        # Strings beginning =,+,-,@ are data, never workbook formulas. Explicit
        # cell type also preserves dates/IDs and avoids DDE/formula injection.
        for row in target:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cell.value)[:32767]
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in target[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="203E52")
        target.freeze_panes = "A2"
        target.auto_filter.ref = target.dimensions
        for column in target.columns:
            target.column_dimensions[column[0].column_letter].width = min(70, max(18, len(str(column[0].value)) + 4))
        return target

    sheet("Report", ["Field", "Value"], [
        ["Status", report["status"]], ["Bot ID", scope["chatbot_id"]], ["Bot", scope["bot_name"]],
        ["Industry", snapshot["industry"]["name"]], ["Kind", scope["kind"]],
        ["Period start", scope.get("period_start")], ["Period end (exclusive)", scope.get("period_end")],
        ["AI analysis", report["analysis_status"]],
        ["Timezone", scope["timezone"]], ["Captured", snapshot["captured_at"]],
        ["Snapshot SHA256", snapshot["snapshot_sha256"]]])
    sheet("Metrics", ["Key", "Metric", "Value", "Coverage", "Source"],
          [[item[key] for key in ("key", "label", "value", "status", "source")] for item in snapshot["metrics"]])
    sheet("Activity grids", ["Grid", "Timezone", "Coverage", "Day", *HOURS, "Day total"],
          [[grid["label"], grid["timezone"], grid["status"], *row]
           for grid in snapshot.get("distributions", []) for row in _grid_rows(grid)])
    sheet("Commentary", ["Paragraph"], [[paragraph] for paragraph in report["narrative"].split("\n\n")])
    sheet("Limitations", ["Limitation"], [[item] for item in snapshot["limitations"] + report["limitations"]])
    sheet("Sources", ["Source", "Available", "Rows", "Truncated", "Error"],
          [[name, source["available"], source["row_count"], source["truncated"], source.get("error_code")]
           for name, source in snapshot["sources"].items()])
    sheet("Business records", ["Event ID", "Type", "Status", "Record ID", "Source", "Conversation ID", "Message evidence", "Occurred"],
          [[row.get(key) for key in ("id", "action_type", "status", "record_id", "source", "conversation_id", "evidence_message_ids", "occurred_at")]
           for row in snapshot["records"]])
    sheet("Documents", ["File ID", "Name", "Coverage", "Truncated", "Chunk IDs"],
          [[row["file_id"], row["name"], row["status"], row["truncated"], [item["chunk_id"] for item in row["excerpts"]]]
           for row in snapshot["documents"]])
    sheet("Customer question samples", ["Message ID", "Conversation ID", "Received", "Text", "Truncated"],
          [[row.get(key) for key in ("message_id", "conversation_id", "created_at", "text", "truncated")]
           for row in snapshot.get("customer_questions", {}).get("excerpts", [])])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_report(report, format):
    if format not in FORMATS:
        raise AnalysisReportError("Choose json, pdf or xlsx.", "unsupported_report_format")
    report = _report(report)
    snapshot = report["snapshot"]
    if format == "json":
        content = json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    elif format == "pdf":
        content = _pdf(report)
    else:
        content = _xlsx(report)
    captured = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
    name = f"bot-{snapshot['scope']['chatbot_id']}-report-{captured:%Y%m%d}-{snapshot['snapshot_sha256'][:12]}.{format}"
    return {"content": content, "content_type": FORMATS[format], "filename": name}
