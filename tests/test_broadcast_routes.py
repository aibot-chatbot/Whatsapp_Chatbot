import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import unittest
from unittest.mock import patch, MagicMock
import types

# Mock standard broken imports
if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app

MOCK_USER = {
    "id": 1,
    "company_id": 42,
    "full_name": "Test User",
    "email": "test@example.com",
    "role": "admin",
    "status": "active",
}

class TestBroadcastRoutes(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaigns")
    def test_list_campaigns_success(self, mock_get_campaigns, mock_verify):
        mock_get_campaigns.return_value = [{"id": 10, "name": "Camp A", "status": "draft"}]

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/broadcast/campaigns?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["campaigns"][0]["name"], "Camp A")

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.create_campaign")
    @patch("app.routes.broadcast_routes.create_broadcast_log")
    def test_save_campaign_success(self, mock_create_log, mock_create_campaign, mock_verify):
        mock_create_campaign.return_value = {"id": 10, "name": "Camp A", "channel_type": "whatsapp", "status": "draft"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/broadcast/campaign?chatbot_id=1",
                json={
                    "name": "Camp A",
                    "channel_type": "whatsapp",
                    "message_template": "Hello {{phone}}",
                    "recipients": [{"phone": "+60123456789", "name": "Alice"}]
                },
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["campaign"]["name"], "Camp A")
            mock_create_log.assert_called_once()

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.get_broadcast_logs_by_campaign")
    def test_get_campaign_logs_success(self, mock_get_logs, mock_get_campaign, mock_verify):
        mock_get_campaign.return_value = {"id": 10, "name": "Camp A"}
        mock_get_logs.return_value = [{"id": 1, "recipient_phone": "+60123456789", "status": "pending"}]

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/broadcast/campaign/10/logs?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["logs"][0]["recipient_phone"], "+60123456789")

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.get_broadcast_logs_by_campaign")
    @patch("app.database.broadcast_repository.supabase")
    @patch("app.routes.broadcast_routes.threading.Thread")
    def test_start_campaign_success(self, thread, db, logs, campaign, verify):
        campaign.return_value = {"id": 10, "status": "draft", "company_id": 42, "chatbot_id": 1}
        logs.return_value = [{"id": 1, "recipient_phone": "+60123456789", "status": "pending"}]
        query = db.table.return_value.update.return_value
        query.eq.return_value = query
        query.execute.return_value.data = [{"id": 10}]

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post("/api/broadcast/campaign/10/start?chatbot_id=1",
                                    json={"consent_confirmed": True},
                                    headers={"Authorization": "Bearer test-token"})
        self.assertEqual(resp.status_code, 200)
        fields = db.table.return_value.update.call_args.args[0]
        self.assertEqual(fields["status"], "sending")
        self.assertEqual(fields["consent_confirmed_by"], 1)
        from datetime import datetime
        self.assertIsNotNone(datetime.fromisoformat(fields["consent_confirmed_at"]).tzinfo)
        self.assertIn(unittest.mock.call("company_id", 42), query.eq.call_args_list)
        self.assertIn(unittest.mock.call("status", "draft"), query.eq.call_args_list)
        thread.return_value.start.assert_called_once()

    @patch("app.routes.broadcast_routes.threading.Thread")
    @patch("app.routes.broadcast_routes.get_broadcast_logs_by_campaign")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    def test_start_requires_explicit_boolean_consent(self, verify, campaign, logs, thread):
        campaign.return_value = {"id": 10, "status": "draft", "company_id": 42, "chatbot_id": 1}
        logs.return_value = [{"id": 1, "status": "pending"}]
        with self._patch_jwt_decode(), self._patch_user_repo():
            for body in (None, {}, [], {"consent_confirmed": False}, {"consent_confirmed": 1},
                         {"consent_confirmed": "true"}):
                with self.subTest(body=body):
                    resp = self.client.post("/api/broadcast/campaign/10/start?chatbot_id=1",
                                            json=body, headers={"Authorization": "Bearer test-token"})
                    self.assertEqual(resp.status_code, 400)
                    self.assertIn("permission", resp.get_json()["message"].lower())
        thread.assert_not_called()

if __name__ == "__main__":
    unittest.main()


