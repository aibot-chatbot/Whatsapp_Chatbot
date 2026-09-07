"""The platform support inbox must hear about an escalation, and must never be
able to break the ticket that triggered it.

Every test here runs the notification on the calling thread by replacing
`_run_in_background`. That is deliberate: in production the send happens on a
daemon thread, where an exception could never reach the caller anyway, so a
threaded test would pass even with the guards deleted and would prove nothing.
`TenantSupportNotificationDispatchTests` covers the real threading seam.
"""

import email as email_parser
import os
import smtplib
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.services import email_service, tenant_support_service


VALID_PAYLOAD = {
    "category": "technical",
    "title": "Widget setup question",
    "redacted_description": "The onboarding widget will not load for my team.",
}
INBOX = "platform-support@example.test"


def _run_inline(target):
    target()


def _html_body(raw_message):
    parsed = email_parser.message_from_string(raw_message)
    for part in parsed.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError("notification carried no HTML body")


class TenantSupportNotificationTests(unittest.TestCase):
    def setUp(self):
        tenant_support_service._inbox_unset_logged = False
        self.addCleanup(setattr, tenant_support_service, "_inbox_unset_logged", False)
        create = patch.object(
            tenant_support_service.tenant_support_repository,
            "create_tenant_support_request",
            return_value=4321,
        )
        self.create_request = create.start()
        self.addCleanup(create.stop)
        inline = patch.object(tenant_support_service, "_run_in_background", _run_inline)
        inline.start()
        self.addCleanup(inline.stop)

    def _submit(self, **overrides):
        payload = dict(VALID_PAYLOAD, **overrides)
        return tenant_support_service.submit_tenant_support_request(
            payload, company_id=100, requester_user_id=7
        )

    def _with_env(self, **values):
        patcher = patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (
            tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV,
            "SMTP_SENDER_EMAIL",
            "SMTP_APP_PASSWORD",
        ):
            if name not in values:
                os.environ.pop(name, None)

    def _smtp_env(self):
        self._with_env(**{
            tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: INBOX,
            "SMTP_SENDER_EMAIL": "noreply@example.test",
            "SMTP_APP_PASSWORD": "smtp-app-password",
        })

    def _capture_sent_message(self):
        sent = []
        server = MagicMock()
        server.sendmail.side_effect = lambda sender, to, body: sent.append((sender, to, body))
        patcher = patch.object(email_service.smtplib, "SMTP", return_value=server)
        patcher.start()
        self.addCleanup(patcher.stop)
        return sent

    # --- the ticket always survives the notification -----------------------

    def test_request_id_is_returned_when_the_mailer_raises(self):
        self._with_env(**{tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: INBOX})
        with patch.object(
            email_service,
            "send_tenant_support_request_notification_email",
            side_effect=smtplib.SMTPException("SMTP is down"),
        ) as mailer:
            self.assertEqual(self._submit(), {"request_id": 4321})
        mailer.assert_called_once()

    def test_request_id_is_returned_when_the_notification_cannot_be_dispatched(self):
        self._with_env(**{tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: INBOX})
        with patch.object(
            tenant_support_service,
            "_run_in_background",
            side_effect=RuntimeError("cannot start new thread"),
        ):
            self.assertEqual(self._submit(), {"request_id": 4321})

    # --- unset recipient disables the feature entirely ---------------------

    def test_nothing_is_sent_when_the_inbox_email_is_unset(self):
        self._with_env()
        with patch.object(
            email_service, "send_tenant_support_request_notification_email"
        ) as mailer:
            self.assertEqual(self._submit(), {"request_id": 4321})
        mailer.assert_not_called()

    def test_a_blank_inbox_email_is_treated_as_unset(self):
        # .env.txt ships the placeholder as an empty string, so dotenv loads ""
        # rather than leaving the name unset.
        self._with_env(**{tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: "   "})
        with patch.object(
            email_service, "send_tenant_support_request_notification_email"
        ) as mailer:
            self._submit()
        mailer.assert_not_called()

    def test_the_missing_inbox_is_logged_once_not_once_per_request(self):
        self._with_env()
        with patch.object(email_service, "send_tenant_support_request_notification_email"):
            with self.assertLogs(tenant_support_service.logger, level="INFO") as logs:
                self._submit()
                self._submit()
                self._submit()
        notices = [
            record
            for record in logs.records
            if tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV in record.getMessage()
        ]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].levelname, "INFO")

    # --- what the notification is allowed to carry -------------------------

    def test_notification_carries_the_request_id_category_and_status(self):
        self._smtp_env()
        sent = self._capture_sent_message()
        self._submit()

        self.assertEqual(len(sent), 1)
        _sender, recipient, raw = sent[0]
        self.assertEqual(recipient, INBOX)
        body = _html_body(raw)
        self.assertIn("Request ID", body)
        self.assertIn("4321", body)
        self.assertIn("Category", body)
        self.assertIn("technical", body)
        self.assertIn("Status", body)
        self.assertIn(tenant_support_service.NEW_REQUEST_STATUS, body)
        self.assertIn("100", body)
        self.assertIn(VALID_PAYLOAD["redacted_description"], body)

    def test_notification_omits_credentials_and_unredacted_free_text(self):
        self._smtp_env()
        sent = self._capture_sent_message()
        self._submit()

        raw = sent[0][2]
        self.assertNotIn("smtp-app-password", raw)
        # `redacted_description` is the only free text cleared for the platform
        # inbox; the title never crosses the tenant boundary.
        self.assertNotIn(VALID_PAYLOAD["title"], raw)

    def test_a_long_description_is_bounded(self):
        limit = tenant_support_service.NOTIFICATION_DESCRIPTION_LIMIT
        self._smtp_env()
        sent = self._capture_sent_message()
        self._submit(redacted_description="Q" * (limit + 400))

        body = _html_body(sent[0][2])
        self.assertIn("Q" * limit, body)
        self.assertNotIn("Q" * (limit + 1), body)
        self.assertIn(tenant_support_service.TRUNCATION_MARKER, body)

    def test_description_markup_is_escaped_not_injected(self):
        self._smtp_env()
        sent = self._capture_sent_message()
        self._submit(redacted_description='<a href="http://evil.test">click</a>')

        body = _html_body(sent[0][2])
        self.assertNotIn('<a href="http://evil.test">', body)
        self.assertIn("&lt;a href=", body)

    def test_the_smtp_connection_is_bounded_by_a_socket_timeout(self):
        # This send runs on a daemon thread, so a hung SMTP server would leak a
        # thread rather than fail a request. Nothing else in the suite notices
        # if the timeout is dropped.
        self._smtp_env()
        server = MagicMock()
        with patch.object(
            email_service.smtplib, "SMTP", return_value=server
        ) as smtp:
            self._submit()
        smtp.assert_called_once_with(
            "smtp.gmail.com",
            587,
            timeout=email_service.SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS,
        )

    def test_nothing_is_sent_when_smtp_credentials_are_missing(self):
        self._with_env(**{tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: INBOX})
        sent = self._capture_sent_message()
        self.assertEqual(self._submit(), {"request_id": 4321})
        self.assertEqual(sent, [])

    # --- the notification never runs before the row exists -----------------

    def test_no_notification_is_sent_when_the_submission_fails(self):
        self._with_env(**{tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: INBOX})
        self.create_request.side_effect = RuntimeError("RPC down")
        with patch.object(
            email_service, "send_tenant_support_request_notification_email"
        ) as mailer:
            with self.assertRaises(tenant_support_service.TenantSupportServiceError):
                self._submit()
        mailer.assert_not_called()

    def test_no_notification_is_sent_for_a_rejected_payload(self):
        self._with_env(**{tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: INBOX})
        with patch.object(
            email_service, "send_tenant_support_request_notification_email"
        ) as mailer:
            with self.assertRaises(tenant_support_service.TenantSupportServiceError):
                self._submit(category="not_a_category")
        mailer.assert_not_called()


