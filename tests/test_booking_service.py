"""Booking rules: what a chat request may contain, who may change what, and the side effects.

Seam: booking_service. The repository is a stateful in-memory fake that honours the real
contract (company scoping, unique intake key, version-guarded update), so these tests
exercise the service's decisions and not just call counts.
"""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.services import booking_service as svc

NOW = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)  # 12:00 in Malaysia
REAL_BACKGROUND = svc._background  # the fixture replaces it with an inline runner


class FakeRepo:
    def __init__(self):
        self.rows, self.next_id, self.recent, self.company_recent = {}, 1, 0, None
        self.clock = NOW

    def create_booking(self, row):
        if row.get("intake_key") and any(
            r["company_id"] == row["company_id"] and r.get("intake_key") == row["intake_key"]
            for r in self.rows.values()
        ):
            return None
        self.clock += timedelta(seconds=1)
        stored = dict(row, id=self.next_id, version=1, created_at=self.clock.isoformat())
        self.rows[self.next_id] = stored
        self.next_id += 1
        return dict(stored)

    def count_recent_for_company(self, company_id, since_iso, source="chat", before_iso=None):
        if self.company_recent is not None:
            return self.company_recent
        return sum(1 for r in self.rows.values()
                   if r["company_id"] == company_id and r.get("source") == source and r["created_at"] >= since_iso
                   and (before_iso is None or r["created_at"] < before_iso))

    def get_booking(self, company_id, booking_id):
        row = self.rows.get(booking_id)
        return dict(row) if row and row["company_id"] == company_id else None

    def get_booking_by_intake_key(self, company_id, key):
        for row in self.rows.values():
            if row["company_id"] == company_id and row.get("intake_key") == key:
                return dict(row)
        return None

    def count_recent_for_conversation(self, company_id, conversation_id, since_iso):
        return self.recent

    def update_booking(self, company_id, booking_id, expected_version, changes):
        row = self.rows.get(booking_id)
        if not row or row["company_id"] != company_id or row["version"] != expected_version:
            return None
        row.update(changes)
        row["version"] += 1
        return dict(row)


@pytest.fixture
def world(monkeypatch):
    repo = FakeRepo()
    refresh, notify = Mock(return_value=True), Mock()
    monkeypatch.setattr(svc, "repo", repo)
    monkeypatch.setattr(svc, "refresh_company_csv", refresh)
    monkeypatch.setattr(svc, "notify_owner_of_new_request", notify)
    # Production runs these on a background thread; the tests run them inline so they can assert.
    monkeypatch.setattr(svc, "_background", lambda function, *args: svc._best_effort(function, *args))
    return {"repo": repo, "refresh": refresh, "notify": notify}


def request(now=NOW, **fields):
    base = {"kind": "reservation", "service": "Dinner for four", "when": "2026-10-05 19:00",
            "party_size": 4, "name": "Ada Lim", "notes": "Window seat"}
    base.update(fields)
    return svc.record_chat_request(
        company_id=42, chatbot_id=7, conversation_id=55, channel="whatsapp",
        customer_phone="+60123456789", customer_ref="60123456789", fields=base, now=now,
    )


# --- a chat request ----------------------------------------------------------

def test_a_chat_request_is_recorded_as_requested(world):
    booking = request()

    assert booking["status"] == "requested" and booking["source"] == "chat" and booking["version"] == 1
    assert (booking["company_id"], booking["chatbot_id"], booking["conversation_id"]) == (42, 7, 55)
    assert booking["kind"] == "reservation" and booking["service_name"] == "Dinner for four"
    assert booking["party_size"] == 4 and booking["customer_name"] == "Ada Lim"
    assert booking["customer_phone"] == "+60123456789" and booking["channel"] == "whatsapp"


def test_the_requested_time_is_malaysia_time_stored_as_utc(world):
    assert request()["scheduled_for"] == "2026-10-05T11:00:00+00:00"


def test_the_model_cannot_choose_tenant_or_status(world):
    booking = request(company_id=999, chatbot_id=888, status="confirmed", version=50,
                      source="staff", confirmed_at="2026-01-01T00:00:00+00:00")

    assert (booking["company_id"], booking["chatbot_id"]) == (42, 7)
    assert booking["status"] == "requested" and booking["version"] == 1 and booking["source"] == "chat"
    assert "confirmed_at" not in booking or booking["confirmed_at"] is None


def test_text_is_cleaned_of_control_and_bidi_characters(world):
    booking = request(name="Ada\x00 ‮Lim\x07", service="Dinner\n\nfor   four", notes="line1\r\nline2")

    assert booking["customer_name"] == "Ada Lim"
    assert booking["service_name"] == "Dinner for four"
    assert booking["notes"] == "line1 line2"


