"""FR-5: when platform staff post a tenant-visible reply, the requester is told
a reply is waiting - and is told nothing else.

Two properties are load-bearing here and both are tested directly:

1. **The email carries no ticket content.** Not the reply body, not the request
   title, not the description. That is what lets `support.html` promise that
   internal notes are not exposed; an email that quoted the thread would move
   the disclosure boundary without moving the page copy.
2. **The reply survives the notification.** The row is committed before any of
   this runs, so every failure below is swallowed. A support reply that 503s
   because SMTP is down is worse than a reply nobody was emailed about.

Most tests replace `_run_in_background` so the send happens on the calling
thread. `TenantReplyNotificationDispatchTests` covers the real threading seam,
where the caller's guard cannot reach.
"""

import email as email_parser
import os
import smtplib
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.services import email_service, platform_admin_service, tenant_support_service


CASE_ID = 9
COMPANY_ID = 31
REQUEST_ID = 12
REPLY_ID = 44
ACTOR_ID = 3
REQUESTER_USER_ID = 77
REQUESTER_EMAIL = "owner@tenant.example"
REPLY_BODY = "We restarted the widget provisioning on your workspace."
REQUEST_TITLE = "Widget will not load"
REQUEST_DESCRIPTION = "The onboarding widget will not load for my team."


def _run_inline(target):
    target()


def _reply_row(**overrides):
    row = {
        "id": REPLY_ID,
        "request_id": REQUEST_ID,
        "platform_support_case_id": CASE_ID,
        "company_id": COMPANY_ID,
        "author_type": "platform_admin",
        "author_platform_admin_user_id": ACTOR_ID,
        "redacted_body": REPLY_BODY,
        "visibility_status": "visible",
    }
    row.update(overrides)
    return row


def _request_row(**overrides):
    row = {
        "id": REQUEST_ID,
        "company_id": COMPANY_ID,
        "requester_user_id": REQUESTER_USER_ID,
        "category": "technical",
        "status": "converted",
        "title": REQUEST_TITLE,
        "redacted_description": REQUEST_DESCRIPTION,
    }
    row.update(overrides)
    return row


def _html_body(raw_message):
    parsed = email_parser.message_from_string(raw_message)
    for part in parsed.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError("reply notice carried no HTML body")


