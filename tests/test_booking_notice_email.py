"""The owner notice: a short email with a button, safe against hostile text and bad addresses.

Seam: receipt_email_service.send_notice_email, observed at the SMTP boundary by parsing the
message that would leave. No live mail: smtplib is replaced.
"""

import email
import ssl
from email import policy

import pytest

from app.services import receipt_email_service as svc


class FakeSMTP:
    sent, constructed, timeouts, contexts, exits = [], 0, [], [], 0

    def __init__(self, host, port, timeout=None):
        FakeSMTP.constructed += 1
        FakeSMTP.timeouts.append(timeout)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        FakeSMTP.exits += 1  # a real SMTP closes its socket here, even after a failed send
        return False

    def starttls(self, context=None):
        FakeSMTP.contexts.append(context)

    def login(self, user, password):
        pass

    def sendmail(self, sender, recipients, message):
        FakeSMTP.sent.append((sender, list(recipients), message))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.constructed, FakeSMTP.timeouts = [], 0, []
    FakeSMTP.contexts, FakeSMTP.exits = [], 0
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "billing@omnexa.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "dummy-password")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    return FakeSMTP


def notice(**overrides):
    kwargs = dict(title="New booking request", message="A customer asked for a booking.",
                  label="Bookings", footer="You are receiving this because you own the account.",
                  recipient_name="Olu", action_label="Open bookings",
                  action_url="https://app.example.test/bookings.html")
    kwargs.update(overrides)
    return svc.send_notice_email("owner@example.test", **kwargs)


def parsed():
    _, recipients, raw = FakeSMTP.sent[0]
    return recipients, email.message_from_string(raw, policy=policy.default)


def body(message, subtype):
    part = message.get_body(preferencelist=(subtype,))
    return part.get_content() if part else ""


def test_the_owner_gets_one_email_with_a_button(smtp):
    assert notice() is True

    recipients, message = parsed()
    assert recipients == ["owner@example.test"] and message["To"] == "owner@example.test"
    assert message["Subject"] == "Omnexa: New booking request"
    html = body(message, "html")
    for expected in ("New booking request", "A customer asked for a booking.", "Bookings", "Olu",
                     "https://app.example.test/bookings.html", "Open bookings",
                     "You are receiving this because you own the account."):
        assert expected in html, expected


def test_a_plain_text_version_has_the_message_and_link(smtp):
    notice()

    text = body(parsed()[1], "plain")
    assert "A customer asked for a booking." in text and "https://app.example.test/bookings.html" in text


def test_hostile_text_is_escaped(smtp):
    notice(title="<script>alert(1)</script>", message='"><img src=x onerror=1>', recipient_name="<b>Olu</b>")

    html = body(parsed()[1], "html")
    for raw in ("<script>", "<img src=x", "<b>Olu</b>"):
        assert raw not in html, raw


def test_a_title_cannot_add_mail_headers(smtp):
    notice(title="Hello\r\nBcc: attacker@evil.test")

    _, message = parsed()
    assert message["Bcc"] is None and "\n" not in message["Subject"] and "\r" not in message["Subject"]


def test_the_button_is_omitted_without_a_link(smtp):
    notice(action_label=None, action_url=None)

    assert "<a href" not in body(parsed()[1], "html")


@pytest.mark.parametrize("address", ["a@b.test\nBcc: x@evil.test", "", None, "no-at-sign", "bé@example.test"])
def test_a_bad_recipient_is_never_mailed(smtp, address):
    assert svc.send_notice_email(address, title="t", message="m", label="L", footer="f") is False
    assert smtp.constructed == 0


def test_missing_smtp_credentials_send_nothing(smtp, monkeypatch):
    monkeypatch.delenv("SMTP_APP_PASSWORD")

    assert notice() is False
    assert smtp.constructed == 0


def test_the_connection_verifies_the_servers_certificate(smtp):
    notice()

    context = smtp.contexts[0]
    assert context is not None, "starttls() without a context sends the SMTP password to anyone who answers"
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


def test_the_connection_is_closed_even_when_sending_fails(smtp, monkeypatch):
    def refuse(self, sender, recipients, message):
        raise OSError("connection reset")

    monkeypatch.setattr(smtp, "sendmail", refuse)

    assert notice() is False
    assert smtp.exits == 1, "a failed send must still close the socket"


def test_the_connection_is_bounded_by_a_timeout(smtp):
    notice()

    assert smtp.timeouts[0] is not None and 0 < smtp.timeouts[0] <= 30


def test_an_smtp_failure_returns_false_and_never_raises(monkeypatch, smtp):
    def explode(host, port, timeout=None):
        raise OSError("smtp down")

    monkeypatch.setattr("smtplib.SMTP", explode)

    assert notice() is False
