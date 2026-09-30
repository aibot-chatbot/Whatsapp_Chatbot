"""A completed plan purchase must email the purchaser a receipt, exactly once.

Seams under test:
  * notify_payment_confirmed - the one call both payment-callback paths make;
  * email_subscription_receipt - who gets it and what leaves, observed at the
    SMTP boundary by parsing the real MIME message rather than a mocked sender.
No live mail: smtplib is replaced for every test.
"""

import email
import inspect
from email import policy
from unittest.mock import Mock

import pytest

from app.database import user_repository
from app.services import billing_notification_service as notifications
from app.services import billing_receipt_service as receipts

ORDER = {
    "order_reference": "SUB-ORD-1001",
    "company_id": 42,
    "new_plan_id": 3,
    "amount_sen": 8900,
    "status": "paid",
    "activation_status": "completed",
    "payment_reference": "chip-txn-77",
    "gateway_order_id": "gw-55",
    "paid_at": "2026-09-30T05:12:00+00:00",
    "created_at": "2026-09-30T05:10:00+00:00",
    "credited_at": "2026-09-30T05:12:05+00:00",
    "created_by_user_id": 7,
}
TOPUP_ORDER = {
    "order_reference": "TOPUP-2001",
    "company_id": 42,
    "created_by_user_id": 7,
    "amount_micro_myr": 10_500_000,
    "payment_reference": "chip-txn-88",
    "paid_at": "2026-09-30T05:20:00+00:00",
    "credited_at": "2026-09-30T05:20:03+00:00",
}
PLAN = {"id": 3, "code": "advanced", "name": "Advanced"}
BUYER = {"email": "buyer@example.test", "full_name": "Bea Buyer"}
OWNER = {"email": "owner@example.test", "full_name": "Olu Owner"}


class FakeSMTP:
    sent = []
    constructed = 0
    timeouts = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.constructed += 1
        FakeSMTP.timeouts.append(timeout)

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, sender, recipients, message):
        FakeSMTP.sent.append((sender, list(recipients), message))

    def quit(self):
        pass


@pytest.fixture
def world(monkeypatch):
    """Dummy tenant data behind the repositories, and a fake SMTP server."""
    FakeSMTP.sent, FakeSMTP.constructed, FakeSMTP.timeouts = [], 0, []
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "billing@omnexa.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "dummy-password")
    monkeypatch.setenv("FRONTEND_URL", "https://app.omnexa.test")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    state = {"order": dict(ORDER), "plan": dict(PLAN), "buyer": dict(BUYER),
             "owner": dict(OWNER), "company": {"id": 42, "company_name": "Acme Sdn Bhd"}}
    monkeypatch.setattr(receipts, "get_subscription_order_by_reference_and_company",
                        lambda ref, company_id: state["order"])
    monkeypatch.setattr(receipts, "get_plan_by_id", lambda plan_id: state["plan"])
    monkeypatch.setattr(receipts, "get_company_user_contact", lambda user_id, company_id: state["buyer"])
    monkeypatch.setattr(receipts, "get_company_billing_contact", lambda company_id: state["owner"])
    monkeypatch.setattr(receipts, "get_company_by_id", lambda company_id: state["company"])
    state["topup"] = dict(TOPUP_ORDER)
    monkeypatch.setattr(receipts, "get_topup_order_by_reference_and_company",
                        lambda ref, company_id: state["topup"])
    return state


def parsed(index=0):
    """The message that actually left: (envelope recipients, parsed email)."""
    _, recipients, raw = FakeSMTP.sent[index]
    return recipients, email.message_from_string(raw, policy=policy.default)


def body(message, subtype):
    part = message.get_body(preferencelist=(subtype,))
    return part.get_content() if part else ""


# --- who gets it and what it says -----------------------------------------

