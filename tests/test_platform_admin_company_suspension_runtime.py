import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from flask import Flask, g

from app import create_app
from app.database import platform_admin_repository, platform_company_repository
from app.routes import billing_routes, broadcast_routes, profile_routes, user_routes, widget_routes
from app.services import platform_admin_service
from app.services.company_status_service import (
    CompanyOperationalStatusError,
    ensure_company_operational,
)
from app.utils import telegram_utils, whatsapp_utils
from app.services import ai_router, wasender_service


AUTH_USER = {
    "id": 1,
    "company_id": 42,
    "email": "admin@example.test",
    "full_name": "Admin",
    "role": "admin",
    "status": "active",
}


class PlatformCompanyLifecycleRepositoryTests(unittest.TestCase):
    def _rpc_result(self, *, action="platform_admin.company.suspend", old_status="active", new_status="inactive"):
        return {
            "company": {
                "id": 42,
                "old_status": old_status,
                "new_status": new_status,
                "updated_at": "2026-08-08T00:00:00+00:00",
            },
            "audit_event": {
                "id": 77,
                "action": action,
                "resource_type": "company",
                "resource_id": "42",
            },
        }

    def test_suspend_rpc_uses_expected_function_and_validates_result(self):
        rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=self._rpc_result())
        )))
        with patch.object(platform_company_repository.supabase, "rpc", rpc):
            result = platform_company_repository.suspend_platform_company_for_platform_admin(3, 42)
        rpc.assert_called_once_with(
            "suspend_platform_company",
            {"p_actor_platform_admin_user_id": 3, "p_company_id": 42},
        )
        self.assertEqual(result["company"]["new_status"], "inactive")

    def test_restore_rpc_uses_expected_function_and_validates_result(self):
        rpc = MagicMock(return_value=MagicMock(execute=MagicMock(
            return_value=SimpleNamespace(data=self._rpc_result(
                action="platform_admin.company.restore",
                old_status="inactive",
                new_status="active",
            ))
        )))
        with patch.object(platform_company_repository.supabase, "rpc", rpc):
            result = platform_company_repository.restore_platform_company_for_platform_admin(3, 42)
        rpc.assert_called_once_with(
            "restore_platform_company",
            {"p_actor_platform_admin_user_id": 3, "p_company_id": 42},
        )
        self.assertEqual(result["company"]["new_status"], "active")

    def test_rpc_result_validation_fails_closed_for_malformed_data(self):
        cases = [
            ("company", None),
            ("audit_event", None),
            ("company.id", 43),
            ("company.old_status", "inactive"),
            ("company.new_status", "active"),
            ("company.updated_at", None),
            ("audit_event.id", True),
            ("audit_event.id", 0),
            ("audit_event.action", "platform_admin.company.restore"),
            ("audit_event.resource_type", "companies"),
            ("audit_event.resource_id", "43"),
        ]
        for dotted, value in cases:
            result = self._rpc_result()
            parts = dotted.split(".")
            if len(parts) == 1:
                result[parts[0]] = value
            else:
                result[parts[0]][parts[1]] = value
            rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=SimpleNamespace(data=result))))
            with self.subTest(dotted=dotted), patch.object(platform_company_repository.supabase, "rpc", rpc):
                with self.assertRaises(RuntimeError):
                    platform_company_repository.suspend_platform_company_for_platform_admin(3, 42)


class PlatformCompanyLifecycleServiceTests(unittest.TestCase):
    def test_lifecycle_services_reject_browser_supplied_fields(self):
        with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
            platform_admin_service.suspend_company(42, {"status": "inactive"}, 3)
        self.assertEqual(raised.exception.code, "invalid_request")

    def test_suspend_maps_known_rpc_errors_to_stable_codes(self):
        cases = [
            (RuntimeError("Company not found"), 404, "company_not_found"),
            (RuntimeError("Company status is unchanged"), 400, "no_change"),
            (RuntimeError("Protected platform-admin company cannot be suspended"), 400, "protected_company"),
            (RuntimeError("Active platform-admin mapping is required"), 403, "platform_admin_access_denied"),
        ]
        for exc, status, code in cases:
            with self.subTest(code=code), patch.object(
                platform_company_repository,
                "suspend_platform_company_for_platform_admin",
                side_effect=exc,
            ):
                with self.assertRaises(platform_admin_service.PlatformAdminServiceError) as raised:
                    platform_admin_service.suspend_company(42, {}, 3)
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.code, code)

    def test_success_returns_refreshed_authoritative_state(self):
        with patch.object(
            platform_company_repository,
            "restore_platform_company_for_platform_admin",
            return_value={
                "company": {"id": 42, "old_status": "inactive", "new_status": "active", "updated_at": "now"},
                "audit_event": {"id": 9},
            },
        ) as repo:
            result = platform_admin_service.restore_company(42, {}, 3)
        self.assertEqual(result["company"]["new_status"], "active")
        repo.assert_called_once_with(3, 42)


