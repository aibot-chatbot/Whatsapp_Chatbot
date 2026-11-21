"""The reply prompt talks like a sales adviser: it finds out what the customer needs before
recommending, remembers what they said (the needs card), moves to booking when they are ready,
and never invents facts, without forcing one robotic sentence when something is missing.

Seam: rag_service.build_prompt. Deployed settings and the booking lookup are replaced.
"""

import pytest

from app.services import rag_service

OLD_FIXED_SENTENCE = "I don’t have that information in the provided company materials"
CUSTOM_PROMPTS = ["", "Reply as our course adviser: {message}"]


@pytest.fixture
def build(monkeypatch):
    settings = {"company_name": "Bright Tuition", "industry_template_published": {}}
    monkeypatch.setattr(rag_service, "get_deployed_settings",
                        lambda _: {**settings, "custom_prompt": settings.get("custom_prompt", "")})
    monkeypatch.setattr(rag_service.booking_intake_service, "prompt_section", lambda _, **kwargs: "")

    def _build(custom_prompt="", published=None, **options):
        settings["custom_prompt"] = custom_prompt
        settings["industry_template_published"] = published
        return rag_service.build_prompt([], "my son is weak in maths", [], 7, **options)

    return _build


@pytest.mark.parametrize("custom_prompt", CUSTOM_PROMPTS)
def test_every_prompt_carries_the_four_step_sales_conversation(build, custom_prompt):
    prompt = build(custom_prompt)

    for step in ("1. Understand:", "2. Recommend:", "3. Confirm:", "4. Close:"):
        assert step in prompt
    assert "reply in the customer's language" in prompt


@pytest.mark.parametrize("custom_prompt", CUSTOM_PROMPTS)
def test_accepts_the_first_no_without_repeating_the_offer(build, custom_prompt):
    rule = ("If they say no to an offer or say they are not interested, accept it the first time. "
            "Leave that offer out for the rest of this conversation and help with anything else they ask.")
    prompt = build(custom_prompt)
    assert prompt.count(rule) == 1
    assert rule in prompt.split("3. Confirm:", 1)[1].split("4. Close:", 1)[0]


@pytest.mark.parametrize("custom_prompt", CUSTOM_PROMPTS)
def test_what_the_customer_said_earlier_reaches_the_prompt(build, custom_prompt):
    prompt = build(custom_prompt, customer_needs={"goal": "Improve maths", "stage": "recommend"})

    assert "- Goal or problem: Improve maths" in prompt
    assert "Conversation stage: recommend" in prompt
    assert "<<NEEDS {" in prompt


def test_a_new_conversation_starts_by_understanding_the_customer(build):
    assert "Conversation stage: understand" in build()


@pytest.mark.parametrize("custom_prompt", CUSTOM_PROMPTS)
def test_missing_facts_are_never_invented_but_not_answered_with_one_fixed_sentence(build, custom_prompt):
    prompt = build(custom_prompt)

    assert "Do not invent prices, dates, contacts" in prompt
    assert "never guess it" in prompt
    assert OLD_FIXED_SENTENCE not in prompt


def test_the_close_step_comes_before_the_booking_rules_it_points_to(monkeypatch, build):
    monkeypatch.setattr(rag_service.booking_intake_service, "prompt_section",
                        lambda _: "\nBookings (switched on for this chatbot):\n")

    prompt = build()

    assert prompt.index("4. Close:") < prompt.index("Bookings (switched on for this chatbot):")


@pytest.mark.parametrize(("template_id", "topic"), [
    ("clinic", "doctor"), ("beauty_salon", "treatment results"),
    ("tuition_center", "grades"), ("property_agent", "approvals"),
    ("car_workshop", "inspection"), ("travel_agency", "visa"),
    ("restaurant", "allergies"), ("retail_shop", "stock"),
    ("general", "weighing options"), (None, "weighing options"),
    ("unknown", "weighing options"),
])
def test_industry_objections_are_static_private_rules_with_no_stated_promises(build, template_id, topic):
    from app.services.industry_template_catalog import industry_prompt
    from app.services.reply_promise_rules import promise_findings

    published = {"template_id": template_id, "template_version": "1.0.0"} if template_id else None
    prefixes = []
    for goal in ("planning a visit", "comparing prices"):
        rules = []
        prompt = build(published=published, customer_needs={"goal": goal}, internal_rules=rules)
        static, dynamic = prompt.split(rag_service.DYNAMIC_SECTION_HEADER)
        assert goal in dynamic
        matching = [rule for rule in rules if rule.startswith("Handling objections:")]
        assert len(matching) == 1
        objections = matching[0]
        assert topic in objections.lower()
        assert prompt.count(objections) == static.count(objections) == 1
        assert (industry_prompt(published) + "\n" + objections) in static
        assert promise_findings(objections, []) == []
        prefixes.append(static.encode("utf-8"))
    assert prefixes[0] == prefixes[1]