class TestBroadcastCampaignLifecycle(unittest.TestCase):
    """Delete, edit, progress and cancel.

    These four exist because the dispatch worker paces at one message every
    three seconds: a 250-recipient campaign runs for over twelve minutes,
    and before this there was no way to watch it, stop it, fix a draft, or
    remove a mistake.
    """

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value=MOCK_USER,
        )

    def _headers(self):
        return {"Authorization": "Bearer test-token"}

    # -- Delete --------------------------------------------------------

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.delete_campaign")
    def test_delete_removes_a_draft(self, mock_delete, mock_get, mock_verify):
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "draft"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/broadcast/campaign/10?chatbot_id=1", headers=self._headers()
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "success")
        mock_delete.assert_called_once_with(10, 42)

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.delete_campaign")
    def test_delete_refuses_while_sending(self, mock_delete, mock_get, mock_verify):
        """The worker still holds these rows; deleting mid-send strands it."""
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "sending"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/broadcast/campaign/10?chatbot_id=1", headers=self._headers()
            )

        self.assertEqual(resp.status_code, 400)
        mock_delete.assert_not_called()

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    def test_delete_missing_campaign_is_404(self, mock_get, mock_verify):
        mock_get.return_value = None

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/broadcast/campaign/999?chatbot_id=1", headers=self._headers()
            )

        self.assertEqual(resp.status_code, 404)

    # -- Edit ----------------------------------------------------------

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.update_campaign")
    @patch("app.routes.broadcast_routes.delete_broadcast_logs_by_campaign")
    @patch("app.routes.broadcast_routes.create_broadcast_log")
    def test_edit_replaces_recipients_and_dedupes(
        self, mock_create_log, mock_delete_logs, mock_update, mock_get, mock_verify
    ):
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "draft"}
        mock_update.return_value = {"id": 10, "name": "Camp B", "status": "draft"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.patch(
                "/api/broadcast/campaign/10?chatbot_id=1",
                headers=self._headers(),
                json={
                    "name": "Camp B",
                    "recipients": [
                        {"phone": "+6012 345 6789"},
                        {"phone": "+60123456789"},
                        {"phone": "+60198887777"},
                    ],
                },
            )

        self.assertEqual(resp.status_code, 200)
        mock_delete_logs.assert_called_once_with(10)
        # The first two rows are the same number written two ways.
        self.assertEqual(mock_create_log.call_count, 2)
        written = [call.args[1] for call in mock_create_log.call_args_list]
        self.assertEqual(written, ["+60123456789", "+60198887777"])

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.update_campaign")
    def test_edit_refuses_a_dispatched_campaign(self, mock_update, mock_get, mock_verify):
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "completed"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.patch(
                "/api/broadcast/campaign/10?chatbot_id=1",
                headers=self._headers(),
                json={"name": "Camp B"},
            )

        self.assertEqual(resp.status_code, 400)
        mock_update.assert_not_called()

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.update_campaign")
    @patch("app.routes.broadcast_routes.delete_broadcast_logs_by_campaign")
    @patch("app.routes.broadcast_routes.create_broadcast_log")
    def test_edit_rejects_an_all_invalid_recipient_list(
        self, mock_create_log, mock_delete_logs, mock_update, mock_get, mock_verify
    ):
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "draft"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.patch(
                "/api/broadcast/campaign/10?chatbot_id=1",
                headers=self._headers(),
                json={"recipients": [{"phone": "not-a-number"}]},
            )

        self.assertEqual(resp.status_code, 400)
        mock_delete_logs.assert_not_called()

    # -- Progress ------------------------------------------------------

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.count_broadcast_logs_by_status")
    def test_progress_counts_only_finished_recipients_as_done(
        self, mock_counts, mock_get, mock_verify
    ):
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "sending"}
        mock_counts.return_value = {
            "sent": 5,
            "failed": 2,
            "cancelled": 1,
            "pending": 3,
            "sending": 1,
        }

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.get(
                "/api/broadcast/campaign/10/progress?chatbot_id=1", headers=self._headers()
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total"], 12)
        # The one currently in flight is not done yet.
        self.assertEqual(data["done"], 8)
        self.assertEqual(data["campaign_status"], "sending")

    # -- Cancel --------------------------------------------------------

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.update_campaign_status")
    @patch("app.routes.broadcast_routes.count_broadcast_logs_by_status")
    @patch("app.routes.broadcast_routes.cancel_pending_broadcast_logs")
    def test_cancel_asks_the_worker_to_stop_without_touching_rows(
        self, mock_cancel_logs, mock_counts, mock_status, mock_get, mock_verify
    ):
        """A live send stops by flipping the status, not by clearing rows.

        The worker owns those rows between messages; clearing them here would
        race with its own write.
        """
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "sending"}
        mock_counts.return_value = {"pending": 7, "sent": 3}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/broadcast/campaign/10/cancel?chatbot_id=1", headers=self._headers()
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["campaign_status"], "cancelling")
        mock_status.assert_called_once_with(10, 42, "cancelling")
        mock_cancel_logs.assert_not_called()

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.update_campaign_status")
    @patch("app.routes.broadcast_routes.cancel_pending_broadcast_logs")
    def test_cancel_clears_a_draft_immediately(
        self, mock_cancel_logs, mock_status, mock_get, mock_verify
    ):
        """No worker is running, so nothing can race and the rows go now."""
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "draft"}
        mock_cancel_logs.return_value = 4

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/broadcast/campaign/10/cancel?chatbot_id=1", headers=self._headers()
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["campaign_status"], "cancelled")
        mock_cancel_logs.assert_called_once_with(10)
        mock_status.assert_called_once_with(10, 42, "cancelled")

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.update_campaign_status")
    def test_cancel_refuses_a_finished_campaign(self, mock_status, mock_get, mock_verify):
        mock_get.return_value = {"id": 10, "name": "Camp A", "status": "completed"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/broadcast/campaign/10/cancel?chatbot_id=1", headers=self._headers()
            )

        self.assertEqual(resp.status_code, 400)
        mock_status.assert_not_called()

    # -- Start ---------------------------------------------------------

    @patch("app.routes.broadcast_routes.verify_chatbot_access")
    @patch("app.routes.broadcast_routes.get_campaign_by_id")
    @patch("app.routes.broadcast_routes.get_broadcast_logs_by_campaign")
    def test_start_refuses_a_cancelled_campaign(self, mock_logs, mock_get, mock_verify):
        """Its recipients are cancelled, not pending.

        Without this guard the route finds nothing pending and quietly marks
        the campaign completed, which reads as "it sent" when it did not.
        """
        mock_get.return_value = {"id": 10, "name": "Camp A", "chatbot_id": 1, "status": "cancelled"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/broadcast/campaign/10/start?chatbot_id=1", headers=self._headers(), json={"consent_confirmed": True}
            )

        self.assertEqual(resp.status_code, 400)
        mock_logs.assert_not_called()


