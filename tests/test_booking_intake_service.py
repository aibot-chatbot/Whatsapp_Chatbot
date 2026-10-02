"""Chat intake: the hidden marker in a model reply becomes a 'requested' booking, and never reaches the customer.

Seam: booking_intake_service.process_reply / extract_request / prompt_section. The recorder
(booking_service.record_chat_request) and the bot lookup are replaced; everything the model can
influence is parsed for real.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import booking_intake_service as svc
from app.services.booking_service import BookingValidationError
from app.services.response_formatter import clean_ai_reply

FIELDS = {"kind": "reservation", "service": "Dinner for four", "when": "2026-10-05 19:00",
          "party_size": 4, "name": "Ada", "notes": "Window seat"}
MARKER = "<<BOOKING " + json.dumps(FIELDS) + ">>"
BOT = {"id": 7, "company_id": 42, "booking_intake_enabled": True}
CONVERSATION = {"id": 55, "source_channel": "whatsapp"}


@pytest.fixture
def recorder(monkeypatch):
    record = Mock(return_value={"id": 9})
    monkeypatch.setattr(svc.booking_service, "record_chat_request", record)
    return record


def run(reply, bot=BOT, conversation=CONVERSATION, customer_id="60123456789", channel="whatsapp", **options):
    return svc.process_reply(reply, bot=bot, conversation=conversation, customer_id=customer_id,
                             channel=channel, **options)


# --- extracting the marker ------------------------------------------------------

def test_the_marker_is_removed_and_its_fields_returned():
    clean, fields = svc.extract_request("Your request is noted.\n" + MARKER)

    assert clean == "Your request is noted."
    assert fields == FIELDS


def test_a_marker_in_the_middle_leaves_the_text_around_it():
    clean, fields = svc.extract_request("Before. " + MARKER + " After.")

    assert "BOOKING" not in clean and "Before." in clean and "After." in clean
    assert fields == FIELDS


def test_the_marker_is_case_insensitive_and_whitespace_tolerant():
    clean, fields = svc.extract_request('ok <<  booking\n{"service": "Haircut"}\n>>')

    assert clean == "ok" and fields == {"service": "Haircut"}


def test_a_double_angle_inside_a_value_does_not_leak_the_rest():
    reply = 'Done. <<BOOKING {"service": "A >> B", "notes": "x"}>>'

    clean, fields = svc.extract_request(reply)

    assert clean == "Done." and fields["service"] == "A >> B"


def test_a_malformed_marker_is_removed_and_gives_no_fields():
    clean, fields = svc.extract_request('Sent. <<BOOKING {"service": "Dinner",>> Thanks!')

    assert "BOOKING" not in clean and "Dinner" not in clean and fields is None
    assert clean.startswith("Sent.") and clean.endswith("Thanks!")


@pytest.mark.parametrize("opener", ["<<BOOKINGS", "<<BOOKING_REQUEST", "<<​BOOKING", "<<⁠ booking", "<<  Booking"])
def test_near_miss_openers_are_removed_too(opener):
    clean, fields = svc.extract_request('Done. ' + opener + ' {"service": "Cut"}>>')

    assert clean == "Done." and fields == {"service": "Cut"}


def test_a_malformed_marker_with_a_double_angle_inside_a_value_leaks_nothing():
    reply = 'Sent! <<BOOKING {"service": "Cut >> Wash", "name": "Ada Lim", "notes": "allergic",}>>'

    clean, fields = svc.extract_request(reply)

    assert clean == "Sent!" and fields is None


def test_a_malformed_marker_only_costs_its_own_line():
    clean, fields = svc.extract_request('Use the <<booking form {oops\nOur hours are 9-5.')

    assert fields is None and "booking" not in clean and "oops" not in clean
    assert "Our hours are 9-5." in clean


def test_markers_on_several_lines_each_lose_only_their_own_line():
    reply = 'One\n<<BOOKING {"service": "A"}>>\nTwo\n<<BOOKING {broken\nThree'

    clean, fields = svc.extract_request(reply)

    assert fields == {"service": "A"}
    assert [line for line in clean.splitlines() if line] == ["One", "Two", "Three"]


def test_spaces_in_the_rest_of_the_reply_are_left_alone():
    clean, _ = svc.extract_request('Menu:   soup    salad\n<<BOOKING {"service": "A"}>>')

    assert clean == "Menu:   soup    salad"


def test_an_unclosed_marker_is_removed_to_the_end():
    clean, fields = svc.extract_request('Sent. <<BOOKING {"service": "Dinner"')

    assert clean == "Sent." and fields is None


def test_the_first_valid_marker_wins_and_all_are_removed():
    first = '<<BOOKING {"service": "First"}>>'
    second = '<<BOOKING {"service": "Second"}>>'

    clean, fields = svc.extract_request(f"A {first} B {second} C")

    assert fields == {"service": "First"} and "BOOKING" not in clean


@pytest.mark.parametrize("payload", ['[1, 2]', '"text"', '42', 'null'])
def test_a_marker_that_is_not_a_json_object_gives_no_fields(payload):
    clean, fields = svc.extract_request(f"ok <<BOOKING {payload}>>")

    assert clean == "ok" and fields is None


@pytest.mark.parametrize("value", [None, "", "Plain reply, no marker."])
def test_a_reply_without_a_marker_is_unchanged(value):
    assert svc.extract_request(value) == ((value or ""), None)


def test_a_non_text_reply_is_passed_through_untouched():
    sentinel = SimpleNamespace(text="handoff")

    assert svc.process_reply(sentinel, bot=BOT, conversation=CONVERSATION, customer_id="1", channel="whatsapp") is sentinel


# --- recording --------------------------------------------------------------------

def test_an_enabled_bot_records_with_scope_taken_from_the_server(recorder):
    reply = run("Noted!\n" + MARKER)

    assert reply == "Noted!\n\n" + svc._ACKNOWLEDGEMENT
    kwargs = recorder.call_args.kwargs
    assert (kwargs["company_id"], kwargs["chatbot_id"], kwargs["conversation_id"]) == (42, 7, 55)
    assert kwargs["channel"] == "whatsapp"
    assert kwargs["customer_phone"] == "+60123456789" and kwargs["customer_ref"] == "60123456789"
    assert kwargs["fields"] == FIELDS


def test_the_model_cannot_choose_the_tenant(recorder):
    hostile = dict(FIELDS, company_id=999, chatbot_id=1, conversation_id=2, status="confirmed", source="staff")

    run("ok <<BOOKING " + json.dumps(hostile) + ">>")

    kwargs = recorder.call_args.kwargs
    assert (kwargs["company_id"], kwargs["chatbot_id"], kwargs["conversation_id"]) == (42, 7, 55)


def test_a_disabled_bot_strips_the_marker_and_records_nothing(recorder):
    reply = run("Noted! " + MARKER, bot=dict(BOT, booking_intake_enabled=False))

    assert reply == "Noted!"
    recorder.assert_not_called()


@pytest.mark.parametrize("flag", [None, "true", 1, "yes"])
def test_only_a_real_true_enables_intake(recorder, flag):
    run("Noted! " + MARKER, bot=dict(BOT, booking_intake_enabled=flag))

    recorder.assert_not_called()


def test_without_a_verified_conversation_nothing_is_recorded_and_the_customer_is_told(recorder):
    reply = run("Noted! " + MARKER, conversation=None)

    assert reply == svc._NOT_RECORDED
    recorder.assert_not_called()


@pytest.mark.parametrize("channel,customer_id,phone,ref", [
    ("whatsapp", "60123456789", "+60123456789", "60123456789"),
    ("wasender", "+60 12-345 6789", "+60123456789", "+60 12-345 6789"),
    ("telegram", "123456789", None, "123456789"),
    ("web", "visitor-abc", None, None),   # a widget session id is a capability, never stored or exported
    ("whatsapp", "not-a-number", None, "not-a-number"),
    ("whatsapp", None, None, None),       # a missing id is stored as nothing, never as the text "None"
])
def test_only_phone_channels_produce_a_phone_number_and_only_stable_ids_are_kept(
        recorder, channel, customer_id, phone, ref):
    run("ok " + MARKER, customer_id=customer_id, channel=channel)

    assert recorder.call_args.kwargs["customer_phone"] == phone
    assert recorder.call_args.kwargs["customer_ref"] == ref


# --- the customer is only told "sent" when it really was ------------------------------

@pytest.mark.parametrize("failure", [
    ("a rejected request", {"side_effect": BookingValidationError("needs a service or a time")}),
    ("an unexpected failure", {"side_effect": RuntimeError("db down")}),
    ("a request over a limit", {"return_value": None}),
], ids=lambda case: case[0])
def test_a_request_that_was_not_recorded_never_leaves_the_customer_believing_it_was(recorder, failure):
    recorder.configure_mock(**failure[1])

    reply = run("Great, it has been sent to the team! " + MARKER)

    assert reply == svc._NOT_RECORDED
    assert "has been sent" not in reply.lower() and "contact the team" in reply.lower()


def test_a_malformed_marker_is_also_never_reported_as_sent(recorder):
    reply = run('All done, sent to the team. <<BOOKING {"service": "Cut",>>')

    assert reply == svc._NOT_RECORDED
    recorder.assert_not_called()


def test_a_recorded_request_is_acknowledged_by_the_server_not_the_model(recorder):
    assert run(MARKER) == svc._ACKNOWLEDGEMENT
    assert "not confirmed" in svc._ACKNOWLEDGEMENT.lower()


@pytest.mark.parametrize("wrapped", ["**{m}**", "### {m}", "__{m}__", "```\n{m}\n```", "`{m}`", "> {m}"])
def test_a_marker_wrapped_in_markdown_still_yields_a_readable_reply(recorder, wrapped):
    reply = run(wrapped.format(m=MARKER), tidy=clean_ai_reply)

    assert reply == svc._ACKNOWLEDGEMENT, repr(reply)
    recorder.assert_called_once()


def test_the_marker_is_read_before_the_cleaner_can_rewrite_its_json(recorder):
    tricky = '<<BOOKING {"service": "Dinner __ Lunch", "notes": "**window**"}>>'

    run("Thanks Ada! " + tricky, tidy=clean_ai_reply)

    assert recorder.call_args.kwargs["fields"]["service"] == "Dinner __ Lunch"
    assert recorder.call_args.kwargs["fields"]["notes"] == "**window**"


def test_the_cleaner_still_tidies_a_reply_without_a_marker():
    assert run("**Hello**  there", tidy=clean_ai_reply) == "Hello  there"


def test_a_test_chat_strips_the_marker_records_nothing_and_says_so(recorder):
    reply = run("Thanks Ada! " + MARKER, record=False)

    assert reply == "Thanks Ada!\n\n" + svc._TEST_NOTE
    recorder.assert_not_called()


def test_a_disabled_bot_that_emits_a_marker_alone_is_not_claimed_to_have_recorded_it(recorder):
    reply = run(MARKER, bot=dict(BOT, booking_intake_enabled=False))

    assert reply == svc._NOT_RECORDED
    recorder.assert_not_called()


# --- the prompt addition -------------------------------------------------------------

def test_the_prompt_section_is_empty_unless_the_bot_is_enabled(monkeypatch):
    monkeypatch.setattr(svc, "get_bot_by_id", lambda bot_id: dict(BOT, booking_intake_enabled=False))
    assert svc.prompt_section(7) == ""

    monkeypatch.setattr(svc, "get_bot_by_id", lambda bot_id: None)
    assert svc.prompt_section(7) == ""


def test_the_prompt_tells_the_model_not_to_claim_a_confirmation(monkeypatch):
    monkeypatch.setattr(svc, "get_bot_by_id", lambda bot_id: BOT)

    section = svc.prompt_section(7, now=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc))

    assert "2026-10-01" in section, "the model needs today's date to resolve 'tomorrow'"
    for needle in ("<<BOOKING", "not confirmed", "explicitly confirm", "Never claim"):
        assert needle in section, needle


def test_the_prompt_example_is_something_the_parser_accepts(monkeypatch):
    monkeypatch.setattr(svc, "get_bot_by_id", lambda bot_id: BOT)

    section = svc.prompt_section(7)
    start = section.index("<<BOOKING")
    example = section[start:section.index(">>", start) + 2]

    clean, fields = svc.extract_request(example)
    assert clean == "" and isinstance(fields, dict) and fields.get("service")


def test_a_failing_bot_lookup_leaves_the_prompt_unchanged(monkeypatch):
    def boom(bot_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "get_bot_by_id", boom)

    assert svc.prompt_section(7) == ""
