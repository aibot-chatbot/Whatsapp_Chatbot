"""Filter 2 (plan A4): a review on Cloudflare Workers AI, never OpenRouter. Every call here is mocked."""
from unittest.mock import MagicMock

import pytest
import requests

from app.services import content_filter
from app.services import content_review_service as review

ACCOUNT = "a" * 32


def reply(result, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = {"success": status == 200, "result": result, "errors": []}
    return response


@pytest.fixture
def cloudflare(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AI_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "synthetic-token")
    state = MagicMock(guard="\n\nsafe", calls=[])

    def post(url, **kwargs):
        state.calls.append({"model": url.rsplit("/ai/run/", 1)[1], **kwargs})
        if "m2m100" in url:
            return reply({"translated_text": "EN:" + kwargs["json"]["text"]})
        return reply({"response": state.guard})

    monkeypatch.setattr(review.requests, "post", post)
    state.post = post
    return state


def guard_input(calls):
    return [call for call in calls if "llama-guard" in call["model"]][0]["json"]["messages"][-1]["content"]


def test_an_unsafe_verdict_names_our_group_and_the_guard_category(cloudflare):
    cloudflare.guard = "\n\nunsafe\nS1"

    result = review.review_text("I will stab you when I see you")

    assert (result.verdict, result.group, result.categories) == ("unsafe", content_filter.THREAT, ("S1",))
    flag = result.as_flag()
    assert (flag.category, flag.rule, flag.filter) == (content_filter.THREAT, "review.S1", 2)


def test_a_safe_verdict_passes(cloudflare):
    assert review.review_text("What time do you open?").verdict == "safe"


@pytest.mark.parametrize("codes", ["S6", "S7", "S5", "S8", "S13", "S14", "S6,S7"])
def test_advice_privacy_and_other_business_categories_are_not_acted_on(cloudflare, codes):
    # Clinics, insurers and lawyers are asked for specialised advice and personal details every day.
    cloudflare.guard = f"\n\nunsafe\n{codes}"

    assert review.review_text("Can you check my blood test result?").verdict == "safe"


@pytest.mark.parametrize("code,group", [
    ("S2", "crime"), ("S3", "sexual"), ("S12", "sexual"), ("S4", content_filter.CHILD_SEXUAL),
    ("S9", content_filter.WEAPONS), ("S10", "hate"), ("S11", content_filter.SELF_HARM),
])
def test_each_acted_on_guard_category_maps_to_one_group(cloudflare, code, group):
    cloudflare.guard = f"\n\nunsafe\n{code}"

    assert review.review_text("synthetic sample").group == group


def test_the_most_serious_category_decides_the_group(cloudflare):
    cloudflare.guard = "\n\nunsafe\nS2,S11"

    assert review.review_text("synthetic sample").group == content_filter.SELF_HARM


@pytest.mark.parametrize("text,language", [
    ("Saya nak tempah slot untuk anak saya", "ms"),
    ("你们星期天几点开门", "zh"),
])
def test_the_translate_option_translates_malay_and_chinese_first(cloudflare, text, language):
    review.review_text(text, option="translate_guard")

    translate = [call for call in cloudflare.calls if "m2m100" in call["model"]][0]["json"]
    assert (translate["source_lang"], translate["target_lang"]) == (language, "en")
    assert guard_input(cloudflare.calls) == "EN:" + text


@pytest.mark.parametrize("text", ["What time do you open on Sunday?", "Saya nak tempah slot", "你们几点开门"])
def test_by_default_the_original_text_goes_straight_to_the_guard_at_temperature_zero(cloudflare, text):
    # Measured: the guard reads Malay and Chinese better as written than through m2m100.
    review.review_text(text)

    assert [call["model"] for call in cloudflare.calls] == [review.GUARD_MODEL]
    assert guard_input(cloudflare.calls) == text
    assert cloudflare.calls[0]["json"]["temperature"] == 0


def test_a_failed_translation_still_reviews_the_original_text(cloudflare, monkeypatch):
    def post(url, **kwargs):
        if "m2m100" in url:
            return reply(None, status=500)
        return cloudflare.post(url, **kwargs)

    monkeypatch.setattr(review.requests, "post", post)

    assert review.review_text("Saya nak tempah slot", option="translate_guard").verdict == "safe"
    assert guard_input(cloudflare.calls) == "Saya nak tempah slot"


@pytest.mark.parametrize("failure", [
    lambda url, **_: reply(None, status=500),
    lambda url, **_: (_ for _ in ()).throw(requests.Timeout("slow")),
    lambda url, **_: reply({"response": "I cannot help with that"}),
    lambda url, **_: reply({"response": "unsafe"}),  # truncated: no hazard code to act on
])
def test_an_outage_or_unreadable_answer_is_unavailable_never_an_exception(cloudflare, monkeypatch, failure):
    monkeypatch.setattr(review.requests, "post", failure)

    assert review.review_text("What time do you open?").verdict == "unavailable"


def test_missing_credentials_are_unavailable_without_a_call(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_AI_ACCOUNT_ID", raising=False)
    post = MagicMock()
    monkeypatch.setattr(review.requests, "post", post)

    assert review.review_text("hello").verdict == "unavailable"
    post.assert_not_called()


def test_the_review_goes_only_to_cloudflare_with_a_short_timeout(cloudflare):
    review.review_text("Saya nak tempah slot", option="translate_guard")

    assert {call["model"] for call in cloudflare.calls} == {review.GUARD_MODEL, review.TRANSLATE_MODEL}
    for call in cloudflare.calls:
        assert call["headers"]["Authorization"] == "Bearer synthetic-token"
        assert call["timeout"] == review.TIMEOUT
        assert call["allow_redirects"] is False


def test_the_review_never_logs_the_text(cloudflare, caplog):
    cloudflare.guard = "\n\nunsafe\nS1"

    review.review_text("I will stab you when I see you")

    assert "stab" not in caplog.text


@pytest.mark.parametrize("value,expected", [(None, "off"), ("", "off"), ("LOG", "log"), ("block", "block"), ("yes", "off")])
def test_the_mode_switch_defaults_to_off(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("CONTENT_REVIEW_MODE", raising=False)
    else:
        monkeypatch.setenv("CONTENT_REVIEW_MODE", value)

    assert review.mode() == expected