class CompanyOperationalStatusGuardTests(unittest.TestCase):
    def test_active_company_allowed(self):
        with patch("app.services.company_status_service.get_company_status_by_id", return_value={"id": 4, "status": "active"}):
            self.assertEqual(ensure_company_operational(4)["status"], "active")

    def test_inactive_missing_null_and_unknown_company_fail_closed(self):
        cases = [
            ({"id": 4, "status": "inactive"}, "company_suspended", 403),
            ({"id": 4, "status": None}, "company_suspended", 403),
            ({"id": 4, "status": "paused"}, "company_suspended", 403),
            (None, "company_not_found", 403),
        ]
        for row, code, status in cases:
            with self.subTest(code=code), patch(
                "app.services.company_status_service.get_company_status_by_id",
                return_value=row,
            ):
                with self.assertRaises(CompanyOperationalStatusError) as raised:
                    ensure_company_operational(4)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.status_code, status)

    def test_browser_jwt_status_cannot_override_database_status(self):
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.company_id = 4
            g.jwt_claims = {"company_status": "active"}
            with patch(
                "app.services.company_status_service.get_company_status_by_id",
                return_value={"id": 4, "status": "inactive"},
            ):
                with self.assertRaises(CompanyOperationalStatusError) as raised:
                    ensure_company_operational(g.company_id)
        self.assertEqual(raised.exception.code, "company_suspended")


class TenantOperationalRouteGuardTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def _auth(self):
        return (
            patch(
                "app.decorators.auth_decorator.jwt.decode",
                return_value={"user_id": 1, "company_id": 42, "role": "admin"},
            ),
            patch("app.database.user_repository.get_user_by_id", return_value=AUTH_USER),
            patch(
                "app.services.company_status_service.get_company_status_by_id",
                return_value={"id": 42, "status": "inactive"},
            ),
        )

    def test_profile_create_and_delete_are_blocked_before_repository_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.profile_routes.save_profile") as save_profile, \
             patch("app.routes.profile_routes.delete_profile") as delete_profile:
            create_response = self.client.post(
                "/api/profiles?chatbot_id=9",
                headers=self.headers,
                json={"name": "sales"},
            )
            delete_response = self.client.delete(
                "/api/profiles/sales?chatbot_id=9",
                headers=self.headers,
            )
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(create_response.get_json()["code"], "company_suspended")
        self.assertEqual(delete_response.status_code, 403)
        self.assertEqual(delete_response.get_json()["code"], "company_suspended")
        save_profile.assert_not_called()
        delete_profile.assert_not_called()

    def test_team_role_and_status_are_blocked_before_billing_or_repository_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.user_routes.get_user_by_id_for_company") as get_target, \
             patch("app.routes.user_routes.count_active_admins_by_company") as count_admins, \
             patch("app.routes.user_routes.can_add_team_member") as billing_check, \
             patch("app.routes.user_routes.update_user_for_company") as update_user:
            role_response = self.client.put(
                "/api/users/7/role",
                headers=self.headers,
                json={"role": "admin"},
            )
            status_response = self.client.put(
                "/api/users/7/status",
                headers=self.headers,
                json={"status": "active"},
            )
        self.assertEqual(role_response.status_code, 403)
        self.assertEqual(role_response.get_json()["code"], "company_suspended")
        self.assertEqual(status_response.status_code, 403)
        self.assertEqual(status_response.get_json()["code"], "company_suspended")
        get_target.assert_not_called()
        count_admins.assert_not_called()
        billing_check.assert_not_called()
        update_user.assert_not_called()

    def test_widget_dashboard_routes_are_blocked_before_implicit_or_explicit_writes(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.widget_routes.ensure_widget") as ensure_widget, \
             patch("app.routes.widget_routes.update_widget_settings") as update_widget, \
             patch("app.routes.widget_routes.regenerate_public_key") as regenerate_key:
            get_response = self.client.get(
                "/api/bots/9/widget",
                headers=self.headers,
            )
            put_response = self.client.put(
                "/api/bots/9/widget",
                headers=self.headers,
                json={"is_enabled": True},
            )
            post_response = self.client.post(
                "/api/bots/9/widget/regenerate-key",
                headers=self.headers,
            )
        self.assertEqual(get_response.status_code, 403)
        self.assertEqual(put_response.status_code, 403)
        self.assertEqual(post_response.status_code, 403)
        ensure_widget.assert_not_called()
        update_widget.assert_not_called()
        regenerate_key.assert_not_called()

    def test_broadcast_create_and_start_are_blocked_before_dispatch_mutation(self):
        auth, user, status = self._auth()
        with auth, user, status, \
             patch("app.routes.broadcast_routes.create_campaign") as create_campaign, \
             patch("app.routes.broadcast_routes.create_broadcast_log") as create_log, \
             patch("app.routes.broadcast_routes.update_campaign_status") as update_status, \
             patch("app.routes.broadcast_routes.threading.Thread") as worker:
            create_response = self.client.post(
                "/api/broadcast/campaign?chatbot_id=9",
                headers=self.headers,
                json={
                    "name": "Campaign",
                    "message_template": "Hello",
                    "recipients": [{"phone": "+60123456789"}],
                },
            )
            start_response = self.client.post(
                "/api/broadcast/campaign/12/start?chatbot_id=9",
                headers=self.headers,
            )
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(create_response.get_json()["code"], "company_suspended")
        self.assertEqual(start_response.status_code, 403)
        self.assertEqual(start_response.get_json()["code"], "company_suspended")
        create_campaign.assert_not_called()
        create_log.assert_not_called()
        update_status.assert_not_called()
        worker.assert_not_called()

    def test_broadcast_worker_fails_closed_if_company_suspends_after_scheduling(self):
        auth, user, status = self._auth()
        campaign = {
            "id": 12,
            "company_id": 42,
            "chatbot_id": 9,
            "channel_type": "whatsapp",
            "message_template": "Hello",
        }
        pending_logs = [{"id": 100, "recipient_phone": "+60123456789", "status": "pending"}]
        with auth, user, status, \
             patch("app.routes.broadcast_routes.update_broadcast_log_status") as update_log, \
             patch("app.routes.broadcast_routes.update_campaign_status") as update_status:
            broadcast_routes.process_broadcast_dispatch(create_app(), campaign, pending_logs)
        update_log.assert_called_once_with(
            100,
            "failed",
            error_message="Company is suspended.",
        )
        update_status.assert_called_once_with(12, 42, "failed")
        self.assertNotIn(
            call(100, "sending"),
            update_log.call_args_list,
        )

    def test_broadcast_worker_stops_before_current_and_remaining_recipient_when_suspended_mid_dispatch(self):
        campaign = {
            "id": 12,
            "company_id": 42,
            "chatbot_id": 9,
            "channel_type": "whatsapp",
            "message_template": "Hello {{phone}}",
        }
        pending_logs = [
            {"id": 100, "recipient_phone": "+60111111111", "status": "pending"},
            {"id": 101, "recipient_phone": "+60222222222", "status": "pending"},
            {"id": 102, "recipient_phone": "+60333333333", "status": "pending"},
        ]
        status_rows = [
            {"id": 42, "status": "active"},
            {"id": 42, "status": "active"},
            {"id": 42, "status": "inactive"},
        ]
        with patch(
            "app.services.company_status_service.get_company_status_by_id",
            side_effect=status_rows,
        ), patch(
            "app.database.whatsapp_channel_repository.get_whatsapp_channels_by_chatbot",
            return_value=[{"id": 1, "is_active": True, "access_token": "token"}],
        ), patch(
            "app.utils.whatsapp_utils.send_message",
            return_value=SimpleNamespace(status_code=200, text="ok"),
        ) as send_message, patch(
            "app.routes.broadcast_routes.update_broadcast_log_status"
        ) as update_log, patch(
            "app.routes.broadcast_routes.update_campaign_status"
        ) as update_status:
            broadcast_routes.process_broadcast_dispatch(create_app(), campaign, pending_logs)

        send_message.assert_called_once()
        self.assertIn(call(100, "sending"), update_log.call_args_list)
        self.assertTrue(any(args[0] == 100 and args[1] == "sent" for args, _kwargs in update_log.call_args_list))
        self.assertIn(
            call(101, "failed", error_message="Company is suspended."),
            update_log.call_args_list,
        )
        self.assertIn(
            call(102, "failed", error_message="Company is suspended."),
            update_log.call_args_list,
        )
        self.assertNotIn(call(101, "sending"), update_log.call_args_list)
        self.assertNotIn(call(102, "sending"), update_log.call_args_list)
        update_status.assert_called_with(12, 42, "failed")


class SystemAiCompanyStatusTests(unittest.TestCase):
    def _active_bot(self, company_id=42):
        return {
            "id": 9,
            "company_id": company_id,
            "ai_provider": "deepseek",
            "model_name": "deepseek-chat",
        }

    def test_generate_system_response_checks_company_before_provider_credit_or_usage(self):
        cases = [
            {"id": 42, "status": "inactive"},
            {"id": 42, "status": None},
            {"id": 42, "status": "paused"},
            None,
        ]
        for company_row in cases:
            with self.subTest(company_row=company_row), \
                 patch.object(
                     ai_router,
                     "get_bot_by_id",
                     return_value=self._active_bot(),
                 ), \
                 patch(
                     "app.services.company_status_service.get_company_status_by_id",
                     return_value=company_row,
                 ), \
                 patch.object(ai_router, "_get_system_provider_for_enforcement") as provider_gate, \
                 patch.object(ai_router, "_check_ai_credit_before_provider") as credit_check, \
                 patch.object(ai_router, "_call_deepseek_direct") as deepseek_call, \
                 patch.object(ai_router, "_make_usage_log") as usage_log:
                with self.assertRaises((CompanyOperationalStatusError, RuntimeError)):
                    ai_router.generate_system_response("Summarize", 9)
                provider_gate.assert_not_called()
                credit_check.assert_not_called()
                deepseek_call.assert_not_called()
                usage_log.assert_not_called()

    def test_generate_system_response_does_not_fallback_through_request_context_without_bot_company(self):
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.company_id = 42
            with patch.object(ai_router, "get_bot_by_id", return_value=None), \
                 patch.object(ai_router, "_call_deepseek_direct") as deepseek_call:
                with self.assertRaises(RuntimeError):
                    ai_router.generate_system_response("Summarize", 9)
        deepseek_call.assert_not_called()

    def test_generate_system_response_passes_bot_company_id_to_provider_enforcement(self):
        with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(42)), \
             patch(
                 "app.services.company_status_service.get_company_status_by_id",
                 return_value={"id": 42, "status": "active"},
             ), \
             patch.object(
                 ai_router,
                 "_get_system_provider_for_enforcement",
                 return_value=("deepseek", "deepseek-chat"),
             ) as provider_gate, \
             patch.object(
                 ai_router,
                 "_call_deepseek_direct",
                 return_value=ai_router._make_result_from_text("Done", "deepseek", "deepseek-chat"),
             ), \
             patch.object(ai_router, "_check_ai_credit_before_provider"), \
            patch.object(ai_router, "_make_usage_log"):
            self.assertEqual(ai_router.generate_system_response("Summarize", 9), "Done")
        provider_gate.assert_called_once()
        self.assertEqual(provider_gate.call_args.args[2], 42)

    def test_system_provider_enforcement_uses_authoritative_company_without_request_context(self):
        policy = SimpleNamespace(allowed=True, api_route=ai_router.ROUTE_DIRECT_DEEPSEEK, denial_reason=None)
        with patch("app.services.ai_access_policy.resolve_ai_access", return_value=policy) as resolve, \
             patch.object(ai_router, "_validate_deepseek_pricing_config"):
            provider, model = ai_router._get_system_provider_for_enforcement(
                ai_router.TRIAL_PROVIDER,
                "ignored-model",
                42,
            )
        resolve.assert_called_once_with(42)
        self.assertEqual(provider, ai_router.TRIAL_PROVIDER)
        self.assertEqual(model, ai_router.TRIAL_MODEL)

    def test_denied_system_ai_policy_prevents_provider_call(self):
        policy = SimpleNamespace(
            allowed=False,
            api_route=ai_router.ROUTE_DIRECT_DEEPSEEK,
            denial_reason="AI is not available.",
        )
        with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(42)), \
             patch(
                 "app.services.company_status_service.get_company_status_by_id",
                 return_value={"id": 42, "status": "active"},
             ), \
             patch("app.services.ai_access_policy.resolve_ai_access", return_value=policy), \
             patch.object(ai_router, "_call_deepseek_direct") as deepseek_call, \
             patch.object(ai_router, "_check_ai_credit_before_provider") as credit_check, \
             patch.object(ai_router, "_make_usage_log") as usage_log:
            with self.assertRaises(ai_router.BillingLimitError):
                ai_router.generate_system_response("Summarize", 9)
        deepseek_call.assert_not_called()
        credit_check.assert_not_called()
        usage_log.assert_not_called()

    def test_missing_system_ai_company_id_fails_before_provider_credit_or_usage(self):
        with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(None)), \
             patch.object(ai_router, "_get_system_provider_for_enforcement") as provider_gate, \
             patch.object(ai_router, "_call_deepseek_direct") as deepseek_call, \
             patch.object(ai_router, "_check_ai_credit_before_provider") as credit_check, \
             patch.object(ai_router, "_make_usage_log") as usage_log:
            with self.assertRaises(CompanyOperationalStatusError):
                ai_router.generate_system_response("Summarize", 9)
        provider_gate.assert_not_called()
        deepseek_call.assert_not_called()
        credit_check.assert_not_called()
        usage_log.assert_not_called()

    def test_request_context_company_cannot_override_bot_company_for_system_ai(self):
        app = Flask(__name__)
        policy = SimpleNamespace(allowed=True, api_route=ai_router.ROUTE_DIRECT_DEEPSEEK, denial_reason=None)
        with app.test_request_context("/"):
            g.company_id = 99
            with patch.object(ai_router, "get_bot_by_id", return_value=self._active_bot(42)), \
                 patch(
                     "app.services.company_status_service.get_company_status_by_id",
                     return_value={"id": 42, "status": "active"},
                 ) as status_lookup, \
                 patch("app.services.ai_access_policy.resolve_ai_access", return_value=policy) as resolve, \
                 patch.object(ai_router, "_validate_deepseek_pricing_config"), \
                 patch.object(
                     ai_router,
                     "_call_deepseek_direct",
                     return_value=ai_router._make_result_from_text("Done", "deepseek", "deepseek-chat"),
                 ), \
                 patch.object(ai_router, "_check_ai_credit_before_provider"), \
                 patch.object(ai_router, "_make_usage_log"):
                self.assertEqual(ai_router.generate_system_response("Summarize", 9), "Done")
        status_lookup.assert_called_once_with(42)
        resolve.assert_called_once_with(42)