def test_overlong_text_is_truncated_to_the_column_limits(world):
    booking = request(name="n" * 500, service="s" * 500, notes="x" * 5000)

    assert len(booking["customer_name"]) == 120
    assert len(booking["service_name"]) == 150
    assert len(booking["notes"]) == 1000


def test_an_unknown_kind_becomes_other(world):
    assert request(kind="drop table")["kind"] == "other"


@pytest.mark.parametrize("raw,expected", [(4, 4), ("4", 4), (0, None), (-2, None), (10_001, None),
                                          ("many", None), (None, None), (True, None), (2.5, None)])
def test_party_size_must_be_a_sane_whole_number(world, raw, expected):
    assert request(party_size=raw)["party_size"] == expected


@pytest.mark.parametrize("when", [
    "next friday evening", "2020-01-01 10:00", "2031-01-01 10:00", "", None,
    "2026-10-05", "20261005", "2026-W41-1",              # a date alone would silently become midnight
    "0001-01-01 00:00", "9999-12-31 23:59-08:00",        # out of range once shifted to UTC
    "2026-13-45 10:00", "2026-10-05T19:00:00+0800"])
def test_an_unusable_time_is_kept_in_the_notes_not_dropped(world, when):
    booking = request(when=when, notes="Window seat")

    assert booking["scheduled_for"] is None
    if when:
        assert str(when)[:100] in booking["notes"] and "Window seat" in booking["notes"]


def test_a_request_with_neither_service_nor_time_is_rejected(world):
    with pytest.raises(svc.BookingValidationError):
        request(service=None, when=None)
    assert world["repo"].rows == {}


def test_the_same_request_twice_returns_the_existing_booking_quietly(world):
    first = request()
    second = request()

    assert second["id"] == first["id"] and len(world["repo"].rows) == 1
    world["refresh"].assert_called_once()
    world["notify"].assert_called_once()


@pytest.mark.parametrize("when,stored", [
    ("2026-10-05 19:00", "2026-10-05T11:00:00+00:00"),
    ("2026-10-05T19:00", "2026-10-05T11:00:00+00:00"),
    ("2026-10-05 19:00:30", "2026-10-05T11:00:30+00:00"),
    ("2026-10-05T19:00:00+08:00", "2026-10-05T11:00:00+00:00"),
    ("2026-10-05 11:00Z", "2026-10-05T11:00:00+00:00")])
def test_a_clear_date_and_time_is_understood_in_any_common_form(world, when, stored):
    assert request(when=when)["scheduled_for"] == stored


def test_a_conversation_cannot_flood_the_queue(world):
    world["repo"].recent = svc.MAX_REQUESTS_PER_CONVERSATION_PER_HOUR

    assert request() is None
    assert world["repo"].rows == {}
    world["notify"].assert_not_called()


def test_a_company_cannot_be_flooded_across_many_conversations(world):
    world["repo"].company_recent = svc.MAX_CHAT_REQUESTS_PER_COMPANY_PER_HOUR

    assert request() is None
    assert world["repo"].rows == {}
    world["refresh"].assert_not_called()
    world["notify"].assert_not_called()


def test_a_replay_of_an_open_request_still_succeeds_over_a_limit(world):
    first = request()
    world["repo"].recent = svc.MAX_REQUESTS_PER_CONVERSATION_PER_HOUR

    assert request()["id"] == first["id"], "the customer is told the truth: it is already with the team"
    assert len(world["repo"].rows) == 1


def test_a_replay_of_a_cancelled_request_is_refused_over_a_limit(world):
    first = request()
    svc.update_booking(42, first["id"], 1, {"status": "cancelled"}, now=NOW)
    world["repo"].company_recent = svc.MAX_CHAT_REQUESTS_PER_COMPANY_PER_HOUR

    assert request() is None


def test_a_confirmed_request_asked_again_is_still_the_same_request(world):
    first = request()
    world["repo"].rows[first["id"]]["status"] = "confirmed"

    assert request()["id"] == first["id"] and len(world["repo"].rows) == 1


@pytest.mark.parametrize("finished", ["cancelled", "completed"])
def test_a_request_repeated_after_it_finished_is_a_new_request(world, finished):
    first = request()
    world["repo"].rows[first["id"]]["status"] = finished

    second = request()

    assert second["id"] != first["id"] and second["status"] == "requested"
    assert second["intake_key"] != first["intake_key"]
    assert len(world["repo"].rows) == 2