def test_purchaser_gets_a_receipt_with_the_payment_details(world):
    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is True

    assert len(FakeSMTP.sent) == 1
    recipients, message = parsed()
    assert message["To"] == "buyer@example.test"
    assert recipients == ["buyer@example.test", "owner@example.test"]
    assert "SUB-ORD-1001" in message["Subject"]
    html = body(message, "html")
    for expected in ("Bea Buyer", "Acme Sdn Bhd", "Advanced", "RM 89.00", "chip-txn-77",
                     "SUB-ORD-1001", "30 Sep 2026", "1:12 pm MYT", "not a tax invoice",
                     "https://app.omnexa.test/billing.html"):
        assert expected in html, expected


def test_a_plain_text_version_carries_the_same_facts(world):
    receipts.email_subscription_receipt(42, "SUB-ORD-1001")

    text = body(parsed()[1], "plain")
    for expected in ("SUB-ORD-1001", "Advanced", "RM 89.00", "chip-txn-77"):
        assert expected in text, expected


def test_owner_is_copied_so_spend_stays_visible_to_them(world):
    receipts.email_subscription_receipt(42, "SUB-ORD-1001")

    assert parsed()[1]["Cc"] == "owner@example.test"


def test_owner_is_not_copied_on_their_own_purchase(world):
    world["buyer"] = dict(OWNER)

    receipts.email_subscription_receipt(42, "SUB-ORD-1001")

    recipients, message = parsed()
    assert recipients == ["owner@example.test"]
    assert message["Cc"] is None


@pytest.mark.parametrize("buyer", [
    None,                                              # deactivated or other company's user
    {"email": "", "full_name": "No Address"},
    {"email": "a@b.test\nBcc: attacker@evil.test", "full_name": "Injected"},
])
def test_unreachable_purchaser_falls_back_to_the_owner(world, buyer):
    world["buyer"] = buyer

    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is True

    recipients, message = parsed()
    assert recipients == ["owner@example.test"]
    assert message["Bcc"] is None


def test_nobody_to_email_sends_nothing(world):
    world["buyer"], world["owner"] = None, None

    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is False
    assert FakeSMTP.constructed == 0


def test_unknown_order_sends_nothing(world):
    world["order"] = None

    assert receipts.email_subscription_receipt(42, "SUB-NOPE") is False
    assert FakeSMTP.constructed == 0


def test_missing_smtp_credentials_send_nothing(world, monkeypatch):
    monkeypatch.delenv("SMTP_APP_PASSWORD")

    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is False
    assert FakeSMTP.constructed == 0


def test_smtp_failure_never_raises(world, monkeypatch):
    def explode(host, port):
        raise OSError("smtp down")

    monkeypatch.setattr("smtplib.SMTP", explode)

    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is False


def test_a_database_error_never_raises(world, monkeypatch):
    monkeypatch.setattr(receipts, "get_company_billing_contact",
                        Mock(side_effect=RuntimeError("db down")))

    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is False


def test_stored_names_cannot_inject_markup_into_the_email(world):
    world["plan"]["name"] = "<script>alert(1)</script>"
    world["company"]["company_name"] = 'Evil"><img src=x onerror=1>'
    world["buyer"]["full_name"] = "<b>Bea</b>"

    receipts.email_subscription_receipt(42, "SUB-ORD-1001")

    html = body(parsed()[1], "html")
    for raw in ("<script>", "<img src=x", "<b>Bea</b>"):
        assert raw not in html, raw
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.parametrize("sen,shown", [(5, "RM 0.05"), (100, "RM 1.00"),
                                       (8900, "RM 89.00"), (123456789, "RM 1,234,567.89")])
def test_amount_is_shown_exactly_from_integer_sen(world, sen, shown):
    world["order"]["amount_sen"] = sen

    receipts.email_subscription_receipt(42, "SUB-ORD-1001")

    assert shown in body(parsed()[1], "html")


