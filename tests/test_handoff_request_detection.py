"""Acceptance tests for the model-free handoff detector (scenario H02).

`app.services.handoff_request_detection` is the escalation path's last line of
defence: it decides whether a customer asked for a human using text rules
alone, so a model or MCP outage can neither strand someone who asked for help
nor drag staff into a conversation nobody escalated.

There are no `xfail` markers left: every defect this suite found has been
fixed, and each one stayed behind as a passing regression case. Six of those
defects were a single class -- a token matched without checking what it
attaches to -- found in six different places over five rounds: `not` inside
`another`, a trailer negator contrasting a noun, a copula naming a new
subject, a retraction word with a complement, the same word with a subject,
and a Chinese negator separated from the phrase by its real object. When a
rule here is changed, that is the failure mode to look for first, and the
tests laid out as matched pairs below are where it shows up.
"""

# ruff: noqa: RUF001 -- CJK punctuation in test data is the thing under test

import pytest

from app.services.handoff_request_detection import (
    AMBIGUOUS,
    DECLINED,
    NONE,
    REQUESTED,
    button_handoff_request,
    detect_explicit_handoff_request,
)


# ── Plain requests ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("message", "language"),
    [
        ("Can I talk to a human please", "en"),
        ("我要转人工", "zh"),
        ("Saya nak bercakap dengan staf", "ms"),
    ],
    ids=[
        "an English customer asking to talk to a human is an explicit request",
        "a Chinese customer asking 转人工 is an explicit request",
        "a Malay customer asking to bercakap dengan staf is an explicit request",
    ],
)
def test_a_plain_request_is_an_explicit_request(message, language):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True
    assert signal.needs_clarification is False
    assert signal.language == language
    assert signal.matched_phrase


# ── The button path ───────────────────────────────────────────────────────


def test_pressing_the_handoff_button_is_a_request_without_parsing_any_text():
    # Arrange / Act
    signal = button_handoff_request()

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True
    assert signal.matched_phrase == "<button>"


def test_a_channel_without_buttons_produces_no_signal_at_all():
    # Arrange / Act
    signal = button_handoff_request(channel_supports_buttons=False)

    # Assert
    assert signal.decision == NONE
    assert signal.is_explicit_request is False
    assert signal.needs_clarification is False


# ── Refusals ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "don't transfer me to a human",
        "不要转人工",
        "jangan hubungkan saya",
        "No need to talk to a human, I found it",
    ],
    ids=[
        "an English customer refusing a transfer is declined",
        "a Chinese customer saying 不要转人工 is declined",
        "a Malay customer saying jangan hubungkan saya is declined",
        "a customer saying no need to talk to a human is declined",
    ],
)
def test_a_refusal_is_declined_and_is_never_treated_as_a_request(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == DECLINED
    assert signal.is_explicit_request is False
    assert signal.needs_clarification is False


# ── The clause rule, both directions ──────────────────────────────────────


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("I am not happy, please talk to a human", REQUESTED),
        ("please don't talk to a human", DECLINED),
        ("I don't like waiting. Please talk to a human", REQUESTED),
        ("I cannot log in. Please talk to a human.", REQUESTED),
        ("不要等了，转人工", REQUESTED),
        ("Saya tak nak bercakap dengan staf", DECLINED),
        ("talk to a human is not what I want", DECLINED),
        ("talk to a human isn't what I want", DECLINED),
        ("I want to talk to a human, not a bot", REQUESTED),
    ],
    ids=[
        "a negator in an earlier clause does not cancel an angry customer's request",
        "a negator in the same clause does cancel the request",
        "a negator in an earlier sentence does not cancel the request",
        "the word cannot in an earlier sentence does not cancel the request",
        "a Chinese comma ends the clause so 不要 does not reach 转人工",
        "a Malay negator in the same clause does cancel the request",
        "a negator after the phrase in the same clause does cancel the request",
        "a negative copula after the phrase does cancel the request",
        "a contrast in the next clause does not cancel the request",
    ],
)
def test_a_negator_only_counts_inside_the_clause_it_sits_in(message, expected):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == expected
    assert signal.is_explicit_request is (expected == REQUESTED)