def test_the_same_request_on_another_day_is_a_new_request(world):
    first = request()

    second = request(now=NOW + timedelta(days=1))

    assert second["id"] != first["id"] and len(world["repo"].rows) == 2


def test_endless_cancelled_repeats_stop_at_a_bound(world):
    for _ in range(svc._MAX_KEY_ATTEMPTS):
        booking = request()
        svc.update_booking(42, booking["id"], 1, {"status": "cancelled"}, now=NOW)

    assert request() is None


def test_the_file_and_the_owner_are_updated_after_a_new_request(world):
    request()

    world["refresh"].assert_called_once_with(42)
    world["notify"].assert_called_once_with(42)


def test_a_file_failure_never_loses_the_booking(world):
    world["refresh"].side_effect = RuntimeError("storage down")

    assert request()["status"] == "requested"
    assert len(world["repo"].rows) == 1


def test_a_notice_failure_never_loses_the_booking(world):
    world["notify"].side_effect = RuntimeError("smtp down")

    assert request()["status"] == "requested"


def test_the_owner_is_emailed_once_per_window_however_many_requests_arrive(world):
    request(service="Dinner")
    request(service="Haircut")
    request(service="Massage")

    assert len(world["repo"].rows) == 3
    assert world["notify"].call_count == 1
    assert world["refresh"].call_count == 3, "the file is still refreshed every time"


def test_a_new_window_emails_the_owner_again(world):
    request(service="Dinner")
    later = NOW + timedelta(minutes=svc.NOTICE_WINDOW_MINUTES + 1)
    world["repo"].clock = later

    request(service="Haircut", now=later)

    assert world["notify"].call_count == 2


def test_a_second_request_in_the_same_instant_still_yields_exactly_one_notice(world):
    # Both rows exist before either asks "was I first?": only the earlier one may email.
    first = world["repo"].create_booking({"company_id": 42, "source": "chat", "intake_key": "a"})
    second = world["repo"].create_booking({"company_id": 42, "source": "chat", "intake_key": "b"})

    svc._notify_if_first_in_window(42, first, NOW)
    svc._notify_if_first_in_window(42, second, NOW)

    assert world["notify"].call_count == 1


def test_the_file_and_notice_run_off_the_callers_thread(world, monkeypatch):
    monkeypatch.setattr(svc, "_background", REAL_BACKGROUND)
    seen, done = [], threading.Event()

    def remember(company_id):
        seen.append(threading.get_ident())
        done.set()

    world["refresh"].side_effect = remember

    request()

    assert done.wait(2), "the refresh never ran"
    assert seen[0] != threading.get_ident(), "the refresh must not run on the chat reply thread"


def test_the_intake_switch_is_a_pass_through_to_the_repository(monkeypatch):
    toggle = Mock(return_value=True)
    monkeypatch.setattr(svc.repo, "set_intake_enabled", toggle)

    assert svc.set_intake_enabled(42, 7, True) is True
    toggle.assert_called_once_with(42, 7, True)


# --- staff updates -----------------------------------------------------------

def created(world):
    return request()


def test_staff_can_confirm_a_request(world):
    booking = created(world)

    updated = svc.update_booking(42, booking["id"], 1, {"status": "confirmed"}, now=NOW)

    assert updated["status"] == "confirmed" and updated["version"] == 2
    assert updated["confirmed_at"] == NOW.isoformat()


def test_staff_can_cancel(world):
    booking = created(world)

    updated = svc.update_booking(42, booking["id"], 1, {"status": "cancelled"}, now=NOW)

    assert updated["status"] == "cancelled" and updated["cancelled_at"] == NOW.isoformat()


@pytest.mark.parametrize("path", [
    ["confirmed", "requested"],   # no going back
    ["cancelled", "confirmed"],   # cancelled is final
    ["cancelled", "completed"],
    ["completed", "cancelled"],   # completed is final
    ["requested", "completed"],   # must be confirmed first
])
def test_illegal_status_moves_are_refused(world, path):
    booking = created(world)
    world["repo"].rows[booking["id"]]["status"] = path[0]

    with pytest.raises(svc.BookingValidationError):
        svc.update_booking(42, booking["id"], 1, {"status": path[1]}, now=NOW)
    assert world["repo"].rows[booking["id"]]["status"] == path[0]


def test_a_finished_booking_cannot_be_edited(world):
    booking = created(world)
    world["repo"].rows[booking["id"]]["status"] = "cancelled"

    with pytest.raises(svc.BookingValidationError):
        svc.update_booking(42, booking["id"], 1, {"notes": "changed my mind"}, now=NOW)