def test_purchaser_lookup_never_selects_credential_columns():
    source = inspect.getsource(user_repository.get_company_user_contact)
    assert '.select("email, full_name")' in source
    for secret in ("password_hash", "otp_code", "otp_expiry"):
        assert secret not in source.split('"""')[-1]


# --- once per payment ------------------------------------------------------

@pytest.fixture
def notice(monkeypatch):
    row = Mock(return_value={"id": 1})
    receipt = Mock(return_value=True)
    generic = Mock(return_value=True)
    monkeypatch.setattr(notifications, "create_billing_notification", row)
    monkeypatch.setattr(receipts, "email_subscription_receipt", receipt)
    monkeypatch.setattr("app.database.user_repository.get_company_billing_contact",
                        lambda company_id: dict(OWNER))
    monkeypatch.setattr("app.services.email_service.send_billing_notification_email", generic)
    return {"row": row, "receipt": receipt, "generic": generic}


def test_first_confirmation_sends_one_receipt_and_no_plain_notice(notice):
    notifications.notify_payment_confirmed(42, "SUB-ORD-1001")

    notice["receipt"].assert_called_once_with(42, "SUB-ORD-1001")
    notice["generic"].assert_not_called()


def test_replayed_callback_does_not_send_a_second_receipt(notice):
    notice["row"].return_value = None  # event_key already exists

    notifications.notify_payment_confirmed(42, "SUB-ORD-1001")

    notice["receipt"].assert_not_called()


def test_no_receipt_for_a_payment_that_was_never_recorded(notice):
    notice["row"].side_effect = RuntimeError("db down")

    notifications.notify_payment_confirmed(42, "SUB-ORD-1001")

    notice["receipt"].assert_not_called()


def test_receipt_failure_never_breaks_the_payment_path(notice):
    notice["receipt"].side_effect = RuntimeError("template exploded")

    notifications.notify_payment_confirmed(42, "SUB-ORD-1001")  # must not raise


def test_a_replayed_callback_against_real_dedup_sends_one_receipt(monkeypatch):
    seen = set()

    def create(**kwargs):
        """Mirror the repository: a row on first sight of an event_key, None after."""
        key = (kwargs["company_id"], kwargs["event_key"])
        if key in seen:
            return None
        seen.add(key)
        return {"id": len(seen)}

    receipt = Mock(return_value=True)
    monkeypatch.setattr(notifications, "create_billing_notification", create)
    monkeypatch.setattr(receipts, "email_subscription_receipt", receipt)

    for _ in range(3):  # CHIP retries callbacks
        notifications.notify_payment_confirmed(42, "SUB-ORD-1001")

    receipt.assert_called_once_with(42, "SUB-ORD-1001")


def test_reconciled_credit_retry_also_triggers_the_receipt(monkeypatch):
    """First activation returns early at credit_pending, before notify runs."""
    from app.services import subscription_reconciliation_service as recon

    monkeypatch.setattr(recon, "_update_state", Mock())
    monkeypatch.setattr(
        "app.database.company_subscription_order_repository.update_subscription_order_status", Mock()
    )
    confirmed = Mock()
    monkeypatch.setattr(notifications, "notify_payment_confirmed", confirmed)
    monkeypatch.setattr(notifications, "notify_reconciliation_completed", Mock())

    result = recon._retry_credit(
        {"order_reference": "SUB-ORD-1001", "company_id": 42, "new_plan_id": 3,
         "activation_sequence_key": "company:42:initial", "status": "paid"},
        "2026-09-30T05:12:00+00:00", plan_included_credit=0, plan_code="advanced",
    )

    assert result["outcome"] == "credit_retry_completed"
    confirmed.assert_called_once_with(company_id=42, order_reference="SUB-ORD-1001")


# --- review hardening ------------------------------------------------------

def test_smtp_connection_is_bounded_by_a_timeout(world):
    """The send runs inside the credited CHIP callback; a stalled server must not pin it."""
    receipts.email_subscription_receipt(42, "SUB-ORD-1001")

    assert len(FakeSMTP.timeouts) == 1
    assert FakeSMTP.timeouts[0] is not None and 0 < FakeSMTP.timeouts[0] <= 30


