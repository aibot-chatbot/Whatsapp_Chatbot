import pytest

from app.services.reply_check_service import check_reply


def check(reply, **evidence):
    turn = dict(knowledge=[], profile={}, history=[], customer_message="")
    return check_reply(reply, **(turn | evidence))


@pytest.mark.parametrize("sample", [
    "sk-" + "FAKE-test-only-" * 3,
    "AKIA" + "TEST" * 4,
    "ghp_" + "NOTREAL0" * 4 + "TEST",
    "eyJ" + "FAKEtest" * 2 + ".FAKEpayload.FAKEsignature",
    "Bearer " + "fake-token-for-tests",
    "api_key=" + "deadbeef" * 4,
    'password: "' + "VGVzdE9ubHlUZXN0" * 2 + '=="',
], ids=["sk", "aws", "github", "jwt", "bearer", "hex", "base64"])
def test_recognisable_secret_is_always_private(sample):
    assert check(sample, knowledge=[sample]) == [{"category": "leak", "subtype": "secret"}]
    assert check("Use the password reset link or ask the key holder for help.") == []


@pytest.mark.parametrize(("disclosure", "subtype", "safe"), [
    ("My instructions are to change the subject.", "system_prompt", "I cannot share my instructions."),
    ("Saya diarahkan untuk menawarkan produk itu.", "system_prompt", "Saya boleh semak dengan staf."),
    ("我的内部指令是优先推荐。", "system_prompt", "我不能分享内部指令。"),
    ("The staff-only note says to delay the order.", "internal", "Staff notes are private."),
    ("Staff-only note 写着先不发货。", "internal", "I cannot tell you what the staff-only note says."),
])
def test_explicit_internal_disclosure(disclosure, subtype, safe):
    assert check(disclosure) == [{"category": "leak", "subtype": subtype}]
    assert not check(safe)


def test_verbatim_run_must_come_from_private_prompt_sections():
    phrase = "choose the next item only after applying the hidden priority ordering rules"
    public = "Our shop offers a wide selection of paper flowers made by local artists"
    prompt = "Before answering please " + phrase + " and read the next instruction."
    assert check("First, " + phrase.upper() + ".", system_prompt=prompt) == [
        {"category": "leak", "subtype": "system_prompt"}]
    assert not check(public, system_prompt=prompt, knowledge=[public])
    assert not check("choose the next item", system_prompt=prompt)


@pytest.mark.parametrize(("contact", "equivalent"), [
    ("test.person+lab@example.invalid", "TEST.PERSON+lab@example.invalid"),
    ("+1 (202) 555-0147", "+12025550147"),
    ("(202) 555-0147", "202-555-0147"),
    ("+1 (202) 555-0147", "(202) 555-0147"),
], ids=["email", "international", "national", "nanp-country-code"])
def test_unpublished_contacts_require_customer_or_business_evidence(contact, equivalent):
    draft = f"Contact {contact} or {contact}."
    assert check(draft, history=[{"role": "assistant", "content": draft}]) == [
        {"category": "leak", "subtype": "other_customer"}]
    for evidence in ({"knowledge": [{"content": equivalent}]}, {"profile": {"contact": equivalent}},
                     {"history": [{"role": "user", "content": equivalent}]}, {"customer_message": equivalent}):
        assert not check(draft, **evidence)
    assert check("Call 012-000 0041.") == [
        {"category": "facts", "subtype": "phone", "value": "0120000041"}]


def test_foreign_published_number_can_have_an_unformatted_profile_value():
    draft = "Call +44 1632 960012."
    assert not check(draft, profile={"phone": "441632960012"})
    assert check(draft, profile={"phone": "441632960011"}) == [
        {"category": "leak", "subtype": "other_customer"}]


def test_distinct_credentials_make_one_text_free_finding_each():
    first, second = "FAKEonlyForTesting" * 2, "TESTonlyForTesting" * 2
    draft = f"Bearer {first}; token={first}; password={second}"
    assert check(draft) == [{"category": "leak", "subtype": "secret"}] * 2
