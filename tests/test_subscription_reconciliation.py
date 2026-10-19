import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret")
import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
import unittest
from unittest.mock import ANY, patch, MagicMock
import types
_m = types.ModuleType("google")
_m.genai = types.ModuleType("google.genai")
_m.genai.Client = MagicMock()
sys.modules["google"] = _m
sys.modules["google.genai"] = _m.genai
for m in ["fitz", "tools", "_tools"]:
    if m not in sys.modules: sys.modules[m] = types.ModuleType(m)

from app.database.company_subscription_order_repository import (
    update_subscription_order_activation_state,
    validate_activation_transition,
    VALID_ACTIVATION_TRANSITIONS,
)


class TestActivationTransitionValidation(unittest.TestCase):
    def test_valid_transitions(self):
        validate_activation_transition(None, 'not_started', 'r1')
        validate_activation_transition('not_started', 'claimed', 'r1')
        validate_activation_transition('claimed', 'activated', 'r1')
        validate_activation_transition('activated', 'credit_pending', 'r1')
        validate_activation_transition('credit_pending', 'completed', 'r1')

    def test_invalid_transitions(self):
        with self.assertRaises(ValueError):
            validate_activation_transition('completed', 'claimed', 'r1')
        with self.assertRaises(ValueError):
            validate_activation_transition('not_started', 'completed', 'r1')

    def test_terminal_states_have_no_transitions(self):
        for s in ['completed', 'conflict', 'failed']:
            self.assertEqual(len(VALID_ACTIVATION_TRANSITIONS.get(s, set())), 0)

class TestUpdateActivationState(unittest.TestCase):
    def test_sets_state(self):
        with patch('app.database.company_subscription_order_repository.supabase') as ms:
            d = MagicMock(data=[{'id':1,'activation_status':'claimed'}])
            ms.table.return_value.update.return_value.eq.return_value.execute.return_value = d
            r = update_subscription_order_activation_state('ref-1', activation_status='claimed')
            self.assertEqual(r['activation_status'], 'claimed')
    def test_raises_on_empty_ref(self):
        with self.assertRaises(ValueError):
            update_subscription_order_activation_state('')
    def test_raises_on_no_fields(self):
        with patch('app.database.company_subscription_order_repository.supabase'):
            with self.assertRaises(ValueError):
                update_subscription_order_activation_state('ref-1')

