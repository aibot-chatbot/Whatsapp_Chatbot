import json
import logging
import re
import threading
import time
from unittest.mock import Mock

import pytest
import requests
from urllib3.exceptions import ReadTimeoutError

from app.database import ai_usage_repository
from app.services import ai_credit_service, ai_router, cloudflare_service


PASS = {"verdict": "pass", "category": "none", "subtype": "none", "reason": "Supported reply."}
INPUTS = dict(knowledge=[{"id": 42, "content": "Published price RM80.", "source": "private_filename"}],
              profile={"name": "Test business"}, history=[
                  {"role": "user", "content": "Budget RM80."},
                  {"role": "system", "content": "private_bot_prompt"},
                  {"role": "assistant", "content": "previous_bot_guess"}],
              customer_message="Can you check?", code_findings=[{"category": "facts", "subtype": "price",
                                                                 "value": "private_match_value"}])


def completion(content):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture(autouse=True)
def require_unbilled_review(monkeypatch):
    monkeypatch.delenv("REPLY_REVIEW_MODEL", raising=False)
    forbidden = []
    for module, names in [(ai_router, ["_make_usage_log", "_charge_logged_usage", "charge_logged_ai_usage",
                                       "insert_usage_log", "_check_ai_credit_before_provider"]),
                          (ai_usage_repository, ["insert_usage_log"]),
                          (ai_credit_service, ["charge_logged_ai_usage", "_charge_usage"]),
                          (ai_router.openrouter_service, ["_request", "post_chat_completion"])]:
        for name in names:
            spy = Mock(side_effect=AssertionError(name))
            monkeypatch.setattr(module, name, spy)
            forbidden.append(spy)
    yield
    for spy in forbidden:
        spy.assert_not_called()


def test_reviews_only_with_workers_ai_and_customer_evidence(monkeypatch):
    from app.services import reply_review_service as service

    provider = Mock(return_value=completion(json.dumps(PASS)))
    monkeypatch.setattr(cloudflare_service, "request", provider)
    for configured in (None, "@cf/meta/llama-3.3-70b-instruct-fp8-fast"):
        if configured:
            monkeypatch.setenv("REPLY_REVIEW_MODEL", configured)
        model = configured or service.DEFAULT_REVIEW_MODEL
        assert service.review_reply("Draft quotation", **INPUTS) == PASS
        args, kwargs = provider.call_args
        prompt = args[0]
        assert kwargs["model"] == model and kwargs["temperature"] == 0 and kwargs["json_response"] is True
        for included in ("Draft quotation", "Published price RM80.", "Test business", "Budget RM80.", "Can you check?"):
            assert included in prompt
        for private in ("private_bot_prompt", "previous_bot_guess", "private_filename", "private_match_value"):
            assert private not in prompt
    monkeypatch.setenv("REPLY_REVIEW_MODEL", "openai/gpt-5.6-sol")
    assert service.review_reply("Draft quotation", **INPUTS) is None
    assert provider.call_count == 2


def test_model_answer_requires_one_consistent_known_verdict(monkeypatch):
    from app.services.reply_review_service import review_reply

    hold = dict(verdict="hold", category="leak", subtype="other_company", reason="Discloses private details.")
    provider = Mock(return_value=completion(json.dumps(hold)))
    monkeypatch.setattr(cloudflare_service, "request", provider)
    assert review_reply("Draft", **INPUTS) == hold
    invalid = [
        dict(hold, verdict="block"), dict(hold, category="privacy"), dict(hold, subtype="unlisted"),
        dict(hold, subtype="timing"), dict(hold, verdict="pass"), dict(PASS, verdict="hold"),
        dict(hold, reason=" "), dict(hold, reason="资料不符"), dict(hold, reason="12345"),
        dict(hold, reason=["quoted"]), dict(hold, reason="x" * 121),
        dict(hold, reason="two\nlines"), dict(hold, extra=True), {"verdict": "pass"}, [],
    ]
    for content in [*map(json.dumps, invalid), '{"verdict":"pass",' + json.dumps(hold)[1:], "invalid JSON"]:
        provider.return_value = completion(content)
        assert review_reply("Draft", **INPUTS) is None
    provider.side_effect = RuntimeError("private provider error")
    assert review_reply("Draft", **INPUTS) is None