class CompanyOperationalStatusEnforcementSourceTests(unittest.TestCase):
    def test_high_impact_entry_points_use_company_operational_guard(self):
        guarded_sources = [
            inspect.getsource(ai_router.generate_response),
            inspect.getsource(ai_router.generate_system_response),
            inspect.getsource(widget_routes._load_widget_or_error),
            inspect.getsource(telegram_utils.process_telegram_update),
            inspect.getsource(wasender_service.process_wasender_webhook),
            inspect.getsource(whatsapp_utils.process_whatsapp_message),
        ]
        for source in guarded_sources:
            with self.subTest(source=source[:80]):
                self.assertIn("ensure_company_operational", source)

    def test_billing_mutation_routes_require_company_operational_guard(self):
        guarded_routes = [
            billing_routes.toyyibpay_checkout,
            billing_routes.subscription_checkout,
            billing_routes.retry_subscription_order,
            billing_routes.cancel_subscription,
            billing_routes.undo_cancel_subscription,
            billing_routes.schedule_downgrade,
            billing_routes.clear_downgrade,
        ]
        for route in guarded_routes:
            with self.subTest(route=route.__name__):
                source = inspect.getsource(route)
                self.assertIn("company_operational_required", source)

    def test_phase5_operational_mutation_inventory_is_guarded(self):
        guarded_routes = [
            profile_routes.update_workspace,
            user_routes.update_current_user,
            user_routes.change_password,
            profile_routes.create_profile,
            profile_routes.remove_profile,
            user_routes.update_member_role,
            user_routes.update_member_status,
            widget_routes.get_bot_widget,
            widget_routes.put_bot_widget,
            widget_routes.post_regenerate_widget_key,
            broadcast_routes.save_campaign,
            broadcast_routes.start_campaign,
            billing_routes.toyyibpay_checkout,
            billing_routes.subscription_checkout,
            billing_routes.retry_subscription_order,
            billing_routes.cancel_subscription,
            billing_routes.undo_cancel_subscription,
            billing_routes.schedule_downgrade,
            billing_routes.clear_downgrade,
        ]
        for route in guarded_routes:
            with self.subTest(route=route.__name__):
                self.assertIn(
                    "company_operational_required",
                    inspect.getsource(route),
                )

    def test_outbound_messaging_boundary_is_authoritatively_guarded_at_application_entry_points(self):
        guarded_sources = {
            "broadcast_worker": inspect.getsource(broadcast_routes.process_broadcast_dispatch),
            "telegram_inbound": inspect.getsource(telegram_utils.process_telegram_update),
            "wasender_inbound": inspect.getsource(wasender_service.process_wasender_webhook),
            "whatsapp_inbound": inspect.getsource(whatsapp_utils.process_whatsapp_message),
            "widget_public": inspect.getsource(widget_routes._load_widget_or_error),
        }
        for name, source in guarded_sources.items():
            with self.subTest(name=name):
                self.assertIn("ensure_company_operational", source)
        self.assertIn("send_wasender_text_message", inspect.getsource(broadcast_routes.process_broadcast_dispatch))
        self.assertIn("send_telegram_message", inspect.getsource(telegram_utils.process_telegram_update))
        self.assertIn("send_message", inspect.getsource(whatsapp_utils.process_whatsapp_message))

    def test_suspended_company_tests_explicitly_override_autouse_active_baseline(self):
        source = inspect.getsource(TenantOperationalRouteGuardTests._auth)
        self.assertIn('"status": "inactive"', source)
        self.assertIn("get_company_status_by_id", source)


