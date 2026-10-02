"""The company's bookings CSV: safe to open in Excel, and ONE file rewritten in place.

Seam: bookings_csv_service. The bytes are parsed back with the csv module and the
storage call is observed at document_storage_service.write_file, so nothing here
depends on how the module builds its rows internally.
"""

import csv
import io
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import bookings_csv_service as svc
from app.services.document_storage_service import DocumentStorageError

EXPECTED_HEADER = (
    "booking_id,status,kind,customer_name,customer_phone,customer_ref,channel,service,"
    "scheduled_for,party_size,notes,source,created_at,updated_at"
)


def booking(**overrides):
    row = {
        "id": 17, "status": "requested", "kind": "reservation", "customer_name": "Ada Lim",
        "customer_phone": "+60123456789", "customer_ref": "60123456789", "channel": "whatsapp",
        "service_name": "Dinner for four", "scheduled_for": "2026-10-05T11:00:00+00:00",
        "party_size": 4, "notes": "Window seat", "source": "chat",
        "created_at": "2026-10-01T02:00:00+00:00", "updated_at": "2026-10-01T02:30:00+00:00",
    }
    row.update(overrides)
    return row


def parse(content):
    """What an Excel-compatible reader sees: rows of text keyed by header."""
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline="")))


# --- the bytes --------------------------------------------------------------

def test_header_row_is_stable():
    first_line = svc.render_csv([]).decode("utf-8-sig").splitlines()[0]
    assert first_line == EXPECTED_HEADER


def test_empty_company_gets_a_header_only_file():
    assert parse(svc.render_csv([])) == []


def test_file_opens_cleanly_in_excel():
    content = svc.render_csv([booking()])
    assert content.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM, or Excel garbles non-ASCII names"
    assert content.count(b"\r\n") == 2, "CRLF line endings: one after the header, one after the row"


def test_values_use_malaysia_time_and_plain_text():
    row = parse(svc.render_csv([booking()]))[0]
    assert row["booking_id"] == "17"
    assert row["scheduled_for"] == "2026-10-05 19:00"   # 11:00 UTC is 19:00 in Malaysia
    assert row["created_at"] == "2026-10-01 10:00"
    assert row["party_size"] == "4"
    assert row["service"] == "Dinner for four"


def test_missing_values_are_blank_not_the_word_none():
    row = parse(svc.render_csv([booking(scheduled_for=None, party_size=None, notes=None)]))[0]
    assert (row["scheduled_for"], row["party_size"], row["notes"]) == ("", "", "")


def test_non_ascii_names_survive():
    row = parse(svc.render_csv([booking(customer_name="Nur Aisyah binti Zainal 王小明")]))[0]
    assert row["customer_name"] == "Nur Aisyah binti Zainal 王小明"


def test_commas_quotes_and_newlines_round_trip():
    notes = 'He said "yes", then\nleft'
    assert parse(svc.render_csv([booking(notes=notes)]))[0]["notes"] == notes


# --- formula injection --------------------------------------------------------

@pytest.mark.parametrize("hostile", [
    "=HYPERLINK(\"http://evil.test\",\"click\")", "+SUM(A1:A9)", "-2+3", "@SUM(A1)",
    "\t=1+1", "\r=1+1",
])
def test_a_cell_can_never_start_a_formula(hostile):
    for column in ("customer_name", "service_name", "notes", "customer_ref"):
        key = {"service_name": "service"}.get(column, column)
        cell = parse(svc.render_csv([booking(**{column: hostile})]))[0][key]
        assert cell == "'" + hostile, (column, cell)


@pytest.mark.parametrize("hostile", [" =1+1", "  @SUM(A1)", " =1+1", " +1+1", " \t-2+3"])
def test_leading_blanks_cannot_hide_a_formula(hostile):
    for column in ("customer_name", "notes", "customer_ref"):
        assert parse(svc.render_csv([booking(**{column: hostile})]))[0][column].startswith("'"), column


def test_ordinary_text_with_a_leading_space_is_not_altered():
    assert parse(svc.render_csv([booking(notes=" window seat")]))[0]["notes"] == " window seat"


