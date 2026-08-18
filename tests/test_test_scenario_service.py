"""Parsing guarantees for the Test lab's business-matched scenarios.

`build_test_scenarios` reaches a database and a model, so what is pinned here
is the pure half: everything that decides whether a model reply reaches the
operator's screen, and in what shape. That is where the failures live -- a
model that wraps the array in an object, drops a field, writes an essay, or
passes invisible characters through from a poisoned document.

"""

from app.services.test_scenario_service import (
    MAX_MESSAGE_CHARACTERS,
    SLOT_KEYS,
    parse_scenarios,
)

FOUR = """[
  {"name": "Order status", "goal": "Find the order and say where it is",
   "message": "hi, where is my order 8813?"},
  {"name": "Return window", "goal": "Quote the 14-day policy from the document",
   "message": "how long do i have to return a jacket?"},
  {"name": "Alterations", "goal": "Decline, we do not alter garments",
   "message": "can you take in the waist on these jeans?"},
  {"name": "Just says hi", "goal": "Ask what they are looking for",
   "message": "hello"}
]"""


def test_four_scenarios_keep_the_slot_order():
    scenarios = parse_scenarios(FOUR)

    assert [s["key"] for s in scenarios] == list(SLOT_KEYS)
    assert scenarios[0]["message"] == "hi, where is my order 8813?"


def test_keys_come_from_position_not_from_the_reply():
    # A model that invents its own keys must not be able to change which icon
    # the frontend draws, or which slot a scenario lands in.
    reply = """[
      {"key": "ecommerce_order", "name": "A", "message": "one"},
      {"key": "nonsense", "name": "B", "message": "two"}
    ]"""

    assert [s["key"] for s in parse_scenarios(reply)] == ["common", "fact"]


def test_an_object_wrapper_is_unwrapped():
    # Several models return {"scenarios": [...]} however the prompt is worded.
    reply = '{"scenarios": [{"name": "A", "goal": "g", "message": "one"}]}'

    assert len(parse_scenarios(reply)) == 1


def test_a_slot_with_no_message_is_dropped_whole():
    # A button that puts nothing in the composer is worse than three buttons.
    reply = '[{"name": "A", "message": "one"}, {"name": "B", "goal": "g"}]'
    scenarios = parse_scenarios(reply)

    assert len(scenarios) == 1
    assert scenarios[0]["name"] == "A"


def test_an_essay_is_clipped_to_a_message_a_person_would_type():
    reply = '[{"name": "A", "goal": "g", "message": "%s"}]' % ("word " * 200)
    scenarios = parse_scenarios(reply)

    assert len(scenarios[0]["message"]) <= MAX_MESSAGE_CHARACTERS


def test_invisible_characters_from_the_document_do_not_survive():
    # A bidi override inside a scenario name reorders what the operator reads
    # before they press Send. The document is untrusted; this is the guard.
    reply = (
        '[{"name": "Ref\\u202eund policy", "goal": "g",'
        ' "message": "do you\\u200b refund?"}]'
    )
    scenarios = parse_scenarios(reply)

    assert scenarios[0]["name"] == "Refund policy"
    assert scenarios[0]["message"] == "do you refund?"


def test_newlines_collapse_so_a_scenario_stays_one_line():
    reply = '[{"name": "A\\n\\nB", "goal": "g", "message": "one\\ntwo"}]'
    scenarios = parse_scenarios(reply)

    assert scenarios[0]["name"] == "A B"
    assert scenarios[0]["message"] == "one two"


def test_unusable_replies_fall_back_rather_than_raise():
    # Every one of these means "show the generic set", never an error page.
    for reply in ["", "   ", "Sorry, I cannot help with that.", "[", "{}",
                  "[1, 2, 3]", None, 42, '["a string", 7]']:
        assert parse_scenarios(reply) == [], reply


def test_a_markdown_fence_is_stripped():
    reply = '```json\n[{"name": "A", "goal": "g", "message": "one"}]\n```'

    assert len(parse_scenarios(reply)) == 1


def test_more_than_four_is_truncated_to_the_four_slots():
    reply = "[%s]" % ",".join(
        '{"name": "N%d", "goal": "g", "message": "m%d"}' % (i, i)
        for i in range(9)
    )

    assert len(parse_scenarios(reply)) == len(SLOT_KEYS)
