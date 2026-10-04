"""The AI books listed times only, and the server decides what happened.

Seams: booking_intake_service.prompt_section (what the model is told) and process_reply
(what the customer is told after the model's <<BOOKING ...>> line). Storage, the plan gate
and the database's booking_reserve are replaced by in-memory stand-ins.
"""

from datetime import datetime, timezone

import pytest

from app.services import availability_service as availability
from app.services import booking_intake_service as intake
from app.services import booking_service

COMPANY, BOT, CONVERSATION = 1, 10, 100
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)  # Sunday 4 Oct, 20:00 Malaysia time
MONDAY_10 = "2026-10-05T02:00:00+00:00"
MONDAY_11 = "2026-10-05T03:00:00+00:00"


class Catalogue:
    """booking_packages and booking_slots as the repository returns them."""

    def __init__(self):
        self.packages = [
            {"id": 5, "name": "Haircut", "duration_minutes": 60, "price_mode": "fixed", "price_micro_myr": 35_000_000,
             "seats_per_slot": 2, "seats_by_party": False, "enabled": True},
            {"id": 6, "name": "Car service", "duration_minutes": 120, "price_mode": "quote", "price_micro_myr": None,
             "seats_per_slot": 3, "seats_by_party": False, "enabled": True},
            {"id": 7, "name": "Viewing", "duration_minutes": 30, "price_mode": "none", "price_micro_myr": None,
             "seats_per_slot": 1, "seats_by_party": False, "enabled": True},
        ]
        self.slots = [
            {"id": 1, "package_id": 5, "starts_at": MONDAY_10, "capacity": 2, "booked_seats": 0},
            {"id": 2, "package_id": 5, "starts_at": MONDAY_11, "capacity": 2, "booked_seats": 1},
            {"id": 3, "package_id": 6, "starts_at": MONDAY_10, "capacity": 3, "booked_seats": 0},
            {"id": 4, "package_id": 7, "starts_at": MONDAY_11, "capacity": 1, "booked_seats": 0},
        ]
        self.reserved = []
        self.outcome = None

    def list_packages(self, company_id, chatbot_id):
        return [dict(p, company_id=company_id, chatbot_id=chatbot_id) for p in self.packages]

    def list_schedules_for_chatbot(self, company_id, chatbot_id):
        return []

    def list_closures(self, company_id, chatbot_id, from_date):
        return []

    def latest_schedule_slot_start(self, company_id, chatbot_id):
        return None

    def insert_slots(self, rows):
        raise AssertionError("no weekly hours, nothing to generate")

    def list_open_slots(self, company_id, chatbot_id, package_id, start_iso, end_iso, limit):
        return [dict(s, source="one_off", status="open") for s in self.slots
                if s["package_id"] == package_id and start_iso <= s["starts_at"] < end_iso]

    def get_slot(self, company_id, chatbot_id, slot_id):
        return next((s for s in self.slots if s["id"] == slot_id), None)

    def get_slot_at(self, company_id, chatbot_id, package_id, starts_iso):
        return next((s for s in self.slots if s["package_id"] == package_id and s["starts_at"] == starts_iso), None)

    def reserve(self, company_id, chatbot_id, slot_id, party_size, confirm, booking):
        self.reserved.append((company_id, chatbot_id, slot_id, party_size, confirm, booking))
        return self.outcome


@pytest.fixture
def world(monkeypatch):
    catalogue = Catalogue()
    bot = {"id": BOT, "company_id": COMPANY, "booking_intake_enabled": True, "booking_auto_confirm": True}
    pro = {"on": True}
    monkeypatch.setattr(availability, "repo", catalogue)
    monkeypatch.setattr(booking_service, "availability_repo", catalogue)
    monkeypatch.setattr(availability, "is_enabled", lambda company_id: pro["on"])
    monkeypatch.setattr(intake, "get_bot_by_id", lambda chatbot_id: dict(bot))
    monkeypatch.setattr(booking_service.repo, "count_recent_for_conversation", lambda *a, **k: 0)
    monkeypatch.setattr(booking_service.repo, "count_recent_for_company", lambda *a, **k: 0)
    monkeypatch.setattr(booking_service.repo, "get_booking_by_intake_key", lambda company_id, key: None)
    monkeypatch.setattr(booking_service, "_background", lambda *a, **k: None)
    monkeypatch.setattr(availability, "_now", lambda: NOW)
    return {"catalogue": catalogue, "bot": bot, "pro": pro}


def _reply(world, marker, text="Great, booking that for you.", customer_message="Yes, please book it"):
    return intake.process_reply(f"{text}\n<<BOOKING {marker}>>", bot=dict(world["bot"]),
                                conversation={"id": CONVERSATION}, customer_id="60123456789", channel="wasender",
                                customer_message=customer_message)