class _ReplyNotificationCase(unittest.TestCase):
    def setUp(self):
        tenant_support_service._notified_reply_ids.clear()
        self.addCleanup(tenant_support_service._notified_reply_ids.clear)

        request = patch.object(
            tenant_support_service.tenant_support_repository,
            "get_tenant_support_request_for_platform_admin",
            return_value=_request_row(),
        )
        self.get_request = request.start()
        self.addCleanup(request.stop)

        user = patch.object(
            tenant_support_service.user_repository,
            "get_user_by_id_for_company",
            return_value={"id": REQUESTER_USER_ID, "email": REQUESTER_EMAIL},
        )
        self.get_user = user.start()
        self.addCleanup(user.stop)

    def _inline(self):
        patcher = patch.object(
            tenant_support_service, "_run_in_background", _run_inline
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _mailer(self, **kwargs):
        patcher = patch.object(
            email_service, "send_tenant_support_reply_notification_email", **kwargs
        )
        mailer = patcher.start()
        self.addCleanup(patcher.stop)
        return mailer

    def _smtp_env(self, **overrides):
        values = {
            "SMTP_SENDER_EMAIL": "noreply@example.test",
            "SMTP_APP_PASSWORD": "smtp-app-password",
            "FRONTEND_URL": "https://app.example.test",
        }
        values.update(overrides)
        patcher = patch.dict(
            os.environ, {k: v for k, v in values.items() if v is not None}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)

    def _capture_sent_message(self):
        sent = []
        server = MagicMock()
        server.sendmail.side_effect = lambda sender, to, body: sent.append((sender, to, body))
        patcher = patch.object(email_service.smtplib, "SMTP", return_value=server)
        self.smtp = patcher.start()
        self.addCleanup(patcher.stop)
        return sent


class TenantReplyNotificationTests(_ReplyNotificationCase):
    """The guards on `notify_tenant_of_reply` itself."""

    def test_a_tenant_visible_reply_emails_the_requester_once(self):
        self._inline()
        mailer = self._mailer()
        tenant_support_service.notify_tenant_of_reply(_reply_row())
        mailer.assert_called_once_with(REQUESTER_EMAIL, request_id=REQUEST_ID)

    def test_the_same_reply_is_never_notified_twice(self):
        self._inline()
        mailer = self._mailer()
        reply = _reply_row()
        tenant_support_service.notify_tenant_of_reply(reply)
        tenant_support_service.notify_tenant_of_reply(dict(reply))
        mailer.assert_called_once()

    def test_a_second_distinct_reply_is_still_notified(self):
        # Guards the dedup from being a blanket "only ever send once" switch.
        self._inline()
        mailer = self._mailer()
        tenant_support_service.notify_tenant_of_reply(_reply_row())
        tenant_support_service.notify_tenant_of_reply(_reply_row(id=REPLY_ID + 1))
        self.assertEqual(mailer.call_count, 2)

    def test_a_reply_that_is_not_tenant_visible_is_never_notified(self):
        self._inline()
        mailer = self._mailer()
        tenant_support_service.notify_tenant_of_reply(
            _reply_row(visibility_status="internal")
        )
        mailer.assert_not_called()

    def test_a_reply_that_is_not_authored_by_staff_is_never_notified(self):
        self._inline()
        mailer = self._mailer()
        tenant_support_service.notify_tenant_of_reply(_reply_row(author_type="tenant"))
        mailer.assert_not_called()

    def test_a_malformed_reply_is_never_notified(self):
        self._inline()
        mailer = self._mailer()
        for reply in (None, [], {}, _reply_row(id=0), _reply_row(request_id="12"),
                      _reply_row(company_id=None), _reply_row(id=True)):
            tenant_support_service.notify_tenant_of_reply(reply)
        mailer.assert_not_called()

    # --- the two guards the outer `except Exception` hides -----------------
    #
    # Deleting either isinstance check below still sends no email: the
    # AttributeError it lets through is swallowed by the surrounding handler.
    # A mutation audit found both guards survived every other test in this
    # file for exactly that reason. What the guard actually buys is the
    # *absence of an error log* - a routine condition must not look like a
    # fault - so that is what these two assert.

    def test_a_non_dict_reply_is_ignored_without_logging_an_error(self):
        self._inline()
        mailer = self._mailer()

        with self.assertNoLogs("app.services.tenant_support_service", level="ERROR"):
            tenant_support_service.notify_tenant_of_reply(None)

        mailer.assert_not_called()

    def test_a_missing_user_row_is_a_normal_outcome_not_an_error(self):
        self._inline()
        mailer = self._mailer()
        self.get_user.return_value = None

        with self.assertNoLogs("app.services.tenant_support_service", level="ERROR"):
            tenant_support_service.notify_tenant_of_reply(_reply_row(id=4401))

        mailer.assert_not_called()

    # --- recipient resolution is tenant-scoped -----------------------------

    def test_the_requester_is_looked_up_inside_the_reply_company(self):
        self._inline()
        self._mailer()
        tenant_support_service.notify_tenant_of_reply(_reply_row())
        self.get_user.assert_called_once_with(REQUESTER_USER_ID, COMPANY_ID)

    def test_no_email_when_the_request_belongs_to_another_company(self):
        self._inline()
        mailer = self._mailer()
        self.get_request.return_value = _request_row(company_id=COMPANY_ID + 1)
        tenant_support_service.notify_tenant_of_reply(_reply_row())
        mailer.assert_not_called()

    def test_no_email_when_the_request_row_is_missing(self):
        self._inline()
        mailer = self._mailer()
        self.get_request.return_value = None
        tenant_support_service.notify_tenant_of_reply(_reply_row())
        mailer.assert_not_called()

    def test_no_email_when_the_requester_user_is_missing_or_has_no_address(self):
        self._inline()
        mailer = self._mailer()
        for user in (None, {}, {"id": REQUESTER_USER_ID, "email": "   "},
                     {"id": REQUESTER_USER_ID, "email": None}):
            tenant_support_service._notified_reply_ids.clear()
            self.get_user.return_value = user
            tenant_support_service.notify_tenant_of_reply(_reply_row())
        mailer.assert_not_called()

    def test_no_email_when_the_request_has_no_requester(self):
        self._inline()
        mailer = self._mailer()
        self.get_request.return_value = _request_row(requester_user_id=None)
        tenant_support_service.notify_tenant_of_reply(_reply_row())
        mailer.assert_not_called()
        self.get_user.assert_not_called()

    # --- nothing here may break the reply ----------------------------------

    def test_a_failing_requester_lookup_is_contained(self):
        self._inline()
        mailer = self._mailer()
        self.get_request.side_effect = RuntimeError("supabase down")
        tenant_support_service.notify_tenant_of_reply(_reply_row())
        mailer.assert_not_called()

    def test_a_failing_mailer_is_contained(self):
        self._inline()
        self._mailer(side_effect=smtplib.SMTPException("SMTP is down"))
        tenant_support_service.notify_tenant_of_reply(_reply_row())

    def test_a_failing_dispatch_is_contained(self):
        with patch.object(
            tenant_support_service,
            "_run_in_background",
            side_effect=RuntimeError("cannot start new thread"),
        ):
            tenant_support_service.notify_tenant_of_reply(_reply_row())

    def test_the_recipient_lookup_runs_off_the_request_thread(self):
        # The two round-trips that resolve the recipient must not be paid for by
        # the staff member waiting on POST .../replies.
        with patch.object(tenant_support_service, "_run_in_background") as spawn:
            tenant_support_service.notify_tenant_of_reply(_reply_row())
        spawn.assert_called_once()
        self.get_request.assert_not_called()
        self.get_user.assert_not_called()


class TenantReplyNoticeContentTests(_ReplyNotificationCase):
    """What the notice is - and is not - allowed to carry."""

    def _send(self, **reply_overrides):
        self._inline()
        sent = self._capture_sent_message()
        tenant_support_service.notify_tenant_of_reply(_reply_row(**reply_overrides))
        return sent

    def test_the_notice_reaches_the_requester_and_names_the_request(self):
        self._smtp_env()
        sent = self._send()
        self.assertEqual(len(sent), 1)
        _sender, recipient, raw = sent[0]
        self.assertEqual(recipient, REQUESTER_EMAIL)
        self.assertIn(str(REQUEST_ID), _html_body(raw))

    def test_the_notice_carries_no_ticket_content(self):
        self._smtp_env()
        raw = self._send()[0][2]
        self.assertNotIn(REPLY_BODY, raw)
        self.assertNotIn(REQUEST_TITLE, raw)
        self.assertNotIn(REQUEST_DESCRIPTION, raw)

    def test_the_notice_carries_no_credentials(self):
        self._smtp_env()
        raw = self._send()[0][2]
        self.assertNotIn("smtp-app-password", raw)

    def test_the_notice_links_to_the_support_page_when_the_app_url_is_set(self):
        self._smtp_env()
        body = _html_body(self._send()[0][2])
        self.assertIn("https://app.example.test/support.html", body)

    def test_the_notice_omits_the_link_rather_than_building_a_broken_one(self):
        self._smtp_env(FRONTEND_URL=None)
        body = _html_body(self._send()[0][2])
        self.assertNotIn("/support.html", body)
        self.assertNotIn("href=", body)

    def test_a_hostile_app_url_cannot_break_out_of_the_href(self):
        self._smtp_env(FRONTEND_URL='https://x.test/" onmouseover="alert(1)')
        body = _html_body(self._send()[0][2])
        self.assertNotIn('onmouseover="alert(1)"', body)
        self.assertIn("&quot;", body)

    def test_nothing_is_sent_when_smtp_credentials_are_missing(self):
        self._smtp_env(SMTP_APP_PASSWORD=None)
        self.assertEqual(self._send(), [])

    def test_the_smtp_connection_is_bounded_by_a_socket_timeout(self):
        self._smtp_env()
        self._send()
        self.smtp.assert_called_once_with(
            "smtp.gmail.com",
            587,
            timeout=email_service.SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS,
        )

    def test_the_sender_cannot_be_handed_ticket_content_at_all(self):
        # The strongest guarantee available: the signature has nowhere to put a
        # subject, a body or a description, so no future caller can leak one.
        with self.assertRaises(TypeError):
            email_service.send_tenant_support_reply_notification_email(
                REQUESTER_EMAIL, request_id=REQUEST_ID, redacted_body=REPLY_BODY
            )


class TenantReplyNotificationCallSiteTests(_ReplyNotificationCase):
    """The hook must sit on the one path that creates a tenant-visible reply."""

    def _rpc_result(self):
        return {
            "case": {
                "id": CASE_ID, "company_id": COMPANY_ID, "status": "in_progress",
                "priority": "normal", "title": "Safe", "redacted_summary": "Safe",
            },
            "event": {
                "id": 20, "case_id": CASE_ID, "event_type": "tenant_reply_created",
                "tenant_support_reply_id": REPLY_ID,
            },
            "reply": _reply_row(),
            "notification": {
                "id": 50, "reply_id": REPLY_ID, "channel": "in_app",
                "status": "pending",
            },
        }

    def _patch_case_path(self, **rpc_kwargs):
        for patcher in (
            patch.object(
                platform_admin_service.platform_support_case_repository,
                "get_support_case_for_platform_admin",
                return_value={
                    "id": CASE_ID, "company_id": COMPANY_ID,
                    "status": "open", "priority": "normal",
                },
            ),
            patch.object(
                platform_admin_service.platform_support_case_repository,
                "create_support_case_reply_for_platform_admin",
                **(rpc_kwargs or {"return_value": self._rpc_result()}),
            ),
            patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin",
                return_value={"id": COMPANY_ID, "company_name": "Tenant", "status": "active"},
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_creating_a_reply_notifies_the_requester(self):
        self._inline()
        self._patch_case_path()
        mailer = self._mailer()
        result = platform_admin_service.create_support_case_reply(
            CASE_ID, {"redacted_body": REPLY_BODY}, ACTOR_ID
        )
        self.assertEqual(result["reply"]["reply_id"], REPLY_ID)
        mailer.assert_called_once_with(REQUESTER_EMAIL, request_id=REQUEST_ID)

    def test_a_failing_notification_never_fails_the_reply(self):
        self._inline()
        self._patch_case_path()
        self._mailer(side_effect=smtplib.SMTPException("SMTP is down"))
        result = platform_admin_service.create_support_case_reply(
            CASE_ID, {"redacted_body": REPLY_BODY}, ACTOR_ID
        )
        self.assertEqual(result["reply"]["reply_id"], REPLY_ID)

    def test_a_rejected_reply_notifies_nobody(self):
        self._inline()
        mailer = self._mailer()
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError):
            platform_admin_service.create_support_case_reply(
                CASE_ID, {"redacted_body": "   "}, ACTOR_ID
            )
        mailer.assert_not_called()

    def test_a_failed_reply_rpc_notifies_nobody(self):
        self._inline()
        self._patch_case_path(
            side_effect=RuntimeError("create_platform_support_case_reply RPC returned raw mismatch")
        )
        mailer = self._mailer()
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError):
            platform_admin_service.create_support_case_reply(
                CASE_ID, {"redacted_body": REPLY_BODY}, ACTOR_ID
            )
        mailer.assert_not_called()

    def test_an_internal_note_notifies_nobody(self):
        # Notes are `platform_support_case_events.redacted_note` rows; they never
        # touch `tenant_support_replies`, so this path must stay silent.
        self._inline()
        mailer = self._mailer()
        for patcher in (
            patch.object(
                platform_admin_service.platform_support_case_repository,
                "get_support_case_for_platform_admin",
                return_value={
                    "id": CASE_ID, "company_id": COMPANY_ID,
                    "status": "open", "priority": "normal",
                },
            ),
            patch.object(
                platform_admin_service.platform_support_case_repository,
                "add_support_case_note_for_platform_admin",
                return_value={
                    "case": {
                        "id": CASE_ID, "company_id": COMPANY_ID, "status": "open",
                        "priority": "normal", "title": "Safe", "redacted_summary": "Safe",
                    },
                    "event": {
                        "id": 21, "case_id": CASE_ID, "event_type": "note_added",
                        "redacted_note": "Internal: escalate to engineering",
                    },
                },
            ),
            patch.object(
                platform_admin_service.platform_company_repository,
                "get_company_for_platform_admin",
                return_value={"id": COMPANY_ID, "company_name": "Tenant", "status": "active"},
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        platform_admin_service.add_support_case_note(
            CASE_ID, {"redacted_note": "Internal: escalate to engineering"}, ACTOR_ID
        )
        mailer.assert_not_called()


class TenantReplyNotificationDispatchTests(_ReplyNotificationCase):
    """The real daemon thread - the only cover for the guard inside the worker.

    The inline tests above reach the caller's guard first and would pass with
    that inner guard deleted.
    """

    def test_a_failing_mailer_is_contained_inside_the_worker_thread(self):
        handled = threading.Event()
        logged = []

        def record_error(*args, **kwargs):
            logged.append(args)
            handled.set()

        with patch.object(
            email_service,
            "send_tenant_support_reply_notification_email",
            side_effect=smtplib.SMTPException("SMTP is down"),
        ), patch.object(tenant_support_service.logger, "error", record_error):
            tenant_support_service.notify_tenant_of_reply(_reply_row())
            self.assertTrue(
                handled.wait(5), "the worker thread never handled the mailer failure"
            )

        self.assertIn("Tenant reply notification failed for reply %s", logged[0])

    def test_the_notice_really_runs_on_a_separate_daemon_thread(self):
        seen = {}
        finished = threading.Event()

        def mailer(*args, **kwargs):
            seen["thread"] = threading.current_thread()
            finished.set()

        with patch.object(
            email_service, "send_tenant_support_reply_notification_email", mailer
        ):
            tenant_support_service.notify_tenant_of_reply(_reply_row())
            self.assertTrue(finished.wait(5), "the notice never ran")

        self.assertIsNot(seen["thread"], threading.current_thread())
        self.assertTrue(seen["thread"].daemon)


if __name__ == "__main__":
    unittest.main()