def test_a_plain_phone_number_is_left_alone():
    assert parse(svc.render_csv([booking(customer_phone="+60123456789")]))[0]["customer_phone"] == "+60123456789"


def test_a_phone_field_carrying_a_formula_is_neutralised():
    cell = parse(svc.render_csv([booking(customer_phone="+60123456789;=1+1")]))[0]["customer_phone"]
    assert cell.startswith("'")


# --- the one living file -------------------------------------------------------

@pytest.fixture
def stored(monkeypatch):
    writes = []

    def record(path, content, *, root, namespace, chatbot_id=None, company_id=None):
        writes.append({"path": Path(path), "content": content, "root": Path(root),
                       "namespace": namespace, "company_id": company_id})

    rows = {"value": [booking()]}
    listing = Mock(side_effect=lambda company_id, limit: list(rows["value"]))
    monkeypatch.setattr(svc.storage, "write_file", record)
    monkeypatch.setattr(svc, "list_bookings_for_csv", listing)
    return {"writes": writes, "rows": rows, "listing": listing}


def test_every_refresh_rewrites_the_same_file_for_that_company(stored):
    assert svc.refresh_company_csv(42) is True
    stored["rows"]["value"] = [booking(), booking(id=18, status="confirmed")]
    assert svc.refresh_company_csv(42) is True

    first, second = stored["writes"]
    assert first["path"] == second["path"], "an update must overwrite the existing file, not create a new one"
    assert first["path"].parts[-3:] == ("42", "bookings", "bookings.csv")
    assert (first["namespace"], first["company_id"]) == ("reports", 42)
    assert len(parse(first["content"])) == 1 and len(parse(second["content"])) == 2


def test_companies_never_share_a_file(stored):
    svc.refresh_company_csv(42)
    svc.refresh_company_csv(43)

    assert stored["writes"][0]["path"] != stored["writes"][1]["path"]


def test_download_is_rendered_from_the_database_and_writes_nothing(stored):
    content = svc.build_company_csv(42)

    assert content == svc.render_csv([booking()])
    assert stored["writes"] == [], "a download must not be a way to hammer storage"


def test_a_file_cut_at_the_row_cap_is_logged(stored, caplog):
    stored["rows"]["value"] = [booking(id=index) for index in range(svc.MAX_ROWS)]

    with caplog.at_level("WARNING"):
        svc.build_company_csv(42)

    assert any("cut at its" in record.message for record in caplog.records)


def test_a_file_under_the_cap_logs_nothing(stored, caplog):
    with caplog.at_level("WARNING"):
        svc.build_company_csv(42)

    assert not caplog.records


@pytest.mark.parametrize("bad", [0, -1, "42", None, True])
def test_a_bad_company_never_reaches_the_database_for_a_download(stored, bad):
    with pytest.raises(ValueError):
        svc.build_company_csv(bad)
    stored["listing"].assert_not_called()


def test_a_storage_outage_does_not_break_the_download(stored, monkeypatch):
    monkeypatch.setattr(svc.storage, "write_file", Mock(side_effect=DocumentStorageError("down")))

    assert svc.refresh_company_csv(42) is False
    assert parse(svc.build_company_csv(42))[0]["booking_id"] == "17"


def test_the_listing_is_capped(stored):
    svc.refresh_company_csv(42)

    stored["listing"].assert_called_once_with(42, svc.MAX_ROWS)


@pytest.mark.parametrize("bad", [0, -1, "42", None, True, 4.2])
def test_a_bad_company_id_never_reaches_a_path(stored, bad):
    with pytest.raises(ValueError):
        svc.refresh_company_csv(bad)
    assert stored["writes"] == []


def test_root_is_the_configured_report_storage_root(stored, monkeypatch, tmp_path):
    monkeypatch.setenv("REPORT_STORAGE_ROOT", str(tmp_path))
    svc.refresh_company_csv(42)

    assert stored["writes"][0]["root"] == tmp_path
    assert str(stored["writes"][0]["path"]).startswith(str(tmp_path) + os.sep)