# ── Quoted and reported speech ────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        'you said "talk to a human"',
        "你说要转人工",
        "kata awak nak staf manusia",
        'you said "talk to a human',
    ],
    ids=[
        "a quoted English phrase is somebody quoting the bot, not a request",
        "a Chinese reported-speech marker 你说 makes the phrase ambiguous",
        "a Malay reported-speech marker kata awak makes the phrase ambiguous",
        "an unclosed quotation mark still resolves to ambiguous, not a request",
    ],
)
def test_a_quoted_or_reported_phrase_needs_clarification(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == AMBIGUOUS
    assert signal.needs_clarification is True
    assert signal.is_explicit_request is False


# ── Existence questions ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "do you have human agents?",
        "有没有人工客服",
        "ada staf manusia?",
    ],
    ids=[
        "asking whether human agents exist is a question, not a request",
        "asking 有没有人工客服 is a question, not a request",
        "asking ada staf manusia is a question, not a request",
    ],
)
def test_an_existence_question_needs_clarification(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == AMBIGUOUS
    assert signal.needs_clarification is True
    assert signal.is_explicit_request is False


# ── Unrelated messages: no bare-keyword matching ──────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "Is a human reading this?",
        "Our sales agent will email you the invoice",
        "I spoke to your staff yesterday and they were lovely",
        "The travel agent booked the wrong date",
        "Where is my order?",
        "请问订单几时到",
        "Bila pesanan saya sampai?",
    ],
    ids=[
        "asking whether a human is reading does not match a bare human keyword",
        "the word agent in an innocent sense does not match",
        "the word staff in an innocent sense does not match",
        "a travel agent is not a support agent",
        "an ordinary English question produces no signal",
        "an ordinary Chinese question produces no signal",
        "an ordinary Malay question produces no signal",
    ],
)
def test_an_unrelated_message_produces_no_signal(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == NONE
    assert signal.is_explicit_request is False
    assert signal.needs_clarification is False


# ── Unusable input ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        None,
        "",
        "   ",
        "\n\t  ",
        42,
        ["talk to a human"],
        {"text": "转人工"},
        b"talk to a human",
    ],
    ids=[
        "None produces no signal without raising",
        "an empty string produces no signal without raising",
        "a whitespace-only message produces no signal without raising",
        "a message of only line breaks and tabs produces no signal without raising",
        "an integer produces no signal without raising",
        "a list produces no signal without raising",
        "a dict produces no signal without raising",
        "bytes produce no signal without raising",
    ],
)
def test_unusable_input_produces_no_signal_without_raising(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == NONE
    assert signal.is_explicit_request is False


# ── Adversarial: cases the module survives ────────────────────────────────


def test_a_mixed_script_malaysian_message_still_reaches_the_chinese_table():
    # Arrange
    message = "boleh tak 转人工"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- "boleh tak" is a question particle, not the negator "tak nak"
    assert signal.decision == REQUESTED
    assert signal.language == "zh"


def test_line_breaks_inside_a_request_are_normalised_away():
    # Arrange
    message = "Can I\n\ttalk to\na human"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.matched_phrase == "talk to a human"


def test_a_very_long_message_ending_in_a_request_is_still_a_request():
    # Arrange -- 10k characters of filler in front of the phrase
    message = ("please hurry " * 800) + ". Please talk to a human"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


def test_a_wall_of_apostrophes_does_not_crash_the_quote_scanner():
    # Arrange
    message = ("'" * 4000) + " talk to a human"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- the only requirement here is a decision, not a traceback
    assert signal.decision in (REQUESTED, AMBIGUOUS, DECLINED, NONE)


# ── Regression cover for rules that were once broken ─────────────────────
#
# Every test below pinned a real defect found by the adversarial pass. The
# module now passes them all; they stay so the fixes cannot be undone.


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("I can't wait, please talk to a human, it's urgent", REQUESTED),
        ("I don't want to talk to a human, it's fine", DECLINED),
    ],
    ids=[
        "contractions around a request must not turn it into a quotation",
        "contractions around a refusal must not turn it into a quotation",
    ],
)
def test_english_contractions_are_not_quotation_marks(message, expected):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == expected