def test_sensitive_numbers_are_masked_before_review(monkeypatch):
    from app.services.reply_review_service import review_reply

    provider = Mock(return_value=completion(json.dumps(PASS)))
    monkeypatch.setattr(cloudflare_service, "request", provider)
    inputs = dict(INPUTS, customer_message="My card is 4111 1111 1111 1111.")
    assert review_reply("MyKad 900101-14-1234. Quoted price RM80.", **inputs) == PASS
    prompt = provider.call_args.args[0]
    assert "4111 1111" not in prompt and "900101-14-1234" not in prompt
    assert "[card number hidden]" in prompt and "[IC number hidden]" in prompt and "RM80" in prompt


def test_slow_transport_times_out_without_queueing_more_work(monkeypatch, caplog):
    from app.services import reply_review_service as service

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "offline-test")
    monkeypatch.setattr(service, "_TIMEOUT", 0.15, raising=False)
    monkeypatch.setattr(service, "_slots", threading.BoundedSemaphore(1), raising=False)
    caplog.set_level(logging.INFO)

    def stalled(*args, **kwargs):
        entered.set()
        release.wait(2)
        finished.set()
        raise TimeoutError

    post = Mock(side_effect=stalled)
    monkeypatch.setattr(cloudflare_service.requests, "post", post)
    try:
        start = time.monotonic()
        assert service.review_reply("Sensitive draft", **INPUTS) is None
        assert entered.is_set() and not finished.is_set()
        assert time.monotonic() - start < 1
        assert service.review_reply("Second draft", **INPUTS) is None
        post.assert_called_once()
        assert post.call_args.kwargs["timeout"] == 0.15
    finally:
        release.set()
        assert finished.wait(2)
    failures = [r.getMessage() for r in caplog.records if "[ReplyReview]" in r.getMessage()]
    assert len(failures) == 2
    for line, reason in zip(failures, ("timeout", "no_slot")):
        assert re.fullmatch(rf"\[ReplyReview\] reviewed verdict=error reason={reason} latency_ms=\d+", line)


def test_unbilled_native_model_needs_no_client_price_or_provider_usage(monkeypatch):
    from app.services.reply_review_service import review_reply

    model = "@cf/example/test-chat"
    monkeypatch.setenv("REPLY_REVIEW_MODEL", model)
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "offline-test")
    monkeypatch.setenv("CLOUDFLARE_AI_MODEL_PRICING_JSON", "{}")
    response = Mock(status_code=200, json=Mock(return_value=completion(json.dumps(PASS))))
    post = Mock(return_value=response)
    monkeypatch.setattr(cloudflare_service.requests, "post", post)
    assert review_reply("Draft", **INPUTS) == PASS
    post.assert_called_once()
    assert post.call_args.args[0].endswith("/ai/v1/chat/completions")
    assert post.call_args.kwargs["json"]["model"] == model
    assert post.call_args.kwargs["json"]["response_format"] == {"type": "json_object"}
    assert post.call_args.kwargs["headers"]["cf-aig-collect-log"] == "false"


# Ordinary support replies, five per language including routine business questions.
ORDINARY = [
    ("Hello! How can I help?", False), ("Thanks for letting me know.", False),
    ("It comes in blue and green.", False), ("Which size would you like?", False),
    ("What day works for your appointment?", True),
    ("Hai, apa khabar?", False), ("Sama-sama!", False), ("Boleh saya bantu pilih warna?", False),
    ("Kami boleh semak harga.", True), ("Nak saya hantar pautan katalog?", True),
    ("您好，有什么需要帮忙的吗？", False), ("谢谢你告诉我。", False), ("这个款式有蓝色。", False),
    ("请问你想选哪种？", False), ("您想预约哪一天？", True),
    ("Hi, boleh saya bantu?", False), ("谢谢，take care!", False), ("Warna blue pun ada.", False),
    ("Nak receipt by email?", True), ("可以 request refund 的吗？", True),
]


def test_risk_gate_handles_four_languages_and_ordinary_support():
    from app.services.reply_review_service import needs_review

    risky = [
        "It costs twenty dollars.", "Our hours are nine to five.", "Her address is in that file.",
        "Other businesses get special rates.", "Your solicitor can advise.", "This is tax advice.",
        "They can diagnose that condition.", "Our reception is on 012-000 0031.",
        "Harga berubah ikut tarikh.", "Esok pukul dua.", "Semak akaun bank mereka.",
        "Permohonan bayaran balik diterima.", "Maklumat pelanggan lain.", "Peguam akan semak.",
        "Ini nasihat perubatan.", "Semak pelaburan dahulu.", "可以免费送货。", "另一家公司的资料。",
        "星期天上午营业。", "请联系牙医。", "合同需要律师审核。", "这笔贷款已经批准。",
        "Boleh confirm slot tu?", "Hantar ke orders@example.my.", "用 shop.example.my/order。",
        "只要 RM80.", "Your place is reserved.", "Book for 12/11.", "是下午三点。",
    ]
    for reply, expected in [*ORDINARY, *((reply, True) for reply in risky)]:
        assert needs_review(reply, []) is expected, reply
    assert needs_review("Hello!", [{"category": "leak", "subtype": "secret"}])