class TenantSupportNotificationDispatchTests(unittest.TestCase):
    """The seam the tests above replace must really get off the request thread.

    These run the genuine daemon thread, so they are the only cover for the
    guard inside the worker; the inline tests above reach the caller's guard
    first and would pass without it.
    """

    def test_a_failing_mailer_is_contained_inside_the_worker_thread(self):
        handled = threading.Event()
        logged = []

        def record_error(*args, **kwargs):
            logged.append(args)
            handled.set()

        with patch.dict(os.environ, {tenant_support_service.PLATFORM_SUPPORT_INBOX_ENV: INBOX}), \
                patch.object(
                    tenant_support_service.tenant_support_repository,
                    "create_tenant_support_request",
                    return_value=99,
                ), \
                patch.object(
                    email_service,
                    "send_tenant_support_request_notification_email",
                    side_effect=smtplib.SMTPException("SMTP is down"),
                ), \
                patch.object(tenant_support_service.logger, "error", record_error):
            result = tenant_support_service.submit_tenant_support_request(
                dict(VALID_PAYLOAD), company_id=100, requester_user_id=7
            )
            self.assertEqual(result, {"request_id": 99})
            self.assertTrue(
                handled.wait(5), "the worker thread never handled the mailer failure"
            )

        self.assertIn("Tenant support notification failed for request %s", logged[0])

    def test_background_dispatch_runs_on_a_separate_daemon_thread(self):
        observed = {}
        finished = threading.Event()

        def target():
            observed["thread"] = threading.current_thread()
            finished.set()

        tenant_support_service._run_in_background(target)

        self.assertTrue(finished.wait(5), "background target never ran")
        self.assertIsNot(observed["thread"], threading.current_thread())
        self.assertTrue(observed["thread"].daemon)


if __name__ == "__main__":
    unittest.main()
