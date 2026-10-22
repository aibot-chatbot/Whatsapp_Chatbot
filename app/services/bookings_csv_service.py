"""bookings_csv_service.py - One living bookings CSV per company.

The file is rewritten in place at a fixed key (reports/<company_id>/bookings/bookings.csv)
after every change and is never saved under a new name. A download is rendered from the
database, which is authoritative, so a stale stored copy can never be served; a download
only reads, so it cannot be used to hammer storage.
"""

import csv
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.service_booking_repository import list_bookings_for_csv
from app.services import document_storage_service as storage

logger = logging.getLogger(__name__)

# ponytail: the 5000 newest rows (about 1.5 MB). Beyond that, split the file by year.
MAX_ROWS = 5000

# (CSV header, booking field)
COLUMNS = (
    ("booking_id", "id"), ("status", "status"), ("kind", "kind"),
    ("customer_name", "customer_name"), ("customer_phone", "customer_phone"),
    ("customer_ref", "customer_ref"), ("channel", "channel"), ("service", "service_name"),
    ("scheduled_for", "scheduled_for"), ("party_size", "party_size"), ("notes", "notes"),
    ("source", "source"), ("created_at", "created_at"), ("updated_at", "updated_at"),
)
_TIME_COLUMNS = frozenset({"scheduled_for", "created_at", "updated_at"})
_MYT = timezone(timedelta(hours=8))  # Malaysia has no DST
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PHONE = re.compile(r"\+?[0-9]{6,15}")


def neutralize(value, *, phone=False):
    """Make a cell safe to open in a spreadsheet.

    Customer-supplied text can start with = + - @ (or a tab/CR), which Excel and Sheets
    run as a formula. A leading apostrophe turns it back into text. A plain phone number
    such as +60123456789 is exempt only when it is nothing but a number.
    """
    text = "" if value is None else str(value)
    if phone and _PHONE.fullmatch(text):
        return text
    # Spreadsheets skip leading blanks before deciding a cell is a formula, so look past them.
    return "'" + text if text.startswith(_FORMULA_START) or text.lstrip().startswith(_FORMULA_START) else text


def _local_time(value):
    """'2026-10-05 19:00' in Malaysia time from an ISO-8601 timestamp; the raw text if unparseable."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_MYT).strftime("%Y-%m-%d %H:%M")


def _cell(header, value):
    if header in _TIME_COLUMNS:
        text = _local_time(value)
    else:
        text = "" if value is None else str(value)
    return neutralize(text, phone=header == "customer_phone")


def render_csv(bookings):
    """UTF-8 with a BOM and CRLF line ends, which is what Excel opens without mangling names."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for header, _ in COLUMNS])
    for booking in bookings:
        writer.writerow([_cell(header, booking.get(field)) for header, field in COLUMNS])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _require_company(company_id):
    if type(company_id) is not int or company_id <= 0:
        raise ValueError("A valid company is required.")


def _storage_path(company_id):
    _require_company(company_id)
    root = Path(os.getenv("REPORT_STORAGE_ROOT", str(Path(__file__).resolve().parents[2] / "data" / "reports")))
    return root, root / str(company_id) / "bookings" / "bookings.csv"


def build_company_csv(company_id, chatbot_id=None):
    """The current file, rendered from the database. Reads only, so storage trouble never blocks it.
    With chatbot_id, only that chatbot's bookings: what the per-bot Bookings page downloads."""
    _require_company(company_id)
    rows = list_bookings_for_csv(company_id, MAX_ROWS, chatbot_id=chatbot_id)
    if len(rows) >= MAX_ROWS:
        logger.warning("Bookings CSV for company %s is cut at its %s newest rows", company_id, MAX_ROWS)
    return render_csv(rows)


def refresh_company_csv(company_id):
    """Rewrite the company's stored file from the database. True when it was stored."""
    root, path = _storage_path(company_id)
    content = build_company_csv(company_id)
    try:
        storage.write_file(path, content, root=root, namespace="reports", company_id=company_id)
        return True
    except storage.DocumentStorageError:
        logger.warning("Bookings CSV could not be stored for company %s", company_id)
        return False
