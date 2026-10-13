"""Which times may the AI offer? Weekly hours + one-off slots - closed dates - full slots.

Seam: availability_service.open_slots, with the repository replaced by an in-memory
stand-in that behaves like the tables in data/073_availability_booking.sql.
Times are Malaysia time (UTC+8); expected values are written out by hand.
"""

from datetime import datetime, timezone

import pytest

from app.services import availability_service as svc

COMPANY, BOT = 1, 10
# Sunday 4 Oct 2026, 20:00 Malaysia time
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class FakeRepo:
    def __init__(self):
        self.packages, self.schedules, self.closures, self.slots = [], [], [], []

    def list_packages(self, company_id, chatbot_id):
        return [p for p in self.packages if (p["company_id"], p["chatbot_id"]) == (company_id, chatbot_id)]

    def list_schedules_for_chatbot(self, company_id, chatbot_id):
        return [s for s in self.schedules if (s["company_id"], s["chatbot_id"]) == (company_id, chatbot_id)]

    def list_closures(self, company_id, chatbot_id, from_date):
        return [c for c in self.closures if c["chatbot_id"] == chatbot_id and c["closed_on"] >= from_date]

    def latest_schedule_slot_start(self, company_id, chatbot_id):
        starts = [s["starts_at"] for s in self.slots if s["chatbot_id"] == chatbot_id and s["source"] == "schedule"]
        return max(starts) if starts else None

    def insert_slots(self, rows):
        taken = {(s["package_id"], s["starts_at"]) for s in self.slots}
        for row in rows:
            if (row["package_id"], row["starts_at"]) not in taken:
                self.slots.append(dict(row, id=len(self.slots) + 1, booked_seats=0))

    def list_open_slots(self, company_id, chatbot_id, package_id, start_iso, end_iso, limit):
        return sorted((s for s in self.slots if s["chatbot_id"] == chatbot_id and s["package_id"] == package_id
                       and s.get("status", "open") == "open" and start_iso <= s["starts_at"] < end_iso),
                      key=lambda s: s["starts_at"])[:limit]


@pytest.fixture
def repo(monkeypatch):
    fake = FakeRepo()
    fake.packages.append({"id": 5, "company_id": COMPANY, "chatbot_id": BOT, "name": "Haircut",
                          "duration_minutes": 60, "seats_per_slot": 2, "enabled": True})
    # Monday 10:00-12:00 every hour, so 10:00 and 11:00 (a 12:00 start would end after closing)
    fake.schedules.append({"company_id": COMPANY, "chatbot_id": BOT, "package_id": 5, "weekday": 1,
                           "start_time": "10:00:00", "end_time": "12:00:00", "interval_minutes": 60})
    monkeypatch.setattr(svc, "repo", fake)
    return fake


def _offered(repo):
    return [(s["package_id"], s["starts_at"], s["seats_left"]) for s in svc.open_slots(COMPANY, BOT, now=NOW, days=7)]


def test_weekly_hours_become_offerable_times(repo):
    assert _offered(repo) == [(5, "2026-10-05T02:00:00+00:00", 2), (5, "2026-10-05T03:00:00+00:00", 2)]


def test_a_one_off_slot_is_offered_alongside_weekly_hours(repo):
    repo.slots.append({"id": 99, "company_id": COMPANY, "chatbot_id": BOT, "package_id": 5, "source": "one_off",
                       "starts_at": "2026-10-06T07:00:00+00:00", "ends_at": "2026-10-06T08:00:00+00:00",
                       "capacity": 4, "booked_seats": 1, "status": "open"})

    assert _offered(repo)[-1] == (5, "2026-10-06T07:00:00+00:00", 3)


def test_a_closed_date_offers_nothing_that_day(repo):
    repo.closures.append({"chatbot_id": BOT, "package_id": None, "closed_on": "2026-10-05"})

    assert _offered(repo) == []


def test_full_slots_are_not_offered_and_partly_booked_show_seats_left(repo):
    _offered(repo)  # generates the Monday slots
    repo.slots[0]["booked_seats"] = 2   # 10:00 is full
    repo.slots[1]["booked_seats"] = 1   # 11:00 has one seat left

    assert _offered(repo) == [(5, "2026-10-05T03:00:00+00:00", 1)]


def test_a_switched_off_package_offers_nothing(repo):
    repo.packages[0]["enabled"] = False

    assert _offered(repo) == []


def test_times_starting_too_soon_are_not_offered(repo):
    soon = datetime(2026, 10, 5, 1, 45, tzinfo=timezone.utc)  # Monday 09:45, 15 minutes before 10:00

    assert [s["starts_at"] for s in svc.open_slots(COMPANY, BOT, now=soon, days=1)] == ["2026-10-05T03:00:00+00:00"]


def test_overlapping_hour_blocks_make_one_time_each(repo, monkeypatch):
    repo.schedules.append(dict(repo.schedules[0], start_time="09:00:00"))  # 09:00-12:00 overlaps 10:00-12:00
    sent = []
    monkeypatch.setattr(repo, "insert_slots", sent.extend)

    svc.generate_slots(COMPANY, BOT, NOW)

    starts = [row["starts_at"] for row in sent]
    assert len(starts) == len(set(starts)) == 12  # 09:00, 10:00, 11:00 on the four Mondays ahead


def test_a_fully_booked_stretch_does_not_hide_later_open_times(repo, monkeypatch):
    monkeypatch.setattr(svc, "SCAN_PER_PACKAGE", 2)
    svc.generate_slots(COMPANY, BOT, NOW)
    for slot in sorted(repo.slots, key=lambda s: s["starts_at"])[:4]:  # 5 and 12 Oct, all full
        slot["booked_seats"] = slot["capacity"]

    offered = svc.open_slots(COMPANY, BOT, now=NOW, days=28)

    assert offered[0]["starts_at"] == "2026-10-19T02:00:00+00:00"  # Monday 19 Oct, 10:00
