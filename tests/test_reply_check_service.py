import json
from collections import Counter
from pathlib import Path

import pytest


def check(reply, *, knowledge=(), profile=None, history=(), customer_message=""):
    from app.services.reply_check_service import check_reply

    return check_reply(reply, knowledge=knowledge, profile=profile or {},
                       history=history, customer_message=customer_message)


@pytest.mark.parametrize(("draft", "source", "subtype", "value"), [
    ("RM1200", "RM 1,200.00", "price", "RM1200"),
    ("价格是马币1200。", "1,200令吉", "price", "RM1200"),
    ("1/12", "1 Disember", "date", "1/12"),
    ("12月1日", "1 Dec", "date", "1/12"),
    ("2 pm", "14:00", "time", "14:00"),
    ("下午两点", "pukul 2 petang", "time", "14:00"),
    ("下午三点半", "3:30 PM", "time", "15:30"),
    ("+60 12-345 6789", "0123456789", "phone", "0123456789"),
    ("03-7627 2929", "+60 3 7627 2929", "phone", "0376272929"),
    ("Bank hotline: +60 12-345 6789", "Phone: 0123456789", "phone", "0123456789"),
    ("https://SHOP.example.my/order/", "http://shop.example.my/order.", "link", "shop.example.my/order"),
    ("shop.example.my/order", "https://shop.example.my/order/", "link", "shop.example.my/order"),
    ("Account: 0000 0000 0031", "Bank account 000000000031", "bank", "000000000031"),
    ("Account: 0123456789", "Account number: 0123 456 789", "bank", "0123456789"),
])
def test_normalises_only_whole_values(draft, source, subtype, value):
    assert check(draft) == [{"category": "facts", "subtype": subtype, "value": value}]
    assert check(draft, knowledge=[{"id": 1, "content": source}]) == []


@pytest.mark.parametrize(("draft", "near_match"), [
    ("RM48.12", "RM48.21"), ("RM12", "RM120"), ("1/12", "11/12"),
    ("1/12/2026", "1/12/2025"), ("2:10 pm", "14:01"),
    ("0123456789", "0123456780"), ("Akaun 000000000031", "Akaun 00000000031"),
    ("shop.example.my/order?item=1", "shop.example.my/order?item=10"),
    ("shop.example.my/Order", "shop.example.my/order"),
])
def test_different_values_are_unsupported(draft, near_match):
    assert len(check(draft, knowledge=[near_match])) == 1


@pytest.mark.parametrize(("budget", "claim", "quote"), [
    ("Is RM80 within budget?", "The fitting costs RM80.", "You mentioned a budget of RM80."),
    ("Bajet saya RM80.", "Harga kami RM80.", "Bajet awak RM80."),
    ("我的预算是RM80。", "我们的价格是RM80。", "你说你的预算是RM80。"),
])
def test_customer_budget_can_be_quoted_but_cannot_establish_the_business_price(budget, claim, quote):
    assert check(quote, customer_message=budget) == []
    assert check(claim, history=[{"role": "user", "content": budget}]) == [
        {"category": "facts", "subtype": "price", "value": "RM80"}
    ]
    assert check(claim, knowledge=["Price: RM80"], customer_message=budget) == []


def test_customer_budget_is_only_evidence_for_a_quote_even_without_a_price_keyword():
    message = "My budget is RM80."
    assert check("The shelf is RM80.", customer_message=message) == [
        {"category": "facts", "subtype": "price", "value": "RM80"},
    ]
    assert not check("You mentioned RM80.", customer_message=message)


def test_trusts_customer_turns_and_profile_but_excludes_assistants_and_metadata():
    findings = check(
        "RM10, RM11, RM12, RM13, RM14, RM14, RM15.",
        knowledge=[{"content": "RM10", "id": "RM15", "source": "RM15"}],
        profile={"business_description": "RM11"},
        history=[{"role": "user", "content": "RM12"}, {"role": "assistant", "content": "RM14"}],
        customer_message="RM13",
    )
    assert findings == [{"category": "facts", "subtype": "price", "value": value}
                        for value in ("RM14", "RM15")]


def test_structured_bank_field_and_customer_account_preserve_leading_zero():
    assert not check("Our bank account is 0123 456 789.", profile={"bank_account": "0123456789"})
    assert not check("Your bank account is 1234 5678.", customer_message="12345678")
    assert check("Our bank account is 0123 456 789.", profile={"phone": "0123456789"})


def test_link_keeps_the_complete_path_before_chinese_punctuation():
    assert not check("打开 https://shop.example.my/order，查看库存。", knowledge=["shop.example.my/order/"])
    assert check("打开 https://shop.example.my/order2，查看库存。", knowledge=["shop.example.my/order/"])


