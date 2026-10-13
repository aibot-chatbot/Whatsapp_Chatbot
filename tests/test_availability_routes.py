"""The owner's availability API: Pro only, own company only, admins write, rules enforced.

Seam: the HTTP endpoints through the real Flask app and real token authentication. Only
the availability repository (an in-memory stand-in), the plan gate and chatbot ownership
are replaced, so validation, roles and tenant scoping are genuinely exercised.
"""

from datetime import datetime, timezone

import jwt
import pytest

import app as app_module
from app.decorators import auth_decorator
from app.routes import availability_routes
from app.services import availability_service

USERS = {
    17: {"id": 17, "company_id": 7, "role": "admin", "status": "active"},
    18: {"id": 18, "company_id": 7, "role": "member", "status": "active"},
}
SECRET = "synthetic-availability-test-secret-32-bytes"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)  # Sunday 4 Oct, 20:00 Malaysia time


class Store:
    def __init__(self):
        self.packages, self.schedules, self.closures, self.slots, self.closed = [], [], [], [], []

    def list_packages(self, company_id, chatbot_id):
        return [p for p in self.packages if (p["company_id"], p["chatbot_id"]) == (company_id, chatbot_id)]

    def get_package(self, company_id, package_id):
        return next((p for p in self.packages if p["id"] == package_id and p["company_id"] == company_id), None)

    def create_package(self, row):
        package = dict(row, id=len(self.packages) + 1, version=1)
        self.packages.append(package)
        return package

    def update_package(self, company_id, package_id, expected_version, changes):
        package = self.get_package(company_id, package_id)
        if not package or package["version"] != expected_version:
            return None
        package.update(changes, version=expected_version + 1)
        return package

    def list_schedules_for_chatbot(self, company_id, chatbot_id):
        return [s for s in self.schedules if s["chatbot_id"] == chatbot_id]

    def replace_schedules(self, company_id, chatbot_id, package_id, rows):
        self.schedules = [s for s in self.schedules if s["package_id"] != package_id] + list(rows)

    def list_closures(self, company_id, chatbot_id, from_date):
        return [c for c in self.closures if c["chatbot_id"] == chatbot_id and c["closed_on"] >= from_date]

    def add_closure(self, row):
        closure = dict(row, id=len(self.closures) + 1)
        self.closures.append(closure)
        return closure

    def close_slots_between(self, company_id, chatbot_id, start_iso, end_iso, package_id=None):
        self.closed.append((start_iso, end_iso, package_id))

    def latest_schedule_slot_start(self, company_id, chatbot_id):
        return None

    def insert_slots(self, rows):
        self.slots.extend(dict(r, id=len(self.slots) + 1, booked_seats=0, status="open") for r in rows)

    def delete_future_unbooked_schedule_slots(self, company_id, chatbot_id, package_id, from_iso):
        self.slots = [s for s in self.slots if s["package_id"] != package_id or s["booked_seats"] > 0]

    def create_slot(self, row):
        slot = dict(row, id=len(self.slots) + 1, booked_seats=0, status="open", version=1)
        self.slots.append(slot)
        return slot

    def get_slot(self, company_id, chatbot_id, slot_id):
        return next((s for s in self.slots if s["id"] == slot_id and s["chatbot_id"] == chatbot_id), None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False))
    monkeypatch.setattr(auth_decorator, "get_jwt_secret", lambda: SECRET)
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda user_id: USERS.get(user_id))
    monkeypatch.setattr("app.services.company_status_service.ensure_company_operational", lambda company_id: None)
    application = app_module.create_app()
    application.config["TESTING"] = True
    return application.test_client()


@pytest.fixture
def store(monkeypatch):
    fake = Store()
    monkeypatch.setattr(availability_service, "repo", fake)
    monkeypatch.setattr(availability_service, "_now", lambda: NOW)
    monkeypatch.setattr(availability_service, "is_enabled", lambda company_id: company_id == 7)

    def own_chatbot_only(chatbot_id):
        if chatbot_id != 3:
            raise PermissionError("You do not have access to this chatbot.")
        return {"id": chatbot_id, "company_id": 7}

    monkeypatch.setattr(availability_routes, "verify_chatbot_access", own_chatbot_only)
    return fake


def auth(user_id=17):
    return {"Authorization": "Bearer " + jwt.encode({"user_id": user_id}, SECRET, algorithm="HS256")}


HAIRCUT = {"chatbot_id": 3, "name": "Haircut", "duration_minutes": 60, "price_mode": "fixed",
           "price_myr": "35.00", "seats_per_slot": 2}


@pytest.mark.parametrize("method,path", [("get", "/api/bookings/availability?chatbot_id=3"),
                                         ("post", "/api/bookings/packages"),
                                         ("put", "/api/bookings/packages/1/hours"),
                                         ("post", "/api/bookings/closures")])