@pytest.mark.parametrize("address,valid", [
    ("ok+tag@sub.example.test", True),
    ("o'brien@example.test", True),
    ("a@b.co\x00", False),
    ("bé@example.test", False),       # non-ASCII would fail at sendmail after validation
    ("a@b.test\n", False),
    ("a b@example.test", False),
    ("Name <a@b.test>", False),
    ("a@b.test,c@d.test", False),
    ("no-at-sign", False),
    ("", False),
    (None, False),
])
def test_mailbox_validation(address, valid):
    from app.services.receipt_email_service import is_single_mailbox

    assert is_single_mailbox(address) is valid


def test_non_ascii_purchaser_falls_back_to_the_owner(world):
    world["buyer"] = {"email": "bé@example.test", "full_name": "Accent"}

    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is True

    assert parsed()[0] == ["owner@example.test"]


def test_missing_paid_at_falls_back_to_the_credit_time(world):
    """chip_service can store '' for paid_at; the receipt must still show a date."""
    world["order"]["paid_at"] = None

    receipts.email_subscription_receipt(42, "SUB-ORD-1001")

    assert "30 Sep 2026" in body(parsed()[1], "html")


def test_a_refused_recipient_is_not_written_to_the_log(world, monkeypatch, caplog):
    import smtplib

    class Refusing(FakeSMTP):
        def sendmail(self, sender, recipients, message):
            raise smtplib.SMTPRecipientsRefused({"buyer@example.test": (550, b"no such user")})

    monkeypatch.setattr("smtplib.SMTP", Refusing)

    assert receipts.email_subscription_receipt(42, "SUB-ORD-1001") is False
    assert "buyer@example.test" not in caplog.text


class RecordingQuery:
    """Stands in for the supabase query builder and records every filter."""

    def __init__(self, rows):
        self.rows, self.filters, self.columns = rows, [], None

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, count):
        return self

    def execute(self):
        return type("Response", (), {"data": self.rows})()


def test_purchaser_lookup_is_scoped_to_the_company_and_to_active_users(monkeypatch):
    query = RecordingQuery([{"email": " Buyer@Example.test ", "full_name": " Bea "}])
    monkeypatch.setattr(user_repository, "supabase", Mock(table=Mock(return_value=query)))

    contact = user_repository.get_company_user_contact(7, 42)

    assert {("id", 7), ("company_id", 42), ("status", "active")} <= set(query.filters)
    assert query.columns == "email, full_name"
    assert contact == {"email": "Buyer@Example.test", "full_name": "Bea"}
    assert user_repository.get_company_user_contact(None, 42) is None
    assert user_repository.get_company_user_contact(7, None) is None


# --- AI-credit top-up receipts ----------------------------------------------

def test_topup_receipt_goes_to_the_purchaser_with_the_credit_details(world):
    assert receipts.email_topup_receipt(42, "TOPUP-2001") is True

    recipients, message = parsed()
    assert message["To"] == "buyer@example.test"
    assert recipients == ["buyer@example.test", "owner@example.test"]
    assert "TOPUP-2001" in message["Subject"]
    html = body(message, "html")
    for expected in ("AI credit top-up", "RM 10.50", "AI credit added", "chip-txn-88",
                     "Acme Sdn Bhd", "30 Sep 2026", "1:20 pm MYT", "credit has been added",
                     "not a tax invoice"):
        assert expected in html, expected


@pytest.mark.parametrize("micro,shown", [
    (10_000_000, "RM 10.00"), (50_000_000, "RM 50.00"), (1_234_567, "RM 1.23"),
    (1_235_000, "RM 1.24"), (1, "RM 0.00"),
])
def test_topup_amount_is_rounded_half_up_to_the_sen(world, micro, shown):
    world["topup"]["amount_micro_myr"] = micro

    receipts.email_topup_receipt(42, "TOPUP-2001")

    assert shown in body(parsed()[1], "html")