@pytest.mark.parametrize("link", [
    "wasap.my/60120000001",
    "https://wa.me/0120000001?text=Hello",
    "https://api.whatsapp.com/send?text=Hello&phone=60120000001",
    "whatsapp://send?phone=%2B60120000001",
])
@pytest.mark.parametrize("source", ["knowledge", "profile"])
def test_whatsapp_destination_supports_only_its_own_number(link, source):
    evidence = {"knowledge": [link]} if source == "knowledge" else {"profile": {"contact": link}}
    assert check("Call +60 12-000 0001.", **evidence) == []
    assert check("Call +60 12-000 0002.", **evidence) == [
        {"category": "facts", "subtype": "phone", "value": "0120000002"}]


@pytest.mark.parametrize("url", [
    "https://wa.me.example.my/60120000001", "https://example.my/?phone=60120000001",
    "https://wa.me/60120000002?text=60120000001",
    "https://api.whatsapp.com/other?phone=60120000001",
    "whatsapp://send?text=60120000001",
])
def test_numbers_outside_whatsapp_destinations_are_not_phone_evidence(url):
    assert check("Call 012-000 0001.", knowledge=[url]) == [
        {"category": "facts", "subtype": "phone", "value": "0120000001"}]


def test_whatsapp_app_uri_in_reply_still_checks_the_destination_as_a_phone():
    link = "whatsapp://send?phone=60120000001"
    assert check(link, profile={"phone": "012-000 0001"}) == []
    assert check(link, profile={"phone": "012-000 0002"}) == [
        {"category": "facts", "subtype": "phone", "value": "0120000001"}]


def test_parentheses_inside_a_link_are_part_of_the_page_address():
    draft = "Open [the listing](https://shop.example.my/item(blue))."
    assert check(draft, knowledge=["http://shop.example.my/item(red)"]) == [
        {"category": "facts", "subtype": "link", "value": "shop.example.my/item(blue)"},
    ]
    assert not check(draft, knowledge=["http://shop.example.my/item(blue)/"])


def test_checker_error_is_type_only(caplog):
    class BrokenKnowledge:
        def __iter__(self):
            raise RuntimeError("private customer value")

    assert check("RM5", knowledge=BrokenKnowledge()) == []
    assert "RuntimeError" in caplog.text
    assert "private customer value" not in caplog.text


def test_section_a_over_all_rulebook_chats():
    chats = json.loads((Path(__file__).parent / "fixtures" / "reply_check_chats.json").read_text("utf-8"))
    totals = Counter()
    flagged = Counter()
    for chat in chats:
        group = "pass" if chat["expected"] == "pass" else chat["category"]
        findings = check(chat["bot_reply"], knowledge=chat["knowledge"], profile=chat["business_profile"],
                         history=chat["history"], customer_message=chat["customer_message"])
        totals[group] += 1
        findings = [f for f in findings if f["category"] == "facts"]
        flagged[group] += bool(findings)
        if group == "facts":
            assert chat["subtype"] in {f["subtype"] for f in findings}, chat["id"]
        if group == "pass":
            assert not findings, chat["id"]
    assert totals == {"facts": 12, "pass": 22, "leak": 9, "promise": 13, "filtered": 4}
    # Overlap on the latter three is informational: other rules grade those replies.
    for group in totals:
        print(f"{group}: {flagged[group]} flagged, {totals[group] - flagged[group]} clear")


def test_combined_fixture_confusion_table():
    chats = json.loads((Path(__file__).parent / "fixtures/reply_check_chats.json").read_text("utf-8"))
    table = Counter()
    reviewer_cases = {"rc-005", "rc-010", "rc-026", "rc-040", "rc-041", "rc-055", "rc-044"}
    missed = set()
    for chat in chats:
        findings = check(chat["bot_reply"], knowledge=chat["knowledge"], profile=chat["business_profile"],
                         history=chat["history"], customer_message=chat["customer_message"])
        group = chat["category"] if chat["expected"] == "hold" else chat["expected"]
        table[group, bool(findings)] += 1
        if group in {"pass", "filter"}:
            assert not findings, chat["id"]
        elif not any((f["category"], f["subtype"]) == (group, chat["subtype"]) for f in findings):
            missed.add(chat["id"])
        assert any(f["category"] == "facts" for f in findings) == (group == "facts"), chat["id"]
    assert missed == reviewer_cases
    counts = {g: (table[g, True], table[g, False]) for g in ("facts", "leak", "promise", "pass", "filter")}
    for group, (flagged, clear) in counts.items():
        print(f"{group}: {flagged} flagged, {clear} clear")
    assert counts == {
        "facts": (12, 0), "leak": (3, 6), "promise": (12, 1), "pass": (0, 22), "filter": (0, 4)}


@pytest.mark.parametrize("case", json.loads(
    (Path(__file__).parent / "fixtures/reply_check_live_cases.json").read_text("utf-8")
), ids=lambda case: case["id"])
def test_code_checks_on_live_patterns(case):
    from app.services.reply_notes import visible_draft

    findings = check(visible_draft(case["bot_reply"]), knowledge=case["knowledge"],
                     profile=case["business_profile"], history=case["history"],
                     customer_message=case["customer_message"])
    expected = {(case["category"], case["subtype"])} if case["expected"] == "hold" else set()
    assert {(f["category"], f["subtype"]) for f in findings} == expected