def test_polite_time_and_free_phrases_skip_unless_the_rest_is_risky():
    from app.services.reply_review_service import needs_review

    for small_talk in ("Have a nice day!", "Good day, feel free to ask!", "Thanks for your time.",
                       "Selamat pagi, apa khabar?", "周末愉快！", "Good morning，早上好！",
                       "Selamat Hari Raya!", "Selamat tengah hari!", "Take your time."):
        assert not needs_review(small_talk, [])
        assert needs_review(small_talk + " The fee is negotiable.", [])
    for subject in ("We charge ten percent.", "The competitor shares its list.", "Ask for the patient's details.",
                    "Jumpa minggu depan.", "手术需要麻醉。", "明年一月再来。", "Her phone number is on file."):
        assert needs_review(subject, [])


def test_common_scheduling_contacts_and_third_party_phrases():
    from app.services.reply_review_service import needs_review

    for reply in ("See you at lunchtime.", "Your neighbour left her parcel here.",
                  "Kami akan menghubungi anda.", "Ini maklumat rakan sekerja awak.",
                  "今年十二月见。", "请拨打我们的热线。", "这是同事的资料。", "这是她的手机号码。",
                  "这次免单。", "Boleh WhatsApp同事。", "Kos servis boleh berubah.",
                  "Kami boleh susun temu janji.", "Ini maklumat syarikat sebelah.",
                  "一件二十块。", "隔壁店的名单。"):
        assert needs_review(reply, []), reply


@pytest.mark.parametrize("code_findings,expected", [
    ([], "pass"),  # code verified every value; e.g. rc-017 "0000 0000 0016" vs "000000000016"
    ([{"category": "facts", "subtype": "bank", "value": "private_match_value"}], "hold"),
    ([{"category": "promise", "subtype": "refund", "value": "private_match_value"}], "pass"),
])
def test_reviewer_fact_holds_need_a_code_fact_finding(monkeypatch, code_findings, expected):
    from app.services import reply_review_service as service

    hold = {"verdict": "hold", "category": "facts", "subtype": "bank", "reason": "Account not in knowledge."}
    monkeypatch.setattr(cloudflare_service, "request", Mock(return_value=completion(json.dumps(hold))))
    result = service.review_reply("Akaun 000000000016.", **dict(INPUTS, code_findings=code_findings))
    assert result["verdict"] == expected


def test_reviewer_date_hold_requires_a_code_date_finding(monkeypatch):
    from app.services.reply_review_service import review_reply

    hold = dict(verdict="hold", category="facts", subtype="date", reason="Unverified date.")
    monkeypatch.setattr(cloudflare_service, "request", Mock(return_value=completion(json.dumps(hold))))
    link = {"category": "facts", "subtype": "link"}
    result = review_reply("See https://updates.example.my.", **dict(INPUTS, code_findings=[link]))
    assert result["verdict"] == "pass"
    date = {"category": "facts", "subtype": "date"}
    assert review_reply("See https://updates.example.my on 21 November.", **dict(INPUTS, code_findings=[link, date])) == hold


def test_reviewer_sends_multilingual_examples_for_refusals_and_unverified_slots(monkeypatch):
    from app.services.reply_review_service import review_reply

    provider = Mock(return_value=completion(json.dumps(PASS)))
    monkeypatch.setattr(cloudflare_service, "request", provider)
    assert review_reply("A short reply.", **INPUTS) == PASS
    rules = provider.call_args.args[0]
    for example in ("public link", "pautan awam", "公开链接", "public link sahaja",
                    "staff must verify", "staf perlu semak", "需工作人员核实", "admin kena check"):
        assert example in rules