class TestBroadcastWorkerCancellation(unittest.TestCase):
    """The dispatch worker is the only thing that can stop a live send.

    It owns the pacing sleep between messages, so cancellation is a flag it
    polls rather than something the route can act on directly.
    """

    def _dispatch(self, statuses, pending_logs):
        from types import SimpleNamespace
        from app.routes import broadcast_routes

        campaign = {
            "id": 12,
            "company_id": 42,
            "chatbot_id": 9,
            "channel_type": "whatsapp",
            "message_template": "Hello {{phone}}",
        }

        with patch(
            "app.services.company_status_service.get_company_status_by_id",
            return_value={"id": 42, "status": "active"},
        ), patch(
            "app.database.whatsapp_channel_repository.get_whatsapp_channels_by_chatbot",
            return_value=[{"id": 1, "is_active": True, "access_token": "token"}],
        ), patch(
            "app.utils.whatsapp_utils.send_message",
            return_value=SimpleNamespace(status_code=200, text="ok"),
        ) as send_message, patch(
            "app.routes.broadcast_routes.is_marketing_phone_withdrawn", return_value=False
        ), patch(
            "app.routes.broadcast_routes.get_campaign_by_id", side_effect=statuses
        ), patch(
            "app.routes.broadcast_routes.cancel_pending_broadcast_logs", return_value=2
        ) as cancel_logs, patch(
            "app.routes.broadcast_routes.update_broadcast_log_status"
        ) as update_log, patch(
            "app.routes.broadcast_routes.update_campaign_status"
        ) as update_status, patch(
            "app.routes.broadcast_routes.time.sleep"
        ):
            broadcast_routes.process_broadcast_dispatch(create_app(), campaign, pending_logs)

        return send_message, cancel_logs, update_log, update_status

    def _logs(self, count):
        return [
            {"id": 100 + i, "recipient_phone": "+6011111111" + str(i), "status": "pending"}
            for i in range(count)
        ]

    def test_worker_stops_at_the_next_message_after_cancel(self):
        sending = {"id": 12, "company_id": 42, "status": "sending"}
        cancelling = {"id": 12, "company_id": 42, "status": "cancelling"}

        send_message, cancel_logs, _update_log, update_status = self._dispatch(
            [sending, cancelling], self._logs(3)
        )

        # The message already in flight goes out; the rest never do.
        send_message.assert_called_once()
        cancel_logs.assert_called_once_with(12)
        update_status.assert_called_with(12, 42, "cancelled")

    def test_worker_runs_to_completion_when_nobody_cancels(self):
        sending = {"id": 12, "company_id": 42, "status": "sending"}

        send_message, cancel_logs, _update_log, update_status = self._dispatch(
            [sending, sending, sending], self._logs(3)
        )

        self.assertEqual(send_message.call_count, 3)
        cancel_logs.assert_not_called()
        update_status.assert_called_with(12, 42, "completed")

    def test_a_failed_cancel_read_does_not_abandon_the_send(self):
        """A transient database blip must not strand a half-delivered blast."""
        sending = {"id": 12, "company_id": 42, "status": "sending"}

        send_message, cancel_logs, _update_log, update_status = self._dispatch(
            [sending, RuntimeError("connection reset"), sending], self._logs(3)
        )

        self.assertEqual(send_message.call_count, 3)
        cancel_logs.assert_not_called()
        update_status.assert_called_with(12, 42, "completed")
