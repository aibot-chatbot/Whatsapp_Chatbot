"""The bookings API: who may call it, that the company always comes from the token, and safe downloads.

Seam: the HTTP endpoints, through the real Flask app and real token authentication. Only the
database and mail boundaries are replaced, so auth and tenant scoping are genuinely exercised.
"""

from unittest.mock import Mock

import jwt
import pytest

import app as app_module
from app.decorators import auth_decorator
from app.routes import booking_routes
from app.services import booking_service

USERS = {
    17: {"id": 17, "company_id": 7, "role": "admin", "status": "active"},
    18: {"id": 18, "company_id": 7, "role": "member", "status": "active"},
    19: {"id": 19, "company_id": 8, "role": "admin", "status": "active"},
}
SECRET = "synthetic-booking-test-secret-value-32-bytes"
BOOKING = {"id": 9, "company_id": 7, "chatbot_id": 3, "status": "requested", "version": 1}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "configure_logging", lambda: None)
    monkeypatch.setattr(app_module, "load_configurations", lambda application: application.config.update(
        CORS_ORIGINS=["https://app.example.test"], RATELIMIT_ENABLED=False))
    monkeypatch.setattr(auth_decorator, "get_jwt_secret", lambda: SECRET)
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda user_id: USERS.get(user_id))
    monkeypatch.setattr("app.services.company_status_service.ensure_company_operational", lambda company_id: None)

    def no_network(*args, **kwargs):
        raise AssertionError("Booking route tests must not reach external services")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("httpx.Client.send", no_network)
    application = app_module.create_app()
    application.config["TESTING"] = True
    return application.test_client()