@pytest.mark.parametrize("scenario,reason", [
    ("read_timeout", "timeout"), ("body_timeout", "timeout"), ("network_error", "error_ConnectionError"),
    ("http_redirect", "http_302"), ("http_limit", "http_429"),
    ("bad_body", "invalid_json"), ("bad_content", "invalid_json"),
    ("duplicate_fields", "invalid_verdict"), ("bad_verdict", "invalid_verdict"),
    ("bad_category", "invalid_verdict"), ("wrong_provider", "model_not_allowed"),
    ("bad_model", "model_not_allowed"), ("provider_exception", "error_RuntimeError"),
])
def test_failed_review_logs_one_text_free_reason(monkeypatch, caplog, scenario, reason):
    from app.services.reply_review_service import review_reply

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "offline-test")
    models = {"wrong_provider": "other/private-model", "bad_model": "@cf/bad"}
    if scenario in models:
        monkeypatch.setenv("REPLY_REVIEW_MODEL", models[scenario])
    response = requests.Response()
    response.status_code = {"http_redirect": 302, "http_limit": 429}.get(scenario, 200)
    contents = {
        "bad_content": "private invalid model output",
        "duplicate_fields": '{"verdict":"hold",' + json.dumps(PASS)[1:],
        "bad_verdict": json.dumps(dict(PASS, verdict="private verdict")),
        "bad_category": json.dumps(dict(PASS, category=[])),
    }
    body = json.dumps(completion(contents.get(scenario, json.dumps(PASS))))
    response._content = ("private response body" if scenario == "bad_body" else body).encode()
    faults = {"read_timeout": requests.ReadTimeout("private timeout detail"),
              "body_timeout": requests.ConnectionError(ReadTimeoutError(None, None, "private body detail")),
              "network_error": requests.ConnectionError("private connection detail"),
              "provider_exception": RuntimeError("private provider detail")}
    monkeypatch.setattr(cloudflare_service.requests, "post", Mock(return_value=response, side_effect=faults.get(scenario)))

    assert review_reply("Private draft 012-000 0011.", **INPUTS) is None
    failures = [r.getMessage() for r in caplog.records if "[ReplyReview]" in r.getMessage()]
    assert len(failures) == 1
    assert re.fullmatch(rf"\[ReplyReview\] reviewed verdict=error reason={reason} latency_ms=\d+", failures[0])


# Live Test Lab review on v112 (2026-11-21): the reviewer held these hedged drafts although the code found nothing.
@pytest.mark.parametrize("draft,category,subtype,expected", [
    ("I’m OlympicEdu, and I understand you want confidence before buying books for your child. I can’t promise "
     "a medal—the team would need to confirm whether any guarantee applies to your purchase. Would you like me "
     "to connect you with the team?", "promise", "guarantee", "pass"),
    ("证书只会发给已支付行政费的参赛者。具体领取时间及是否可以免费邮寄，需要行政团队进一步确认，您需要联系行政人员查询吗？",
     "promise", "timing", "pass"),
    ("Our admin team will need to check your child’s registration to confirm the Tiger Maths slot for this "
     "Saturday at 10am. Would you like to contact our admin staff?", "promise", "timing", "pass"),
    ("Our admin team will need to confirm the practice book’s price and whether free delivery tomorrow is "
     "possible. Would you like to contact our admin team?", "promise", "timing", "pass"),
    ("Kalau ada diskaun, admin akan sahkan dulu.", "promise", "discount", "pass"),
    # Plain statements keep the reviewer's hold.
    ("Your Tiger Maths slot is confirmed for Saturday at 10am.", "promise", "timing", "hold"),
    ("你明早的补牙时段已经确定，直接来就好。", "promise", "timing", "hold"),  # fixture rc-044
    ("Yes, delivery tomorrow is free.", "promise", "free_item", "hold"),
    ("我们保证您的孩子一定得奖。", "promise", "guarantee", "hold"),
    ("Kami beri diskaun 20% untuk tiga orang anak.", "promise", "discount", "hold"),
    ("This treatment can't fail, it will cure the condition.", "promise", "medical", "hold"),
    # Privacy holds stay strict even for a refusal.
    ("I can’t share a parent’s private phone number.", "leak", "other_customer", "hold"),
])
def test_reviewer_promise_holds_need_a_plain_promise_statement(monkeypatch, draft, category, subtype, expected):
    from app.services import reply_review_service as service

    hold = {"verdict": "hold", "category": category, "subtype": subtype, "reason": "Reviewer hold."}
    monkeypatch.setattr(cloudflare_service, "request", Mock(return_value=completion(json.dumps(hold))))
    assert service.review_reply(draft, **dict(INPUTS, code_findings=[]))["verdict"] == expected
