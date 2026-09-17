"""Billing notifications must also reach the account owner by email.

An in-app notice alone is missed: a customer whose AI credit is exhausted has
stopped receiving replies and is not looking at the dashboard to find out why.

These tests pin the three properties that matter:
  * the right events email, and only those events;
  * the recipient is the account owner, not every admin;
  * email is best effort and can never break a billing operation.
"""

from unittest.mock import Mock

import pytest

from app.services import billing_notification_service as svc


TITLE = "AI credit is running low"


def notify(notification_type: str) -> None:
    """Call the helper with one fixed event, varying only the type.

    Spelled out rather than unpacked from a dict so the argument types stay
    concrete: `**dict(...)` widens every value to `int | str` and the type
    checker then rejects every parameter.
    """
    svc._safe_notify(
        company_id=42,
        notification_type=notification_type,
        severity="warning",
        title=TITLE,
        message="Your workspace has used 80% of this month's AI credit.",
        event_key="evt-1",
    )


@pytest.fixture
def wiring(monkeypatch):
    """Replace the row write, the owner lookup and the mailer with spies."""
    created = Mock()
    mailer = Mock(return_value=True)
    contact = Mock(return_value={"email": "owner@example.test", "full_name": "Ada"})

    monkeypatch.setattr(svc, "create_billing_notification", created)
    monkeypatch.setattr(
        "app.database.user_repository.get_company_billing_contact", contact
    )
    monkeypatch.setattr(
        "app.services.email_service.send_billing_notification_email", mailer
    )
    return {"created": created, "mailer": mailer, "contact": contact}


@pytest.mark.parametrize("notification_type", sorted(svc._EMAIL_NOTIFICATION_TYPES))
def test_actionable_events_email_the_owner(wiring, notification_type):
    notify(notification_type)

    wiring["mailer"].assert_called_once()
    assert wiring["mailer"].call_args.args[0] == "owner@example.test"
    assert wiring["mailer"].call_args.kwargs["recipient_name"] == "Ada"
    assert wiring["mailer"].call_args.kwargs["title"] == TITLE


@pytest.mark.parametrize(
    "notification_type", ["reconciliation_completed", "activation_completed"]
)
def test_internal_events_do_not_email(wiring, notification_type):
    """Housekeeping and the duplicate half of a payment stay in-app.

    activation_completed fires for the same event as payment_confirmed, so
    emailing both would send two messages for one payment.
    """
    notify(notification_type)

    wiring["created"].assert_called_once()
    wiring["mailer"].assert_not_called()


def test_no_email_when_the_notification_row_failed(wiring):
    """The row is the system of record; never email an unrecorded event."""
    wiring["created"].side_effect = RuntimeError("db down")

    notify("ai_credit_depleted")

    wiring["mailer"].assert_not_called()


def test_company_with_no_active_owner_is_skipped_quietly(wiring):
    """Every seat deactivated is a real state, not an error."""
    wiring["contact"].return_value = None

    notify("ai_credit_depleted")

    wiring["created"].assert_called_once()
    wiring["mailer"].assert_not_called()


def test_mail_failure_never_breaks_the_billing_operation(wiring):
    """A bounced email must not roll back a subscription change."""
    wiring["mailer"].side_effect = RuntimeError("smtp exploded")

    # Must not raise: the caller is mid-billing-operation.
    notify("subscription_expired")

    wiring["created"].assert_called_once()


def test_owner_lookup_never_selects_credential_columns():
    """The users row carries password_hash and otp_code; neither may travel."""
    import inspect

    from app.database import user_repository

    source = inspect.getsource(user_repository.get_company_billing_contact)
    assert '.select("email, full_name")' in source
    body = source.split('"""')[-1]
    for secret in ("password_hash", "otp_code", "otp_expiry"):
        assert secret not in body