class PlatformCompanyLifecycleAuditSchemaTests(unittest.TestCase):
    def test_suspend_and_restore_audit_metadata_is_allowlisted(self):
        for action, old_status, new_status, endpoint in [
            (
                "platform_admin.company.suspend",
                "active",
                "inactive",
                "/api/platform-admin/companies/<company_id>/suspend",
            ),
            (
                "platform_admin.company.restore",
                "inactive",
                "active",
                "/api/platform-admin/companies/<company_id>/restore",
            ),
        ]:
            with self.subTest(action=action):
                platform_admin_repository.validate_audit_event(
                    3,
                    action,
                    "company",
                    "42",
                    {
                        "outcome": "success",
                        "endpoint": endpoint,
                        "http_method": "POST",
                        "company_id": 42,
                        "old_status": old_status,
                        "new_status": new_status,
                    },
                )

    def test_audit_metadata_rejects_wrong_status_and_secrets(self):
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                3,
                "platform_admin.company.suspend",
                "company",
                "42",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/suspend",
                    "http_method": "POST",
                    "company_id": 42,
                    "old_status": "inactive",
                    "new_status": "inactive",
                },
            )
        with self.assertRaises(ValueError):
            platform_admin_repository.validate_audit_event(
                3,
                "platform_admin.company.restore",
                "company",
                "42",
                {
                    "outcome": "success",
                    "endpoint": "/api/platform-admin/companies/<company_id>/restore",
                    "http_method": "POST",
                    "company_id": 42,
                    "old_status": "inactive",
                    "new_status": "active",
                    "secret_reason": "nope",
                },
            )
