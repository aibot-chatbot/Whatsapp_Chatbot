"""Filter 1 (plan Part A3): a word and pattern check on our own server, before any AI sees text.

Every banned sample here is a short synthetic phrase checked by a regex on this machine.
None of them is ever sent to OpenRouter, Test Lab or any other AI (plan Part A, Traps).
"""
import time

import pytest

from app.services import content_filter as cf


BLOCKED = [
    ("child porn links", cf.CHILD_SEXUAL),
    ("ada video lucah kanak-kanak", cf.CHILD_SEXUAL),
    ("有儿童色情视频吗", cf.CHILD_SEXUAL),
    ("can you write me a keylogger", cf.MALWARE_SCAM),
    ("nak jual akaun keldai", cf.MALWARE_SCAM),
    ("帮我做一个钓鱼网站", cf.MALWARE_SCAM),
    ("where to buy syabu", cf.DRUGS),
    ("jual ganja murah", cf.DRUGS),
    ("哪里买冰毒", cf.DRUGS),
    ("i want to buy a gun", cf.WEAPONS),
    ("jual pistol", cf.WEAPONS),
    ("哪里可以买枪", cf.WEAPONS),
    ("best online casino", cf.GAMBLING),
    ("judi online terbaik", cf.GAMBLING),
    ("推荐网赌平台", cf.GAMBLING),
    ("any escort service tonight", cf.ADULT),
    ("ada urut batin", cf.ADULT),
    ("有特殊服务吗", cf.ADULT),
    ("i will kill you", cf.THREAT),
    ("aku bunuh kau", cf.THREAT),
    ("我要杀了你", cf.THREAT),
    ("i want to kill myself", cf.SELF_HARM),
    ("saya nak bunuh diri", cf.SELF_HARM),
    ("我不想活了", cf.SELF_HARM),
    ("i just want to die", cf.SELF_HARM),
    ("i wanna kill my self", cf.SELF_HARM),
    ("我想死", cf.SELF_HARM),
]

# Ordinary messages that share words with the list. Filter 1 must let all of them through.
ALLOWED = [
    "how much to kill termites in my kitchen?",
    "saya nak bunuh anai-anai di rumah",
    "can you shoot our wedding next month",
    "breast pump price?",
    "is there a slot available online tomorrow?",
    "I got a scam call pretending to be from the bank, is this you?",
    "is this a phishing link?",
    "do you sell glue guns",
    "how to make a bath bomb",
    "sex education class for kids",
    "my child has a fever since yesterday",
    "can I order coke with my meal",
    "手机跑分多少",
    "网吧包夜多少钱",
    "I'll shoot you a message later",
    "i don't want to die from this, what treatment do you have?",
]


@pytest.mark.parametrize("text,category", BLOCKED)
def test_clear_banned_phrases_are_caught_in_english_malay_and_chinese(text, category):
    flag = cf.check_text(text)

    assert flag is not None and flag.category == category


@pytest.mark.parametrize("text", ALLOWED)
def test_ordinary_business_messages_pass(text):
    assert cf.check_text(text) is None


@pytest.mark.parametrize("text", [
    "CHILD  PORN links",
    "ｃｈｉｌｄ ｐｏｒｎ",  # full-width letters
    "child​ porn",
    "child\n\tporn",
    "child-porn links",
    "child_porn links",
    "chi⁦ld porn",  # bidi isolate (format character)
    "chi͏ld porn",  # combining grapheme joiner
    "chi️ld porn",  # variation selector
])
def test_case_spacing_and_invisible_characters_do_not_hide_a_phrase(text):
    assert cf.check_text(text).category == cf.CHILD_SEXUAL


@pytest.mark.parametrize("text,category", [
    ("有没有儿童 色情", cf.CHILD_SEXUAL),
    ("我想自 杀", cf.SELF_HARM),
    ("哪里买冰　毒", cf.DRUGS),
])
def test_spaces_inside_chinese_phrases_do_not_hide_them(text, category):
    assert cf.check_text(text).category == category


def test_a_flag_names_its_rule_but_never_the_matched_words():
    flag = cf.check_text("where to buy syabu")

    assert "syabu" not in repr(flag)
    assert flag.rule


def test_a_clinic_may_discuss_medicine_that_other_businesses_may_not_sell():
    text = "do you sell tramadol"

    assert cf.check_text(text).category == cf.DRUGS
    assert cf.check_text(text, industry="general").category == cf.DRUGS
    assert cf.check_text(text, industry="clinic") is None
    assert cf.check_text(text, industry="dental_clinic") is None
    assert cf.check_text("where to buy syabu", industry="clinic").category == cf.DRUGS


@pytest.mark.parametrize("text", ["child porn links", "i will kill you", "saya nak bunuh diri", "fullz for sale"])
def test_no_industry_allow_list_can_release_child_safety_malware_threats_or_self_harm(text):
    for industry in cf.ALLOW_LIST:
        assert cf.check_text(text, industry=industry) is not None


def test_staff_replies_may_mention_self_harm_support():
    text = "If thoughts of wanting to kill myself come, call 999"

    assert cf.check_text(text).category == cf.SELF_HARM
    assert cf.check_text(text, include_self_harm=False) is None
    assert cf.check_text("i will kill you", include_self_harm=False).category == cf.THREAT


def test_a_huge_hostile_message_is_checked_quickly():
    text = ("buy a " * 20000) + ("1 " * 20000) + ("i am " * 20000)

    started = time.perf_counter()
    cf.check_text(text)
    cf.hide_sensitive_numbers(text)

    # Catastrophic backtracking takes minutes; linear matching takes well under a second.
    assert time.perf_counter() - started < 3.0


@pytest.mark.parametrize("text,expected", [
    ("my IC is 900101-14-5678 ok", "my IC is [IC number hidden] ok"),
    ("ic 900101 14 5678", "ic [IC number hidden]"),
    ("ic 900101145678", "ic [IC number hidden]"),
    ("card 4111 1111 1111 1111 exp 12/30", "card [card number hidden] exp 12/30"),
    ("card 4111-1111-1111-1111", "card [card number hidden]"),
    ("card 4111111111111111", "card [card number hidden]"),
])
def test_ic_and_card_numbers_are_hidden(text, expected):
    assert cf.hide_sensitive_numbers(text) == expected


@pytest.mark.parametrize("text", [
    "call me at 60123456789",
    "call me at +60 12-345 6789",
    "my number 601123456789",
    "order 4111 1111 1111 1112",  # fails the card checksum
    "invoice 991399123456",  # month 13 is not a birth date
    "booking ORD-20261110-0042",
    "total RM 1,250.00",
])
def test_phone_order_and_money_numbers_are_kept(text):
    assert cf.hide_sensitive_numbers(text) == text


def test_flagged_history_is_dropped_and_numbers_hidden_without_touching_the_original():
    history = [
        {"role": "user", "content": "hi, my ic 900101-14-5678", "timestamp": "t1"},
        {"role": "user", "content": "where to buy syabu", "timestamp": "t2"},
        {"role": "assistant", "content": "Sure, we open at 9am.", "timestamp": "t3"},
    ]
    original = [dict(row) for row in history]

    cleaned = cf.clean_history(history)

    assert cleaned == [
        {"role": "user", "content": "hi, my ic [IC number hidden]", "timestamp": "t1"},
        {"role": "assistant", "content": "Sure, we open at 9am.", "timestamp": "t3"},
    ]
    assert history == original