def test_every_endpoint_requires_a_signed_in_user(client, store, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_a_company_without_pro_is_told_it_is_a_pro_feature(client, store, monkeypatch):
    monkeypatch.setattr(availability_service, "is_enabled", lambda company_id: False)

    response = client.post("/api/bookings/packages", json=HAIRCUT, headers=auth())

    assert response.status_code == 403 and response.get_json()["code"] == "feature_not_available"
    assert store.packages == []


def test_members_cannot_change_packages(client, store):
    assert client.post("/api/bookings/packages", json=HAIRCUT, headers=auth(18)).status_code == 403


def test_an_admin_creates_a_package_for_their_own_company(client, store):
    response = client.post("/api/bookings/packages", json=dict(HAIRCUT, company_id=8), headers=auth())

    assert response.status_code == 201
    package = store.packages[0]
    assert (package["company_id"], package["chatbot_id"], package["price_micro_myr"]) == (7, 3, 35_000_000)


def test_a_fixed_price_needs_an_amount(client, store):
    response = client.post("/api/bookings/packages", json=dict(HAIRCUT, price_myr=None), headers=auth())

    assert response.status_code == 400 and store.packages == []


def test_another_chatbot_is_refused(client, store):
    assert client.post("/api/bookings/packages", json=dict(HAIRCUT, chatbot_id=4), headers=auth()).status_code == 403


def test_weekly_hours_replace_the_old_ones_and_create_bookable_times(client, store):
    client.post("/api/bookings/packages", json=HAIRCUT, headers=auth())

    response = client.put("/api/bookings/packages/1/hours", headers=auth(), json={"hours": [
        {"weekday": 1, "start": "10:00", "end": "12:00", "interval_minutes": 60}]})

    assert response.status_code == 200
    assert [(s["weekday"], s["start_time"], s["end_time"]) for s in store.schedules] == [(1, "10:00", "12:00")]
    assert "2026-10-05T02:00:00+00:00" in [s["starts_at"] for s in store.slots]  # Monday 10:00 Malaysia time


def test_hours_that_end_before_they_start_are_refused(client, store):
    client.post("/api/bookings/packages", json=HAIRCUT, headers=auth())

    response = client.put("/api/bookings/packages/1/hours", headers=auth(), json={"hours": [
        {"weekday": 1, "start": "12:00", "end": "10:00", "interval_minutes": 60}]})

    assert response.status_code == 400 and store.schedules == []


def test_a_one_off_time_in_the_past_is_refused(client, store):
    client.post("/api/bookings/packages", json=HAIRCUT, headers=auth())

    response = client.post("/api/bookings/slots", headers=auth(),
                           json={"package_id": 1, "starts_at": "2026-10-01 10:00"})

    assert response.status_code == 400


def test_a_one_off_time_uses_the_package_seats(client, store):
    client.post("/api/bookings/packages", json=HAIRCUT, headers=auth())

    response = client.post("/api/bookings/slots", headers=auth(),
                           json={"package_id": 1, "starts_at": "2026-10-10 15:00"})

    assert response.status_code == 201
    slot = store.slots[-1]
    assert (slot["starts_at"], slot["capacity"], slot["source"]) == ("2026-10-10T07:00:00+00:00", 2, "one_off")


def test_a_chatbot_has_at_most_25_packages(client, store):
    for number in range(25):
        assert client.post("/api/bookings/packages", json=dict(HAIRCUT, name=f"P{number}"), headers=auth()).status_code == 201

    response = client.post("/api/bookings/packages", json=dict(HAIRCUT, name="One too many"), headers=auth())

    assert response.status_code == 400 and len(store.packages) == 25


def test_reopening_one_closure_keeps_a_day_another_closure_still_covers(client, store, monkeypatch):
    store.closures = [{"id": 1, "company_id": 7, "chatbot_id": 3, "package_id": None, "closed_on": "2026-10-05"},
                      {"id": 2, "company_id": 7, "chatbot_id": 3, "package_id": 1, "closed_on": "2026-10-05"}]
    reopened = []
    monkeypatch.setattr(store, "delete_closure", lambda company_id, closure_id, s=store: next(
        s.closures.pop(i) for i, c in enumerate(s.closures) if c["id"] == closure_id), raising=False)
    monkeypatch.setattr(store, "reopen_schedule_slots_between", lambda *a, **k: reopened.append(a), raising=False)

    assert client.delete("/api/bookings/closures/2", headers=auth()).status_code == 200
    assert reopened == []  # the whole chatbot is still closed that day


def test_closing_a_date_closes_that_days_open_times(client, store):
    response = client.post("/api/bookings/closures", headers=auth(),
                           json={"chatbot_id": 3, "closed_on": "2026-10-05", "reason": "Public holiday"})

    assert response.status_code == 201
    # Malaysia midnight to midnight
    assert store.closed == [("2026-10-04T16:00:00+00:00", "2026-10-05T16:00:00+00:00", None)]