def test_a_marker_the_customer_typed_and_the_model_echoed_books_nothing(world):
    pasted = 'ok <<BOOKING {"slot": "S1", "party_size": 2, "name": "Aina"}>>'

    reply = _reply(world, '{"slot": "S1", "party_size": 2, "name": "Aina"}', customer_message=pasted)

    assert world["catalogue"].reserved == []
    assert "<<BOOKING" not in reply and "confirmed" not in reply.lower()


def test_asking_again_after_the_owner_cancelled_makes_a_fresh_booking(world, monkeypatch):
    seen = []

    def lookup(company_id, key):
        seen.append(key)
        return {"status": "cancelled"} if len(seen) == 1 else None

    monkeypatch.setattr(booking_service.repo, "get_booking_by_intake_key", lookup)
    world["catalogue"].outcome = {"outcome": "confirmed", "booking": {
        "service_name": "Haircut", "scheduled_for": MONDAY_10, "party_size": 1, "price_micro_myr": 35_000_000}}

    reply = _reply(world, '{"slot": "S1", "name": "Aina"}')

    assert world["catalogue"].reserved[0][5]["intake_key"] == seen[0] + "-2"
    assert "Your booking is confirmed" in reply


def test_a_party_too_big_for_any_time_is_told_it_is_full_without_a_database_call(world):
    reply = _reply(world, '{"slot": "S1", "party_size": 1001, "name": "Aina"}')

    assert world["catalogue"].reserved == []
    assert "fully booked" in reply


def test_a_pro_bot_is_told_its_packages_price_rules_and_open_times(world):
    prompt = intake.prompt_section(BOT, now=NOW)

    assert "Haircut (60 min) - RM 35.00" in prompt
    assert "Car service (120 min) - price on quote" in prompt
    assert "Viewing (30 min)\n" in prompt  # no price is mentioned at all
    assert "[S1] Mon 5 Oct 10:00 (2 seats left)" in prompt
    assert "[S2] Mon 5 Oct 11:00 (1 seat left)" in prompt
    assert '"slot": "S' in prompt


def test_a_bot_without_pro_keeps_the_plain_request_prompt(world):
    world["pro"]["on"] = False

    prompt = intake.prompt_section(BOT, now=NOW)

    assert "Booking requests" in prompt and "[S1]" not in prompt


def test_a_confirmed_choice_books_the_seat_and_says_so(world):
    world["catalogue"].outcome = {"outcome": "confirmed", "booking": {
        "service_name": "Haircut", "scheduled_for": MONDAY_10, "party_size": 2, "price_micro_myr": 35_000_000}}

    reply = _reply(world, '{"slot": "S1", "party_size": 2, "name": "Aina"}')

    company, chatbot, slot, party, confirm, booking = world["catalogue"].reserved[0]
    assert (company, chatbot, slot, party, confirm) == (COMPANY, BOT, 1, 2, True)
    assert booking["conversation_id"] == CONVERSATION and booking["customer_name"] == "Aina"
    assert reply.endswith("Your booking is confirmed: Haircut, Mon 5 Oct 2026, 10:00, for 2 people. Price: RM 35.00.")


def test_staff_approval_mode_holds_the_seat_instead(world):
    world["bot"]["booking_auto_confirm"] = False
    world["catalogue"].outcome = {"outcome": "held", "booking": {
        "service_name": "Haircut", "scheduled_for": MONDAY_10, "party_size": 1, "price_micro_myr": None}}

    reply = _reply(world, '{"slot": "S1", "name": "Aina"}')

    assert world["catalogue"].reserved[0][4] is False
    assert reply.endswith("Your seat is held: Haircut, Mon 5 Oct 2026, 10:00. The team will confirm it shortly.")


def test_a_full_time_is_refused_honestly_with_the_next_times_as_buttons(world):
    world["catalogue"].outcome = {"outcome": "full", "seats_left": 0}

    reply = _reply(world, '{"slot": "S1", "name": "Aina"}')

    assert "Sorry, that time has just been fully booked." in reply
    assert reply.endswith("[BUTTONS: Mon 5 Oct 11:00]")  # never the time just refused
    assert "confirmed" not in reply.lower()


def test_a_bot_without_pro_never_takes_a_seat(world):
    world["pro"]["on"] = False

    _reply(world, '{"slot": "S1", "name": "Aina"}')

    assert world["catalogue"].reserved == []