@pytest.mark.parametrize(
    "message",
    [
        "I already spoke to another bot so please talk to a human",
        "I cannot solve this myself so please talk to a human",
    ],
    ids=[
        "the word another must not decline a request because it contains not",
        "the word cannot must not decline a request it does not negate",
    ],
)
def test_a_negator_hidden_inside_an_unrelated_word_does_not_decline(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


def test_a_line_break_ends_a_clause_like_the_boundary_table_says():
    # Arrange -- two lines of a WhatsApp message; the refusal is about the bot
    message = "I don't like this bot\nplease talk to a human"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


def test_a_clean_request_after_a_negated_phrase_is_still_a_request():
    # Arrange
    message = "I don't want you to escalate this, I want to talk to a human"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- declining here strands a customer who asked in so many words
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


@pytest.mark.parametrize(
    "message",
    [
        "do you have a human agent?",
        "is there a human agent available?",
    ],
    ids=[
        "an article after 'do you have' must not turn a question into a request",
        "an article after 'is there' must not turn a question into a request",
    ],
)
def test_an_existence_question_survives_an_article_before_the_phrase(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- escalating here pulls staff into a conversation nobody asked to escalate
    assert signal.decision == AMBIGUOUS
    assert signal.is_explicit_request is False


def test_the_malay_preposition_kepada_is_not_an_existence_question():
    # Arrange
    message = "Tolong hantar saya kepada staf manusia"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


def test_praising_customer_service_is_not_a_request_for_a_human():
    # Arrange
    message = "Your customer service is excellent, thank you"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- NONE or AMBIGUOUS are both defensible; REQUESTED is not
    assert signal.is_explicit_request is False


def test_a_bare_noun_phrase_on_its_own_is_still_a_request():
    # Arrange -- the counterweight to the test above: no topic, just an ask
    message = "customer service"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


# ── Rules introduced by the rewrite ──────────────────────────────────────


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("别转人工", DECLINED),
        ("特别想转人工", REQUESTED),
        ("特别转人工", REQUESTED),
    ],
    ids=[
        "the single character 别 immediately before the phrase is a refusal",
        "别 closing the compound 特别 is not a refusal",
        "特别 directly against the phrase is still not a refusal",
    ],
)
def test_a_single_character_chinese_negator_is_told_apart_from_its_compounds(
    message, expected
):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == expected
    assert signal.is_explicit_request is (expected == REQUESTED)


def test_the_last_decisive_phrase_wins_over_an_earlier_one():
    # Arrange -- a correction: the refusal is about the bot, the ask is final
    message = "don't transfer me to a bot, please talk to a human"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.matched_phrase == "talk to a human"


# ── Withdrawing an ask vs naming the alternative ─────────────────────────
#
# These two tests are a matched pair and must be read together. A retraction
# stands alone and cancels the request; a contrast names what the customer
# does NOT want instead, and is the most emphatic form of the request. Both
# sides have been broken at different times, in both directions.
#
# The whole rule is the minimal pair "no need now" (withdrawal, below) against
# "no need to rush" (a complement, so not a withdrawal -- next test down).
# Change one and check the other.


