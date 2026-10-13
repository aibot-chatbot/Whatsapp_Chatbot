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


def _money(micro_myr):
    ringgit, sen = divmod(int(micro_myr) // 10_000, 100)
    return f"RM {ringgit:,}.{sen:02d}"


def _metric_value(metric):
    if metric.get("value") is None:
        return "Unavailable"
    return _money(metric["value"]) if metric.get("unit") == "micro_myr" else _scalar(metric["value"])


def _cell(table, index, value):
    if value is None:
        return "Unavailable"
    return _money(value) if index in table.get("money_columns", []) and isinstance(value, int) else value


def _layout(snapshot):
    """The report type's frozen layout, or None for reports made before layouts existed."""
    layout = snapshot.get("layout")
    return layout if isinstance(layout, dict) and isinstance(layout.get("sections"), list) else None


def _cards(snapshot, layout):
    metrics = {item["key"]: item for item in snapshot["metrics"]}
    return [metrics[key] for key in layout.get("cards", []) if key in metrics]


def _layout_sections(snapshot, layout):
    """(title, parts) for each section this report has data for; parts are (kind, payload)."""
    metrics = {item["key"]: item for item in snapshot["metrics"]}
    tables = {item["key"]: item for item in snapshot.get("tables", [])}
    grids = {item["key"]: item for item in snapshot.get("distributions", [])}
    excerpts = (snapshot.get("customer_questions") or {}).get("excerpts") or []
    sections = []
    for section in layout["sections"]:
        parts = []
        for item in section.get("items", []):
            kind, key = item.get("kind"), item.get("key")
            if kind == "table" and key in tables:
                parts.append(("table", tables[key]))
            elif kind == "distribution" and key in grids:
                parts.append(("grid", grids[key]))
            elif kind == "metrics":
                prefix = item.get("prefix")
                chosen = [metrics[name] for name in item.get("keys", []) if name in metrics]
                chosen += [metric for metric in snapshot["metrics"] if prefix and metric["key"].startswith(prefix)]
                if chosen:
                    parts.append(("metrics", chosen))
            elif kind == "questions" and excerpts:
                parts.append(("questions", excerpts))
            elif kind == "documents" and snapshot.get("documents"):
                parts.append(("documents", snapshot["documents"]))
        if parts:
            sections.append((section.get("title") or "Details", parts))
    return sections


def _html_table(headers, rows):
    head = "<tr>" + "".join(f"<th>{escape(str(header))}</th>" for header in headers) + "</tr>"
    body = "".join("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>" for row in rows)
    return f"<table>{head}{body}</table>"


def _pdf_grid(grid):
    rows = _grid_rows(grid)
    total = "" if len(rows[0]) == 1 else f" · total {escape(str(grid.get('total')))}"
    parts = [f"<h3>{escape(grid['label'])}</h3><p>{escape(grid['timezone'])} · coverage {escape(grid['status'])}"
             f"{total}. {escape(grid.get('note') or '')}</p>"]
    if len(rows[0]) == 1:
        return parts + [f"<p>{UNKNOWN_GRID}</p>"]
    parts.append('<table class="grid"><tr><th>Day</th>' + "".join(f"<th>{hour}</th>" for hour in HOURS)
                 + "<th>Total</th></tr>")
    parts.extend("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>" for row in rows)
    parts.append("</table>")
    return parts


def _pdf_grids(snapshot):
    return [part for grid in snapshot.get("distributions", []) for part in _pdf_grid(grid)]


def _table_rows(table):
    return [[_cell(table, index, value) for index, value in enumerate(row)] for row in table["rows"]]


def _pdf_part(kind, payload):
    if kind == "table":
        if not payload.get("available", True):
            return [f"<p>{escape(payload['label'])}: unavailable (unknown, not zero).</p>"]
        rows = _table_rows(payload)
        parts = [_html_table(payload["columns"], rows) if rows else "<p>None in this period.</p>"]
        return parts + (["<p>Only the first rows are shown.</p>"] if payload.get("truncated") else [])
    if kind == "grid":
        return _pdf_grid(payload)
    if kind == "metrics":
        return [_html_table(["Measure", "Value", "Coverage"],
                            [[item["label"], _metric_value(item), item["status"]] for item in payload])]
    if kind == "questions":
        return [f"<p>Message {sample['message_id']}; conversation {sample['conversation_id']}: "
                f"{escape(sample['text'])}</p>" for sample in payload]
    parts = []
    for document in payload:
        parts.append(f"<h3>{escape(document['name'])}</h3>")
        parts.extend(f"<p>{escape(str(item.get('text') or ''))}</p>" for item in document["excerpts"])
    return parts


def _narrative(report):
    # Escape every byte of model/document text. Never render model HTML/images.
    return [f"<p>{escape(paragraph).replace(chr(10), '<br>')}</p>" for paragraph in report["narrative"].split("\n\n")]


def _pdf(report):
    snapshot = report["snapshot"]
    scope = snapshot["scope"]
    layout = _layout(snapshot)
    partial = report["status"] == "partial"
    if layout:
        title = f"{layout['title']}{' (partial)' if partial else ''} — {scope['bot_name']}"
    else:
        title = f"{'Partial report' if partial else 'Report'} — {scope['bot_name']}"
    metadata = [f"Industry: {snapshot['industry']['name']}",
                f"Period: {scope.get('period_start') or 'Selected documents'} to {scope.get('period_end') or 'capture time'} (end exclusive, {scope['timezone']})",
                f"Captured: {snapshot['captured_at']}", f"Snapshot: {snapshot['snapshot_sha256']}"]
    parts = [f"<h1>{escape(title)}</h1>"]
    parts.extend(f"<p>{escape(line)}</p>" for line in metadata)
    if layout:
        cards = _cards(snapshot, layout)
        if cards:
            parts.append("<h2>Key numbers</h2>")
            parts.append(_html_table(["Measure", "Value"], [[item["label"], _metric_value(item)] for item in cards]))
        parts.append("<h2>Summary</h2>")
        parts.extend(_narrative(report))
        for section_title, items in _layout_sections(snapshot, layout):
            parts.append(f"<h2>{escape(section_title)}</h2>")
            for kind, payload in items:
                parts.extend(_pdf_part(kind, payload))
    else:
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
        parts.extend(_narrative(report))
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
    if not layout and questions.get("excerpts"):
        parts.append("<h2>Customer question samples</h2>")
        parts.extend(_pdf_part("questions", questions["excerpts"]))
    return _pdf_bytes(parts)


def _pdf_bytes(parts):
    import pymupdf

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

    layout = _layout(snapshot)
    used = set()

    def unique(name):
        # Excel sheet names: at most 31 characters, none of the reserved characters, and unique.
        base = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Details"
        title, number = base, 2
        while title.lower() in used:
            title = f"{base[:28]} {number}"
            number += 1
        used.add(title.lower())
        return title

    report_rows = [
        ["Status", report["status"]], ["Bot ID", scope["chatbot_id"]], ["Bot", scope["bot_name"]],
        ["Industry", snapshot["industry"]["name"]], ["Kind", scope["kind"]],
        ["Period start", scope.get("period_start")], ["Period end (exclusive)", scope.get("period_end")],
        ["AI analysis", report["analysis_status"]],
        ["Timezone", scope["timezone"]], ["Captured", snapshot["captured_at"]],
        ["Snapshot SHA256", snapshot["snapshot_sha256"]]]
    if layout:
        report_rows.insert(0, ["Report type", layout["title"]])
    sheet(unique("Report"), ["Field", "Value"], report_rows)
    if layout:
        sheet(unique("Key numbers"), ["Measure", "Value", "Coverage"],
              [[item["label"], _metric_value(item), item["status"]] for item in _cards(snapshot, layout)])
        for section_title, items in _layout_sections(snapshot, layout):
            for index, (kind, payload) in enumerate(items):
                title = unique(section_title if index == 0 else f"{section_title} {index + 1}")
                if kind == "table":
                    sheet(title, payload["columns"], _table_rows(payload) if payload.get("available", True)
                          else [["Unavailable (unknown, not zero)"]])
                elif kind == "grid":
                    sheet(title, ["Day", *HOURS, "Day total"], _grid_rows(payload))
                elif kind == "metrics":
                    sheet(title, ["Measure", "Value", "Coverage"],
                          [[item["label"], _metric_value(item), item["status"]] for item in payload])
                elif kind == "questions":
                    sheet(title, ["Message ID", "Conversation ID", "Received", "Text", "Truncated"],
                          [[row.get(key) for key in ("message_id", "conversation_id", "created_at", "text", "truncated")]
                           for row in payload])
                else:
                    sheet(title, ["File ID", "Name", "Excerpt"],
                          [[document["file_id"], document["name"], item.get("text")]
                           for document in payload for item in document["excerpts"]])
        sheet(unique("Commentary"), ["Paragraph"], [[paragraph] for paragraph in report["narrative"].split("\n\n")])
        sheet(unique("Limitations"), ["Limitation"], [[item] for item in snapshot["limitations"] + report["limitations"]])
        sheet(unique("Sources"), ["Source", "Available", "Rows", "Truncated", "Error"],
              [[name, source["available"], source["row_count"], source["truncated"], source.get("error_code")]
               for name, source in snapshot["sources"].items()])
        if snapshot["records"]:
            sheet(unique("Business records"), ["Event ID", "Type", "Status", "Record ID", "Source", "Conversation ID",
                                               "Message evidence", "Occurred"],
                  [[row.get(key) for key in ("id", "action_type", "status", "record_id", "source", "conversation_id",
                                             "evidence_message_ids", "occurred_at")] for row in snapshot["records"]])
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
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