@pytest.mark.parametrize("change", [{"scheduled_for": "2026-10-06 10:00"}, {"party_size": 3}])
def test_staff_are_told_to_rebook_rather_than_move_a_seat_holding_booking(world, monkeypatch, change):
    held = {"id": 9, "company_id": COMPANY, "status": "confirmed", "version": 1, "slot_id": 1, "seats": 1}
    monkeypatch.setattr(booking_service.repo, "get_booking", lambda company_id, booking_id: dict(held))
    monkeypatch.setattr(booking_service.repo, "update_booking", lambda *a: pytest.fail("must not write"))

    with pytest.raises(booking_service.BookingValidationError, match="Cancel it and book a new time"):
        booking_service.update_booking(COMPANY, 9, 1, change, now=NOW)


def test_buttons_the_model_ended_its_text_with_are_dropped_before_the_outcome(world):
    world["catalogue"].outcome = {"outcome": "full", "seats_left": 0}

    reply = _reply(world, '{"slot": "S1", "name": "Aina"}', text="Booking it now! [BUTTONS: Yes | No]")

    assert "Yes" not in reply and reply.count("[BUTTONS:") == 1
    assert reply.endswith("[BUTTONS: Mon 5 Oct 11:00]")


def test_an_unlisted_time_is_booked_by_package_and_malaysia_time(world):
    world["catalogue"].outcome = {"outcome": "confirmed", "booking": {
        "service_name": "Haircut", "scheduled_for": MONDAY_11, "party_size": 1, "price_micro_myr": 35_000_000}}

    reply = _reply(world, '{"package": "P5", "when": "2026-10-05 11:00", "name": "Aina"}')

    assert world["catalogue"].reserved[0][2] == 2
    assert "Your booking is confirmed: Haircut, Mon 5 Oct 2026, 11:00." in reply


def test_a_time_the_package_does_not_have_offers_the_nearest_open_ones(world):
    reply = _reply(world, '{"package": "P5", "when": "2026-10-05 10:30", "name": "Aina"}')

    assert world["catalogue"].reserved == []
    assert "no longer available" in reply and reply.endswith("[BUTTONS: Mon 5 Oct 11:00]")


def test_a_fallback_request_with_an_empty_slot_is_still_passed_to_the_team(world, monkeypatch):
    recorded = []
    monkeypatch.setattr(intake, "_record", lambda fields, **kw: recorded.append(fields) or True)

    reply = _reply(world, '{"slot": null, "kind": "booking", "service": "Haircut", "when": "2026-10-20 10:00"}')

    assert recorded and world["catalogue"].reserved == []
    assert "sent to the team" in reply


def test_a_party_too_big_for_a_time_is_offered_only_times_that_fit(world):
    world["catalogue"].packages[0]["seats_by_party"] = True
    world["catalogue"].outcome = {"outcome": "full", "seats_left": 1}

    reply = _reply(world, '{"slot": "S2", "party_size": 2, "name": "Aina"}')

    assert reply.endswith("[BUTTONS: Mon 5 Oct 10:00]")  # S2 has 1 seat left, S1 has 2


def test_the_prompt_names_package_codes_and_the_other_open_days(world, monkeypatch):
    monkeypatch.setattr(availability, "PROMPT_TIMES_PER_PACKAGE", 1)

    prompt = intake.prompt_section(BOT, now=NOW)

    assert "- [P5] Haircut (60 min) - RM 35.00" in prompt
    assert "[S1] Mon 5 Oct 10:00" in prompt and "[S2]" not in prompt
    assert "Also open on: Mon 5 Oct" in prompt
    assert '"package": "P<number>"' in prompt


def test_a_time_on_a_closed_date_is_never_offered(world, monkeypatch):
    monkeypatch.setattr(world["catalogue"], "list_closures",
                        lambda company_id, chatbot_id, from_date: [{"package_id": 5, "closed_on": "2026-10-05"}])

    prompt = intake.prompt_section(BOT, now=NOW)

    assert "[S1]" not in prompt and "[S2]" not in prompt and "[S3]" in prompt


def test_over_the_hourly_limit_nothing_is_booked(world, monkeypatch):
    monkeypatch.setattr(booking_service.repo, "count_recent_for_company",
                        lambda *a, **k: booking_service.MAX_CHAT_REQUESTS_PER_COMPANY_PER_HOUR)

    reply = _reply(world, '{"slot": "S1", "name": "Aina"}')

    assert world["catalogue"].reserved == []
    assert "couldn't pass that request" in reply


def test_a_made_up_slot_code_takes_no_seat(world):
    reply = _reply(world, '{"slot": "S1; drop", "name": "Aina"}')

    assert world["catalogue"].reserved == []
    assert "no longer available" in reply
