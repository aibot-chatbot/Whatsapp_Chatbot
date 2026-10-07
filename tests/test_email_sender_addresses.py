"""Each kind of email leaves from its own address: support, billing or notify.

Seam: the message handed to SMTP. No live mail: smtplib.SMTP is replaced. The SMTP
login stays SMTP_SENDER_EMAIL; only the From header moves, and an unset address
falls back to the login so a missing setting never stops mail.
"""

import email
from email import policy

import pytest

from app.services import email_service, receipt_email_service

LOGIN = "login@omnexa.test"


class FakeSMTP:
    sent, logins = [], []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        FakeSMTP.logins.append(user)

    def sendmail(self, sender, recipients, message):
        FakeSMTP.sent.append(message)

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins = [], []
    monkeypatch.setenv("SMTP_SENDER_EMAIL", LOGIN)
    monkeypatch.setenv("SMTP_APP_PASSWORD", "dummy-password")
    monkeypatch.setenv("EMAIL_FROM_SUPPORT", "supportteam@omnexa.test")
    monkeypatch.setenv("EMAIL_FROM_BILLING", "billing@omnexa.test")
    monkeypatch.setenv("EMAIL_FROM_NOTIFY", "notifyteam@omnexa.test")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    return FakeSMTP


def sent_from():
    assert len(FakeSMTP.sent) == 1
    return email.message_from_string(FakeSMTP.sent[0], policy=policy.default)["From"]


SENDS = {
    "otp": lambda: email_service.send_otp_email("user@example.test", "123456"),
    "reset": lambda: email_service.send_reset_email("user@example.test", "123456"),
    "invite": lambda: email_service.send_invite_email("user@example.test", "https://app.example.test/i"),
    "billing": lambda: email_service.send_billing_notification_email(
        "owner@example.test", title="Credit low", message="Top up soon."),
    "receipt": lambda: receipt_email_service.send_receipt_email(
        "owner@example.test", order_reference="ORD-1", rows=[("Plan", "Pro")],
        recipient_name="Olu", summary="thanks for your payment.", notice="Keep this receipt."),
    "notice": lambda: receipt_email_service.send_notice_email(
        "owner@example.test", title="New booking", message="A customer booked.",
        label="Bookings", footer="You own the account."),
}


@pytest.mark.parametrize("kind, expected", [
    ("otp", "supportteam@omnexa.test"),
    ("reset", "supportteam@omnexa.test"),
    ("invite", "notifyteam@omnexa.test"),
    ("billing", "billing@omnexa.test"),
    ("receipt", "billing@omnexa.test"),
    ("notice", "notifyteam@omnexa.test"),
])
def test_each_email_leaves_from_its_own_address(smtp, kind, expected):
    assert SENDS[kind]() is True
    assert sent_from() == f"Omnexa <{expected}>"
    assert smtp.logins == [LOGIN]  # the account that signs in never changes


def test_an_unset_address_falls_back_to_the_login(smtp, monkeypatch):
    monkeypatch.delenv("EMAIL_FROM_SUPPORT")
    assert SENDS["otp"]() is True
    assert sent_from() == f"Omnexa <{LOGIN}>"