def test_unknown_topup_order_sends_nothing(world):
    world["topup"] = None

    assert receipts.email_topup_receipt(42, "TOPUP-NOPE") is False
    assert FakeSMTP.constructed == 0


def test_topup_purchaser_falls_back_to_the_owner(world):
    world["buyer"] = None

    assert receipts.email_topup_receipt(42, "TOPUP-2001") is True

    assert parsed()[0] == ["owner@example.test"]


@pytest.fixture
def stateful_notices(monkeypatch):
    seen = set()

    def create(**kwargs):
        """Mirror the repository: a row on first sight of an event_key, None after."""
        key = (kwargs["company_id"], kwargs["event_key"])
        if key in seen:
            return None
        seen.add(key)
        return {"id": len(seen)}

    plan, topup = Mock(return_value=True), Mock(return_value=True)
    monkeypatch.setattr(notifications, "create_billing_notification", create)
    monkeypatch.setattr(receipts, "email_subscription_receipt", plan)
    monkeypatch.setattr(receipts, "email_topup_receipt", topup)
    return {"plan": plan, "topup": topup}


def test_topup_confirmation_sends_one_receipt_across_replays(stateful_notices):
    for _ in range(3):
        notifications.notify_topup_confirmed(42, "TOPUP-2001")

    stateful_notices["topup"].assert_called_once_with(42, "TOPUP-2001")
    stateful_notices["plan"].assert_not_called()


def test_a_plan_order_and_a_topup_with_the_same_reference_each_get_a_receipt(stateful_notices):
    notifications.notify_payment_confirmed(42, "SHARED-REF")
    notifications.notify_topup_confirmed(42, "SHARED-REF")

    stateful_notices["plan"].assert_called_once_with(42, "SHARED-REF")
    stateful_notices["topup"].assert_called_once_with(42, "SHARED-REF")


@pytest.fixture
def topup_callback(monkeypatch):
    from app.services import ai_credit_topup_callback_service as callback

    credit = Mock(return_value={"status": "applied", "transaction_id": 9})
    mark = Mock()
    confirmed = Mock()
    monkeypatch.setattr(callback, "_add_topup_credit", credit)
    monkeypatch.setattr(callback, "_mark_order_credited", mark)
    monkeypatch.setattr(notifications, "notify_topup_confirmed", confirmed)
    return {"module": callback, "credit": credit, "mark": mark, "confirmed": confirmed}


def apply_topup(callback):
    return callback._apply_credit_and_mark_credited(
        "TOPUP-2001", 42, 10_500_000, "chip-txn-88", "2026-09-30T05:20:00+00:00"
    )


def test_topup_callback_sends_the_receipt_once_the_credit_is_applied(topup_callback):
    result = apply_topup(topup_callback["module"])

    assert result["status"] == "credited"
    topup_callback["confirmed"].assert_called_once_with(company_id=42, order_reference="TOPUP-2001")


def test_topup_callback_sends_no_receipt_when_no_credit_transaction_exists(topup_callback):
    topup_callback["credit"].return_value = {"status": "failed"}

    with pytest.raises(RuntimeError):
        apply_topup(topup_callback["module"])

    topup_callback["confirmed"].assert_not_called()


def test_topup_callback_sends_no_receipt_when_the_order_could_not_be_marked_credited(topup_callback):
    topup_callback["mark"].side_effect = RuntimeError("db down")

    with pytest.raises(RuntimeError):
        apply_topup(topup_callback["module"])

    topup_callback["confirmed"].assert_not_called()


def test_a_failing_receipt_never_breaks_the_topup_callback(topup_callback):
    topup_callback["confirmed"].side_effect = RuntimeError("template exploded")

    assert apply_topup(topup_callback["module"])["status"] == "credited"
