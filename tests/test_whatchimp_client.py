"""WhatChimp HTTP client: number lookup, text and reply-button sends.

A non-technical owner pastes only their WhatChimp API key; the number list comes
from /user/myInfo so they never type a phone_number_id. Seam: requests.post out,
with every WhatChimp answer canned.
"""

import json
from unittest.mock import MagicMock

import pytest
import requests

from app.services import whatchimp_client as wc

TOKEN = "test-whatchimp-token"
NUMBER_ID = "119060000040020"


def _answer(payload, status_code=200):
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload
    return response


@pytest.fixture
def posted(monkeypatch):
    """Record each POST and reply with the queued canned answers in order."""
    calls, answers = [], []

    def fake_post(url, data=None, headers=None, timeout=None, allow_redirects=True):
        calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout,
                      "allow_redirects": allow_redirects})
        return answers.pop(0)

    monkeypatch.setattr(wc.requests, "post", fake_post)
    return calls, answers


def test_lists_connected_numbers_from_the_api_key_alone(posted):
    calls, answers = posted
    answers.append(_answer({"status": "1", "message": {"name": "Ali", "whatsapp_bots_details": [
        {"display_phone_number": "+60 12-345 6789", "phone_number_id": 119060000040020,
         "whatsapp_business_account_id": "999", "whatsapp_business_name": "Ali Bakery"},
        {"display_phone_number": "+60 19-000 0000"},  # no id: cannot be used, so it is not offered
    ]}}))

    result = wc.list_whatsapp_numbers(TOKEN)

    assert result == {"success": True, "error": None, "data": [
        {"phone_number_id": NUMBER_ID, "display_phone_number": "+60 12-345 6789", "business_name": "Ali Bakery"}]}
    assert calls[0]["url"] == "https://app.whatchimp.com/api/v1/user/myInfo"
    assert calls[0]["data"] == {"apiToken": TOKEN}  # in the body, never the URL
    assert calls[0]["timeout"] == wc.REQUEST_TIMEOUT_SECONDS
    assert calls[0]["allow_redirects"] is False  # a redirect would re-send the key elsewhere


def test_wrong_api_key_returns_whatchimps_reason(posted):
    _, answers = posted
    answers.append(_answer({"status": "0", "message": "No user found"}))

    assert wc.list_whatsapp_numbers(TOKEN) == {"success": False, "data": {"status": "0", "message": "No user found"},
                                                "error": "No user found"}


def test_missing_api_key_makes_no_request(posted):
    calls, _ = posted
    assert wc.list_whatsapp_numbers("  ")["success"] is False
    assert calls == []


def test_sends_text_to_digits_only_recipient(posted):
    calls, answers = posted
    answers.append(_answer({"status": "1", "wa_message_id": "wamid.X", "message": "Message sent successfully."}))

    result = wc.send_whatchimp_text(TOKEN, NUMBER_ID, "+60 12-345 6789", "Hello")

    assert result["success"] is True and result["data"]["wa_message_id"] == "wamid.X"
    assert calls[0]["url"] == "https://app.whatchimp.com/api/v1/whatsapp/send"
    assert calls[0]["data"] == {"apiToken": TOKEN, "phone_number_id": NUMBER_ID,
                                "phone_number": "60123456789", "message": "Hello"}


def test_a_business_scoped_user_id_is_sent_whole(posted):
    calls, answers = posted
    answers.append(_answer({"status": "1", "message": "Message sent successfully."}))

    wc.send_whatchimp_text(TOKEN, NUMBER_ID, "MY.4815162342000001", "Hello")

    assert calls[0]["data"]["phone_number"] == "MY.4815162342000001", "digits-only would address another number"


def test_rejected_send_is_a_failure_with_the_reason(posted):
    _, answers = posted
    answers.append(_answer({"status": "0", "message": "Subscriber limit has been exceeded."}))

    result = wc.send_whatchimp_text(TOKEN, NUMBER_ID, "60123456789", "Hello")

    assert result["success"] is False and result["error"] == "Subscriber limit has been exceeded."


@pytest.mark.parametrize("failure, reason", [
    (requests.Timeout(), "WhatChimp did not answer in time"),
    (requests.ConnectionError(), "Could not reach WhatChimp"),
])
def test_network_failures_are_reported_not_raised(monkeypatch, failure, reason):
    monkeypatch.setattr(wc.requests, "post", MagicMock(side_effect=failure))
    assert wc.send_whatchimp_text(TOKEN, NUMBER_ID, "60123456789", "Hi") == {
        "success": False, "data": None, "error": reason}


def test_http_error_without_json_is_a_failure(posted):
    _, answers = posted
    broken = MagicMock(status_code=502)
    broken.json.side_effect = ValueError
    answers.append(broken)

    result = wc.send_whatchimp_text(TOKEN, NUMBER_ID, "60123456789", "Hi")

    assert result == {"success": False, "data": None, "error": "WhatChimp rejected the request (502)"}


def test_media_attachment_is_sent_by_url_with_caption(posted):
    calls, answers = posted
    answers.append(_answer({"status": "1", "wa_message_id": "wamid.F"}))

    result = wc.send_whatchimp_file(TOKEN, NUMBER_ID, "60123456789", "https://cdn.example/menu.pdf", "document", "Our menu")

    assert result["success"] is True
    assert calls[0]["url"] == "https://app.whatchimp.com/api/v1/whatsapp/send/file"
    assert calls[0]["data"] == {"apiToken": TOKEN, "phone_number_id": NUMBER_ID, "phone_number": "60123456789",
                                "media_url": "https://cdn.example/menu.pdf", "media_type": "document",
                                "media_caption_text": "Our menu"}


def test_reply_buttons_follow_the_official_whatsapp_limits(posted):
    calls, answers = posted
    answers.append(_answer({"status": "1", "wa_message_id": "wamid.B"}))

    result = wc.send_whatchimp_buttons(TOKEN, NUMBER_ID, "60123456789", "Pick one",
                                       ["Programme information", "Rules", "Schedule", "Fees"])

    assert result["success"] is True
    assert calls[0]["url"] == "https://app.whatchimp.com/api/v1/whatsapp/send/interactive-buttons"
    assert json.loads(calls[0]["data"]["buttons"]) == [
        {"id": "btn_0", "title": "Programme informatio"},
        {"id": "btn_1", "title": "Rules"},
        {"id": "btn_2", "title": "Schedule"},
    ]
    assert calls[0]["data"]["message"] == "Pick one"