def auth(user_id=17):
    token = jwt.encode({"user_id": user_id}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def service(monkeypatch):
    stub = Mock(spec=["list_for_company", "update_booking", "set_intake_enabled", "BookingError",
                      "BookingValidationError", "BookingNotFound", "BookingConflict"])
    stub.set_intake_enabled.return_value = True
    stub.BookingError = booking_service.BookingError
    stub.BookingValidationError = booking_service.BookingValidationError
    stub.BookingNotFound = booking_service.BookingNotFound
    stub.BookingConflict = booking_service.BookingConflict
    stub.list_for_company.return_value = [dict(BOOKING)]
    stub.update_booking.return_value = dict(BOOKING, status="confirmed", version=2)
    monkeypatch.setattr(booking_routes, "booking_service", stub)

    def own_chatbot_only(chatbot_id):
        if chatbot_id != 3:
            raise PermissionError("You do not have access to this chatbot.")
        return {"id": chatbot_id}

    monkeypatch.setattr(booking_routes, "verify_chatbot_access", Mock(side_effect=own_chatbot_only))
    return stub


# --- authentication ----------------------------------------------------------

@pytest.mark.parametrize("method,path", [("get", "/api/bookings"), ("patch", "/api/bookings/9"),
                                         ("get", "/api/bookings/export.csv"), ("get", "/api/bookings/settings?chatbot_id=3"),
                                         ("put", "/api/bookings/settings")])
def test_every_endpoint_requires_a_signed_in_user(client, service, method, path):
    assert getattr(client, method)(path).status_code == 401


# --- list -------------------------------------------------------------------

def test_list_uses_the_company_from_the_token_never_the_query(client, service):
    response = client.get("/api/bookings?company_id=999&status=requested", headers=auth(17))

    assert response.status_code == 200
    assert response.get_json()["data"]["bookings"] == [BOOKING]
    assert service.list_for_company.call_args.args[0] == 7
    assert service.list_for_company.call_args.kwargs["status"] == "requested"


def test_list_for_a_chatbot_checks_the_chatbot_belongs_to_the_company(client, service):
    assert client.get("/api/bookings?chatbot_id=3", headers=auth(17)).status_code == 200
    denied = client.get("/api/bookings?chatbot_id=4", headers=auth(17))

    assert denied.status_code == 403
    assert service.list_for_company.call_count == 1


def test_a_bad_filter_is_a_400(client, service):
    service.list_for_company.side_effect = booking_service.BookingValidationError("Unknown status.")

    response = client.get("/api/bookings?status=nonsense", headers=auth(17))

    assert response.status_code == 400 and response.get_json()["message"] == "Unknown status."


def test_an_unexpected_failure_does_not_leak_its_message(client, service):
    service.list_for_company.side_effect = RuntimeError("relation service_bookings does not exist at db.internal")

    response = client.get("/api/bookings", headers=auth(17))

    assert response.status_code == 500
    assert "service_bookings" not in response.get_data(as_text=True)


# --- update -----------------------------------------------------------------

def test_staff_can_confirm_a_booking(client, service):
    response = client.patch("/api/bookings/9", json={"expected_version": 1, "status": "confirmed"}, headers=auth(18))

    assert response.status_code == 200
    assert response.get_json()["data"]["booking"]["status"] == "confirmed"
    args = service.update_booking.call_args.args
    assert args[:3] == (7, 9, 1) and args[3] == {"status": "confirmed"}, "company from token; version not in changes"


def test_the_company_in_the_body_is_ignored(client, service):
    client.patch("/api/bookings/9", json={"expected_version": 1, "status": "confirmed", "company_id": 8}, headers=auth(17))

    args = service.update_booking.call_args.args
    assert args[0] == 7 and "company_id" in args[3], "the service rejects it; the route never lets it choose the tenant"


@pytest.mark.parametrize("body", [{}, {"status": "confirmed"}, {"expected_version": "1", "status": "confirmed"},
                                  {"expected_version": 0, "status": "confirmed"}, {"expected_version": True},
                                  {"expected_version": 1}])
def test_an_update_needs_a_valid_version_and_something_to_change(client, service, body):
    assert client.patch("/api/bookings/9", json=body, headers=auth(17)).status_code == 400
    service.update_booking.assert_not_called()


@pytest.mark.parametrize("raised,status", [(booking_service.BookingNotFound("nope"), 404),
                                           (booking_service.BookingConflict("changed"), 409),
                                           (booking_service.BookingValidationError("bad"), 400)])
def test_service_errors_map_to_http_statuses(client, service, raised, status):
    service.update_booking.side_effect = raised

    response = client.patch("/api/bookings/9", json={"expected_version": 1, "status": "confirmed"}, headers=auth(17))

    assert response.status_code == status and response.get_json()["status"] == "error"


def test_a_body_that_is_not_a_json_object_is_a_400(client, service):
    assert client.patch("/api/bookings/9", data="[1,2]", headers={**auth(17), "Content-Type": "application/json"}).status_code == 400
    assert client.patch("/api/bookings/9", data="not json", headers={**auth(17), "Content-Type": "application/json"}).status_code == 400


def test_an_oversized_body_is_refused(client, service):
    huge = '{"expected_version":1,"notes":"' + "x" * 200_000 + '"}'

    response = client.patch("/api/bookings/9", data=huge, headers={**auth(17), "Content-Type": "application/json"})

    assert response.status_code == 413
    service.update_booking.assert_not_called()


# --- the CSV download -------------------------------------------------------

def test_the_download_is_a_private_non_executable_attachment(client, service, monkeypatch):
    build = Mock(return_value=b"\xef\xbb\xbfbooking_id\r\n")
    monkeypatch.setattr(booking_routes.bookings_csv_service, "build_company_csv", build)

    response = client.get("/api/bookings/export.csv", headers=auth(18))

    assert response.status_code == 200 and response.data == b"\xef\xbb\xbfbooking_id\r\n"
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert response.headers["Content-Disposition"] == 'attachment; filename="bookings.csv"'
    assert "no-store" in response.headers["Cache-Control"] and "private" in response.headers["Cache-Control"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    build.assert_called_once_with(7)


def test_each_company_downloads_only_its_own_file(client, service, monkeypatch):
    build = Mock(return_value=b"x")
    monkeypatch.setattr(booking_routes.bookings_csv_service, "build_company_csv", build)

    client.get("/api/bookings/export.csv?company_id=7", headers=auth(19))

    build.assert_called_once_with(8)


def test_a_chatbot_download_holds_only_that_chatbots_bookings(client, service, monkeypatch):
    build = Mock(return_value=b"x")
    monkeypatch.setattr(booking_routes.bookings_csv_service, "build_company_csv", build)

    response = client.get("/api/bookings/export.csv?chatbot_id=3", headers=auth(18))

    assert response.status_code == 200
    assert response.headers["Content-Disposition"] == 'attachment; filename="bookings-bot-3.csv"'
    build.assert_called_once_with(7, chatbot_id=3)


@pytest.mark.parametrize("query,status", [("chatbot_id=4", 403), ("chatbot_id=abc", 400), ("chatbot_id=0", 400)])
def test_a_chatbot_download_refuses_another_tenants_or_a_bad_chatbot(client, service, monkeypatch, query, status):
    build = Mock(return_value=b"x")
    monkeypatch.setattr(booking_routes.bookings_csv_service, "build_company_csv", build)

    response = client.get("/api/bookings/export.csv?" + query, headers=auth(17))

    assert response.status_code == status
    build.assert_not_called()


# --- the per-chatbot switch ---------------------------------------------------

def test_the_switch_state_is_read_from_the_chatbot(client, service, monkeypatch):
    monkeypatch.setattr(booking_routes, "get_bot_by_id",
                        lambda bot_id, company_id=None: {"id": bot_id, "booking_intake_enabled": True})

    response = client.get("/api/bookings/settings?chatbot_id=3", headers=auth(18))

    assert response.status_code == 200 and response.get_json()["data"] == {"chatbot_id": 3, "enabled": True}


def test_only_an_admin_can_change_the_switch(client, service):
    member = client.put("/api/bookings/settings", json={"chatbot_id": 3, "enabled": True}, headers=auth(18))
    admin = client.put("/api/bookings/settings", json={"chatbot_id": 3, "enabled": True}, headers=auth(17))

    assert member.status_code == 403 and admin.status_code == 200
    service.set_intake_enabled.assert_called_once_with(7, 3, True)


@pytest.mark.parametrize("body", [{"chatbot_id": 3}, {"chatbot_id": 3, "enabled": "yes"}, {"enabled": True},
                                  {"chatbot_id": "3", "enabled": True}])
def test_the_switch_needs_a_chatbot_and_a_real_boolean(client, service, body):
    assert client.put("/api/bookings/settings", json=body, headers=auth(17)).status_code == 400
    service.set_intake_enabled.assert_not_called()


def test_the_switch_cannot_touch_another_companys_chatbot(client, service):
    response = client.put("/api/bookings/settings", json={"chatbot_id": 4, "enabled": True}, headers=auth(17))

    assert response.status_code == 403
    service.set_intake_enabled.assert_not_called()


def test_a_chatbot_that_vanished_is_a_404(client, service):
    service.set_intake_enabled.return_value = False

    response = client.put("/api/bookings/settings", json={"chatbot_id": 3, "enabled": True}, headers=auth(17))

    assert response.status_code == 404


# --- query strings: a bad value is a 400, never silently "everything" -----------------

@pytest.mark.parametrize("query", ["chatbot_id=abc", "chatbot_id=0", "chatbot_id=-3", "limit=abc", "limit=0",
                                   "offset=-1", "offset=x", f"offset={booking_routes._MAX_OFFSET + 1}"])
def test_a_malformed_query_value_is_refused_not_ignored(client, service, query):
    response = client.get("/api/bookings?" + query, headers=auth(17))

    assert response.status_code == 400 and response.get_json()["status"] == "error"
    service.list_for_company.assert_not_called()


def test_sensible_query_values_pass_through_and_a_big_limit_is_left_to_the_repository_cap(client, service):
    response = client.get("/api/bookings?chatbot_id=3&limit=1000&offset=100&status=requested", headers=auth(17))

    assert response.status_code == 200
    kwargs = service.list_for_company.call_args.kwargs
    assert (kwargs["chatbot_id"], kwargs["limit"], kwargs["offset"], kwargs["status"]) == (3, 1000, 100, "requested")


@pytest.fixture
def real_service(monkeypatch):
    """The real booking_service rules over a stub repository, to prove bad input is a 400 and not a crash."""
    repo = Mock()
    repo.get_booking.return_value = {"id": 9, "company_id": 7, "status": "requested", "version": 1}
    repo.update_booking.return_value = {"id": 9, "status": "confirmed", "version": 2}
    monkeypatch.setattr(booking_service, "repo", repo)
    monkeypatch.setattr(booking_service, "refresh_company_csv", Mock())
    return repo


@pytest.mark.parametrize("body", [
    {"status": ["confirmed"]}, {"status": {"to": "confirmed"}}, {"status": 1}, {"kind": ["booking"]},
    {"scheduled_for": "0001-01-01 00:00"}, {"scheduled_for": 5}, {"scheduled_for": "2026-10-06"},
    {"customer_name": {"a": 1}}, {"notes": 5}, {"party_size": {"n": 1}}])
def test_malformed_edit_values_are_a_400_never_a_500(client, real_service, body):
    response = client.patch("/api/bookings/9", json={"expected_version": 1, **body}, headers=auth(17))

    assert response.status_code == 400, response.get_json()
    real_service.update_booking.assert_not_called()
