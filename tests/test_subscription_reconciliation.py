import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret")
import sys
sys.path.insert(0, "C:\\Users\\User\\PycharmProjects\\python-whatsapp-bot-main")
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

    def test_order_not_found(self):
        d = MagicMock(data=[])
        self.ms.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = d
        r = self.svc.reconcile_subscription_order('nonexistent')
        self.assertEqual(r['outcome'], 'manual_review_required')

    def test_unpaid_not_reconcilable(self):
        self._mock_order({'order_reference':'r1','status':'pending','activation_status':'not_started','reconciliation_required':False})
        r = self.svc.reconcile_subscription_order('r1')
        self.assertEqual(r['outcome'], 'unpaid_order_not_reconcilable')

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

    def test_legacy_paid_recoverable(self):
        self._mock_order({'order_reference':'r1','status':'paid','activation_status':'not_started','new_plan_id':1,'subscription_id':10,'company_id':42,'activation_sequence_key':None,'order_schema_version':None,'source_plan_id':None,'source_status':None})
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

if __name__ == '__main__':
    unittest.main()