class TestReconciliationService(unittest.TestCase):
    def setUp(self):
        self.ms = MagicMock()
        self.p1 = patch('app.database.company_subscription_order_repository.supabase', self.ms)
        self.p1.start()
        self.p2 = patch('app.services.subscription_reconciliation_service.conditional_activate_subscription')
        self.mc = self.p2.start()
        self.p3 = patch('app.services.subscription_reconciliation_service._ensure_company_ai_credit')
        self.mt = self.p3.start()
        self.p4 = patch('app.services.subscription_reconciliation_service.update_company_subscription')
        self.mu = self.p4.start()
        self.p5 = patch('app.services.subscription_reconciliation_service._increment_attempt')
        self.p5.start()
        import app.services.subscription_reconciliation_service as s
        self.svc = s

    def tearDown(self):
        self.p1.stop(); self.p2.stop(); self.p3.stop(); self.p4.stop(); self.p5.stop()

    def _mock_order(self, attrs):
        d = MagicMock(data=[attrs])
        self.ms.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = d

    def test_already_completed(self):
        self._mock_order({'order_reference':'r1','status':'credited','activation_status':'completed'})
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'already_completed')

    def test_credited_orders_cannot_restart_activation(self):
        for schema_version in (None, 2, 99):
            for activation_status in (None, '', '  ', 'completed', 'not_started', 'claimed', 'failed', 'conflict', 'unknown'):
                with self.subTest(schema_version=schema_version, activation_status=activation_status):
                    self._mock_order({
                        'order_reference': 'credited-history', 'payment_gateway': 'toyyibpay',
                        'status': 'credited', 'activation_status': activation_status,
                        'order_schema_version': schema_version, 'company_id': 42,
                        'subscription_id': 10, 'new_plan_id': 1,
                        'activation_sequence_key': None, 'source_plan_id': None,
                        'source_status': None, 'reconciliation_required': False,
                    })
                    with patch.object(self.svc, '_retry_activation') as activate, patch.object(
                        self.svc, '_retry_credit'
                    ) as credit, patch.object(self.svc, '_increment_attempt') as increment, patch.object(
                        self.svc, '_update_state'
                    ) as update_state, patch.object(self.svc, 'get_plan_by_id') as plan:
                        result = self.svc.reconcile_subscription_order(
                            'credited-history', company_id=42, force=True,
                        )
                    expected = 'already_completed' if (activation_status or '').strip() in ('', 'completed') else 'manual_review_required'
                    self.assertEqual(result['outcome'], expected)
                    self.assertEqual(result['order_status'], 'credited')
                    activate.assert_not_called()
                    credit.assert_not_called()
                    increment.assert_not_called()
                    update_state.assert_not_called()
                    plan.assert_not_called()
                    self.mc.assert_not_called()
                    self.mu.assert_not_called()
                    self.mt.assert_not_called()

    def test_paid_orders_keep_activation_retry(self):
        for activation_status in (None, '', 'claimed', 'failed'):
            with self.subTest(activation_status=activation_status):
                order = {
                    'order_reference': 'paid-recovery', 'status': 'paid',
                    'activation_status': activation_status, 'company_id': 42,
                }
                self._mock_order(order)
                expected = {'outcome': 'reconciled_and_completed'}
                with patch.object(self.svc, '_retry_activation', return_value=expected) as activate, patch.object(
                    self.svc, '_retry_credit'
                ) as credit:
                    result = self.svc.reconcile_subscription_order('paid-recovery', company_id=42)
                self.assertEqual(result, expected)
                activate.assert_called_once_with(order, ANY)
                credit.assert_not_called()

    def test_credited_explicit_credit_recovery_never_reactivates(self):
        for activation_status in ('activated', 'credit_pending'):
            with self.subTest(activation_status=activation_status):
                order = {
                    'order_reference': 'credited-recovery', 'status': 'credited',
                    'activation_status': activation_status, 'company_id': 42,
                }
                self._mock_order(order)
                expected = {'outcome': 'credit_retry_completed'}
                with patch.object(self.svc, '_retry_credit', return_value=expected) as credit, patch.object(
                    self.svc, '_retry_activation'
                ) as activate:
                    result = self.svc.reconcile_subscription_order('credited-recovery', company_id=42)
                self.assertEqual(result, expected)
                credit.assert_called_once_with(order, ANY)
                activate.assert_not_called()
                self.mc.assert_not_called()
                self.mu.assert_not_called()

    def test_order_not_found(self):
        d = MagicMock(data=[])
        self.ms.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = d
        r = self.svc.reconcile_subscription_order('nonexistent')
        self.assertEqual(r['outcome'], 'manual_review_required')

    def test_unpaid_not_reconcilable(self):
        self._mock_order({'order_reference':'r1','status':'pending','activation_status':'not_started','reconciliation_required':False})
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'unpaid_order_not_reconcilable')

    def test_legacy_unpaid_activation_flags_cannot_grant_credit(self):
        for gateway in ('toyyibpay', 'hitpay', None):
            for status in ('pending', 'failed', 'expired', 'cancelled', 'unknown', None):
                for activation_status in ('activated', 'credit_pending'):
                    with self.subTest(gateway=gateway, status=status, activation_status=activation_status):
                        self.mt.reset_mock()
                        self._mock_order({
                            'order_reference': 'legacy-unpaid', 'payment_gateway': gateway,
                            'status': status, 'activation_status': activation_status,
                            'company_id': 42, 'new_plan_id': 7, 'subscription_id': 9,
                            'activation_sequence_key': 'company:42:initial',
                            'reconciliation_required': True,
                        })
                        with patch.object(self.svc, 'get_plan_by_id', return_value={
                            'id': 7, 'code': 'advanced', 'included_ai_credit_micro_myr': 20000000,
                        }) as plan, patch.object(self.svc, '_update_state') as update_state, patch.object(
                            self.svc, '_increment_attempt'
                        ) as increment, patch(
                            'app.database.company_subscription_order_repository.update_subscription_order_status'
                        ) as mark_credited, patch(
                            'app.services.billing_notification_service.notify_reconciliation_completed'
                        ) as notify:
                            result = self.svc.reconcile_subscription_order(
                                'legacy-unpaid', company_id=42, force=True,
                            )
                        self.assertEqual(result['outcome'], 'unpaid_order_not_reconcilable')
                        self.assertEqual(result['order_status'], status or '')
                        self.mt.assert_not_called()
                        self.mc.assert_not_called()
                        self.mu.assert_not_called()
                        plan.assert_not_called()
                        update_state.assert_not_called()
                        increment.assert_not_called()
                        mark_credited.assert_not_called()
                        notify.assert_not_called()

    def test_legacy_unpaid_claimed_state_cannot_retry_activation(self):
        self._mock_order({
            'order_reference': 'legacy-unpaid', 'payment_gateway': 'hitpay',
            'status': 'pending', 'activation_status': 'claimed',
            'company_id': 42, 'new_plan_id': 7, 'reconciliation_required': True,
        })
        with patch.object(self.svc, '_retry_activation') as activate, patch.object(
            self.svc, '_retry_credit'
        ) as credit, patch.object(self.svc, '_increment_attempt') as increment:
            result = self.svc.reconcile_subscription_order('legacy-unpaid', company_id=42)
        self.assertEqual(result['outcome'], 'unpaid_order_not_reconcilable')
        activate.assert_not_called()
        credit.assert_not_called()
        increment.assert_not_called()

    def test_pending_chip_order_uses_authoritative_reconciliation(self):
        order = {
            'order_reference': 'chip-r1',
            'status': 'pending',
            'payment_gateway': 'chip',
            'gateway_order_id': 'hp-1',
        }
        self._mock_order(order)
        expected = {
            'outcome': 'reconciled_and_completed',
            'order_status': 'credited',
            'message': 'done',
        }
        with patch.object(
            self.svc, '_reconcile_pending_chip_order', return_value=expected
        ) as reconcile_chip:
            result = self.svc.reconcile_subscription_order('chip-r1')

        self.assertEqual(result, expected)
        reconcile_chip.assert_called_once_with(order)

    def test_chip_provider_failure_preserves_pending_order_for_retry(self):
        self._mock_order({
            'order_reference': 'chip-r2',
            'status': 'pending',
            'payment_gateway': 'chip',
            'gateway_order_id': 'hp-2',
        })
        with patch.object(
            self.svc, '_reconcile_pending_chip_order', side_effect=RuntimeError('offline')
        ), patch.object(self.svc, '_update_state') as update_state:
            result = self.svc.reconcile_subscription_order('chip-r2')

        self.assertEqual(result['outcome'], 'manual_review_required')
        update_state.assert_called_once_with(
            'chip-r2',
            activation_error_code='chip_reconciliation_failed',
            activation_error_message='CHIP reconciliation requires retry.',
            reconciliation_required=True,
        )

    def test_failed_payment_rejected(self):
        self._mock_order({'order_reference':'r1','status':'failed','activation_status':None,'reconciliation_required':False})
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'unpaid_order_not_reconcilable')

    def test_expired_unpaid_rejected(self):
        self._mock_order({'order_reference':'r1','status':'expired','activation_status':None,'reconciliation_required':False})
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'unpaid_order_not_reconcilable')

    def test_malformed_version2_rejected(self):
        self._mock_order({'order_reference':'r1','status':'paid','activation_status':'not_started','order_schema_version':2,'source_plan_id':None,'source_status':None})
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'malformed_order')

    def test_version3_without_prepaid_term_is_rejected(self):
        self._mock_order({
            'order_reference': 'r1',
            'payment_gateway': 'toyyibpay',
            'status': 'paid',
            'activation_status': 'not_started',
            'order_schema_version': 3,
            'source_plan_id': 1,
            'source_status': 'active',
            'billing_term_months': None,
        })
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'malformed_order')
        self.assertIn('prepaid billing term', r['message'])

    def test_unknown_paid_order_schema_is_rejected(self):
        self._mock_order({
            'order_reference': 'r1',
            'payment_gateway': 'toyyibpay',
            'status': 'paid',
            'activation_status': 'not_started',
            'order_schema_version': 99,
            'source_plan_id': 1,
            'source_status': 'active',
        })
        with patch.object(self.svc, '_retry_activation') as activate:
            r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'malformed_order')
        self.assertIn('not supported', r['message'])
        activate.assert_not_called()

    def test_legacy_paid_recoverable(self):
        self._mock_order({'order_reference':'r1','payment_gateway':'toyyibpay','status':'paid','activation_status':'not_started','new_plan_id':1,'subscription_id':10,'company_id':42,'activation_sequence_key':None,'order_schema_version':None,'source_plan_id':None,'source_status':None})
        self.mu.return_value = {'id':10}
        with patch('app.services.subscription_reconciliation_service.get_plan_by_id') as mp:
            mp.return_value = {'id':1,'code':'essential','billing_interval':'monthly','included_ai_credit_micro_myr':0,'name':'Essential'}
            with patch('app.services.subscription_reconciliation_service._ensure_company_ai_credit'):
                r = self.svc.reconcile_subscription_order('r1')
                self.assertIn(r['outcome'], ['credit_retry_completed', 'manual_review_required'])
                _, kwargs = self.mu.call_args
                from app.services.billing_period_service import calculate_current_period_end
                period_start = kwargs['updates']['current_period_start']
                expected_end = calculate_current_period_end(period_start, 'monthly').isoformat()
                self.assertEqual(kwargs['updates']['current_period_end'], expected_end)

    def test_atomic_paid_recovery_uses_monthly_period(self):
        self._mock_order({
            'order_reference': 'r2',
            'status': 'paid',
            'activation_status': 'not_started',
            'new_plan_id': 1,
            'subscription_id': 10,
            'company_id': 42,
            'activation_sequence_key': 'company:42:upgrade-from:1:period:2026-07-01',
            'order_schema_version': 2,
            'source_plan_id': 1,
            'source_status': 'active',
            'source_period_start': '2026-07-01T00:00:00+00:00',
            'source_period_end': '2026-08-01T00:00:00+00:00',
        })
        self.mc.return_value = {'id': 10}
        self.mt.return_value = {'status': 'applied'}
        with patch('app.services.subscription_reconciliation_service.get_plan_by_id') as mp:
            mp.return_value = {'id': 1, 'code': 'essential', 'billing_interval': 'monthly', 'included_ai_credit_micro_myr': 0, 'name': 'Essential'}
            r = self.svc.reconcile_subscription_order('r2')
        self.assertIn(r['outcome'], ['credit_retry_completed', 'manual_review_required'])
        _, kwargs = self.mc.call_args
        from app.services.billing_period_service import calculate_current_period_end
        period_start = kwargs['period_start_iso']
        expected_end = calculate_current_period_end(period_start, 'monthly').isoformat()
        self.assertEqual(kwargs['period_end_iso'], expected_end)

    def test_conflict_retry_rejected(self):
        self._mock_order({'order_reference':'r1','status':'paid','activation_status':'conflict'})
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'activation_already_claimed')

    def test_credit_pending_retries_credit_without_reactivation(self):
        self._mock_order({
            'order_reference': 'r16',
            'payment_gateway': 'hitpay',
            'status': 'credited',
            'activation_status': 'credit_pending',
            'new_plan_id': 7,
            'subscription_id': 9,
            'company_id': 34,
            'activation_sequence_key': 'company:34:initial-from:9:trial:2026-08-19T03:07:02.646645+00:00',
            'order_schema_version': 2,
            'source_plan_id': 1,
            'source_status': 'trial',
            'payment_reference': 'DEV_TEST_PAYMENT',
        })
        self.mt.return_value = {
            'status': 'ensured',
            'period_changed': True,
            'included_credit_granted_micro_myr': 20000000,
        }
        with patch('app.services.subscription_reconciliation_service.get_plan_by_id') as mp, \
             patch('app.services.subscription_reconciliation_service._update_state') as update_state, \
             patch('app.database.company_subscription_order_repository.update_subscription_order_status') as mark_credited:
            mp.return_value = {
                'id': 7,
                'code': 'advanced',
                'billing_interval': 'monthly',
                'included_ai_credit_micro_myr': 20000000,
                'name': 'Advanced',
            }
            mark_credited.return_value = {'id': 16, 'status': 'credited'}
            r = self.svc.reconcile_subscription_order('r16')

        self.assertEqual(r['outcome'], 'credit_retry_completed')
        self.mc.assert_not_called()
        self.mu.assert_not_called()
        self.mt.assert_called_once_with(34)
        update_state.assert_called_with(
            'r16',
            activation_status='completed',
            credit_granted_at=ANY,
            reconciliation_required=False,
        )
        mark_credited.assert_called_once()
        _, mark_kwargs = mark_credited.call_args
        self.assertEqual(mark_kwargs['order_reference'], 'r16')
        self.assertEqual(mark_kwargs['status'], 'credited')
        self.assertIsNotNone(mark_kwargs['credited_at'])

    def test_completed_reconciliation_is_idempotent_and_does_not_duplicate_credit(self):
        self._mock_order({
            'order_reference': 'r17',
            'status': 'credited',
            'activation_status': 'completed',
            'reconciliation_required': False,
            'new_plan_id': 7,
            'company_id': 34,
        })

        r = self.svc.reconcile_subscription_order('r17')

        self.assertEqual(r['outcome'], 'already_completed')
        self.mt.assert_not_called()
        self.mc.assert_not_called()


# Provider-specific authoritative recovery is covered by test_chip_reconciliation.py.

if __name__ == '__main__':
    unittest.main()