@pytest.mark.parametrize(
    "message",
    [
        "talk to a human, actually no need",
        "talk to a human. actually never mind",
        "talk to a human, no need now",
        "转人工，不用了",
    ],
    ids=[
        "an English retraction after a request must withdraw it",
        "an English change of mind after a request must withdraw it",
        "a bare no need plus filler must withdraw the request",
        "a Chinese retraction 不用了 after 转人工 must withdraw it",
    ],
)
def test_a_retraction_after_a_request_withdraws_it(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- escalating here pages staff the customer just told to stand down
    assert signal.decision == DECLINED
    assert signal.is_explicit_request is False


@pytest.mark.parametrize(
    "message",
    [
        "I want to talk to a human not a bot",
        "let me talk to a human not this bot",
        "I need to speak to a person not an AI",
        "Can I talk to a human without waiting so long",
        "transfer me without any more questions",
        "要人工不要机器人",
    ],
    ids=[
        "contrasting a human against a bot must not decline the request",
        "contrasting a human against this bot must not decline the request",
        "contrasting a person against an AI must not decline the request",
        "the adverb without must not decline a request it does not negate",
        "asking to be transferred without more questions is still a request",
        "a Chinese contrast 要人工不要机器人 must not decline the request",
    ],
)
def test_a_contrast_or_adverb_after_the_phrase_does_not_decline_it(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- these are the most emphatic way a customer asks for a human
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


@pytest.mark.parametrize(
    "message",
    [
        "talk to a human, no need to rush",
        "transfer me, no need to call back",
        "talk to a human, it's fine if it takes a while",
        "talk to a human, all good otherwise",
    ],
    ids=[
        "no need to rush withdraws the rush, not the request",
        "no need to call back withdraws the callback, not the request",
        "reassurance about the wait is not a withdrawal",
        "all good otherwise is a qualifier, not a withdrawal",
    ],
)
def test_a_retraction_of_something_else_does_not_withdraw_the_request(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- a real retraction stands alone; these all take a complement
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


@pytest.mark.parametrize(
    "message",
    [
        "I want to talk to a human the bot is not helping",
        "let me talk to a human this bot is not working",
    ],
    ids=[
        "a complaint about the bot after the phrase must not decline the request",
        "a complaint about this bot after the phrase must not decline the request",
    ],
)
def test_a_trailing_complaint_about_the_bot_does_not_decline_the_request(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- the phrase is only the subject when the copula directly follows it
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


def test_a_negative_copula_is_a_trailer_rule_and_not_lead_in_vocabulary():
    """Documents that the lead-in vocabulary deliberately excludes isn't.

    A negative copula negates the request only in the trailer construction
    where the phrase is the subject ("talk to a human isn't what I want",
    covered above). Putting isn't/aren't into the lead-in negator list
    instead would make this message DECLINED -- a refusal the customer never
    uttered, in the direction that strands them. The narrower trailer-only
    rule is the point, not an oversight.
    """
    # Arrange
    message = "isn't there a human agent?"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


# ── Accepted false positives ─────────────────────────────────────────────


def test_please_before_a_praised_noun_phrase_still_pages_someone():
    """An accepted false positive, decided rather than missed.

    "please" sits in the explicit-ask list, where it outranks the praise that
    would otherwise mark "customer service" as a topic. It is a weaker ask
    signal than "i want"/"i need" because it also introduces polite
    instructions, so this message escalates when nobody asked.

    Removing "please" from that list would fix it and would cost
    "please, customer service" and "please get me a human agent", which are
    real requests. That is the wrong trade: over-paging is recoverable,
    stranding is not. Change this test only alongside that decision.
    """
    # Arrange
    message = "please note your customer service is excellent"

    # Act
    signal = detect_explicit_handoff_request(message)

    # Assert
    assert signal.decision == REQUESTED


@pytest.mark.parametrize(
    "message",
    [
        "talk to a human, the payment is all good",
        "talk to a human, the refund is all good",
        "I need to talk to a human, the first issue is all good",
        "talk to a human, the bot said no need",
    ],
    ids=[
        "all good about the payment does not withdraw the request",
        "all good about the refund does not withdraw the request",
        "one resolved issue does not withdraw a request about another",
        "the bot's opinion is reported speech, not the customer withdrawing",
    ],
)
def test_a_retraction_about_something_else_does_not_withdraw_the_request(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- a real retraction has no subject of its own: "actually no need"
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


# ── Whether a Chinese negator reaches the phrase ─────────────────────────
#
# Another matched pair, and the reason this one was fixable: 要人工不要机器人
# already passed while 不要机器人要人工 did not -- the same four content words
# in the other clause order, with the opposite answer. A Chinese negator only
# negates the phrase when nothing of substance sits between them. The test
# below says what must still be refused; the one after it says what must not.


@pytest.mark.parametrize(
    "message",
    [
        "不要机器人要人工",
        "不需要机器人转人工",
        "不用担心转人工",
        "我不想等了转人工",
    ],
    ids=[
        "not-a-robot-a-human must be a request in either clause order",
        "not-needing-a-robot must not decline the request for a human",
        "dont-worry before the phrase negates worrying, not the request",
        "not-wanting-to-wait before the phrase negates waiting, not the request",
    ],
)
def test_a_chinese_negator_about_something_else_does_not_decline(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- 要人工不要机器人 already passes; the same words in the other
    # clause order must not flip the answer.
    assert signal.decision == REQUESTED
    assert signal.is_explicit_request is True


@pytest.mark.parametrize(
    "message",
    [
        "不要转人工",
        "不要再转人工",
    ],
    ids=[
        "a Chinese negator directly against the phrase still refuses",
        "an adverb between the negator and the phrase still refuses",
    ],
)
def test_a_chinese_negator_that_binds_to_the_phrase_still_declines(message):
    # Arrange / Act
    signal = detect_explicit_handoff_request(message)

    # Assert -- the bridge set lets adverbs and particles through, so it must
    # not have quietly switched Chinese negation off altogether.
    assert signal.decision == DECLINED
    assert signal.is_explicit_request is False