def test_staff_can_reschedule_and_edit_details(world):
    booking = created(world)

    updated = svc.update_booking(
        42, booking["id"], 1,
        {"scheduled_for": "2026-10-06 20:30", "party_size": 6, "notes": "Birthday cake"}, now=NOW)

    assert updated["scheduled_for"] == "2026-10-06T12:30:00+00:00"
    assert updated["party_size"] == 6 and updated["notes"] == "Birthday cake"


@pytest.mark.parametrize("bad", [
    {"scheduled_for": "not a date"}, {"party_size": 0}, {"kind": "mystery"},
    {"scheduled_for": "2026-10-06"},                 # a date alone is not an appointment time
    {"scheduled_for": "0001-01-01 00:00"},           # overflowed the UTC conversion before
    {"scheduled_for": ["2026-10-06 20:30"]}, {"scheduled_for": 20261006},
    {"status": ["confirmed"]}, {"status": {"to": "confirmed"}}, {"status": 1},
    {"kind": ["booking"]}, {"customer_name": {"a": 1}}, {"service_name": ["x"]}, {"notes": 5},
    {"party_size": {"n": 1}}])
def test_staff_edits_are_validated_strictly(world, bad):
    booking = created(world)

    with pytest.raises(svc.BookingValidationError):
        svc.update_booking(42, booking["id"], 1, bad, now=NOW)


@pytest.mark.parametrize("changes", [{}, {"company_id": 1}, {"chatbot_id": 2}, {"version": 9}, {"id": 3},
                                     {"conversation_id": 4}, {"intake_key": "x"}, {"unknown": 1}])
def test_nothing_to_change_or_forbidden_fields_are_refused(world, changes):
    booking = created(world)

    with pytest.raises(svc.BookingValidationError):
        svc.update_booking(42, booking["id"], 1, changes, now=NOW)


def test_a_stale_version_is_a_conflict_and_changes_nothing(world):
    booking = created(world)
    svc.update_booking(42, booking["id"], 1, {"status": "confirmed"}, now=NOW)

    with pytest.raises(svc.BookingConflict):
        svc.update_booking(42, booking["id"], 1, {"status": "cancelled"}, now=NOW)
    assert world["repo"].rows[booking["id"]]["status"] == "confirmed"


def test_a_booking_that_changes_between_read_and_write_is_a_conflict(world, monkeypatch):
    booking = created(world)
    monkeypatch.setattr(world["repo"], "update_booking", lambda *a, **k: None)

    with pytest.raises(svc.BookingConflict):
        svc.update_booking(42, booking["id"], 1, {"status": "confirmed"}, now=NOW)


def test_another_companys_booking_is_not_found(world):
    booking = created(world)

    with pytest.raises(svc.BookingNotFound):
        svc.update_booking(43, booking["id"], 1, {"status": "confirmed"}, now=NOW)
    assert world["repo"].rows[booking["id"]]["status"] == "requested"


def test_the_file_is_refreshed_after_every_update(world):
    booking = created(world)
    world["refresh"].reset_mock()

    svc.update_booking(42, booking["id"], 1, {"status": "confirmed"}, now=NOW)

    world["refresh"].assert_called_once_with(42)


def test_a_file_failure_never_fails_an_update(world):
    booking = created(world)
    world["refresh"].side_effect = RuntimeError("storage down")

    assert svc.update_booking(42, booking["id"], 1, {"status": "confirmed"}, now=NOW)["status"] == "confirmed"


# --- the owner notice carries no customer details ---------------------------------

def test_the_owner_notice_names_no_customer(monkeypatch):
    sent = Mock(return_value=True)
    monkeypatch.setattr(svc, "get_company_billing_contact",
                        lambda company_id: {"email": "owner@example.test", "full_name": "Olu"})
    monkeypatch.setattr(svc, "send_notice_email", sent)
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.test")

    svc.notify_owner_of_new_request(42)

    args, kwargs = sent.call_args
    assert args[0] == "owner@example.test"
    text = " ".join(str(v) for v in kwargs.values())
    assert "https://app.example.test/bookings.html" in text
    for private in ("Ada", "60123456789", "Dinner"):
        assert private not in text


def test_no_owner_means_no_notice(monkeypatch):
    sent = Mock()
    monkeypatch.setattr(svc, "get_company_billing_contact", lambda company_id: None)
    monkeypatch.setattr(svc, "send_notice_email", sent)

    svc.notify_owner_of_new_request(42)

    sent.assert_not_called()
