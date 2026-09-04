"""Tests for pure helper functions in the smoke script."""

import os, sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
import unittest
from unittest.mock import patch, MagicMock

import types

# Mock broken dependencies before loading the smoke script module
if 'google' not in sys.modules:
    _g = types.ModuleType('google')
    _g.genai = types.ModuleType('google.genai')
    _g.genai.Client = MagicMock()
    sys.modules['google'] = _g
    sys.modules['google.genai'] = _g.genai
if 'fitz' not in sys.modules:
    sys.modules['fitz'] = types.ModuleType('fitz')
if 'tools' not in sys.modules:
    sys.modules['tools'] = types.ModuleType('tools')
if '_tools' not in sys.modules:
    sys.modules['_tools'] = types.ModuleType('_tools')
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")


class TestSmokeScriptHelpers(unittest.TestCase):
    """Tests for pure helper functions in the smoke script."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "smoke_test_ai_credit_topup_supabase",
            os.path.join(
                str(_REPO_ROOT),
                "scripts", "smoke_test_ai_credit_topup_supabase.py"
            ),
        )
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_confirmation_missing_exits(self):
        """Confirmation variable missing rejects execution."""
        env_backup = os.environ.copy()
        os.environ.pop("CONFIRM_LIVE_SUPABASE_SMOKE_TEST", None)
        with self.assertRaises(SystemExit):
            self.mod.main()
        os.environ.clear()
        os.environ.update(env_backup)

    def test_confirmation_wrong_value_exits(self):
        """Confirmation variable with wrong value rejects execution."""
        env_backup = os.environ.copy()
        os.environ["CONFIRM_LIVE_SUPABASE_SMOKE_TEST"] = "NO"
        with self.assertRaises(SystemExit):
            self.mod.main()
        os.environ.clear()
        os.environ.update(env_backup)

    def test_get_required_env_returns_value(self):
        """get_required_env returns the environment value."""
        env_backup = os.environ.copy()
        os.environ["TEST_VAR"] = "hello"
        result = self.mod.get_required_env("TEST_VAR")
        self.assertEqual(result, "hello")
        os.environ.clear()
        os.environ.update(env_backup)

    def test_get_required_env_missing_exits(self):
        """get_required_env exits when variable is missing."""
        with self.assertRaises(SystemExit):
            self.mod.get_required_env("NONEXISTENT_VAR_XYZ")

    def test_parse_positive_int_valid(self):
        """Positive integer string is parsed correctly."""
        result = self.mod.parse_positive_int("42", "test")
        self.assertEqual(result, 42)

    def test_parse_positive_int_zero_exits(self):
        """Zero exits."""
        with self.assertRaises(SystemExit):
            self.mod.parse_positive_int("0", "test")

    def test_parse_positive_int_negative_exits(self):
        """Negative exits."""
        with self.assertRaises(SystemExit):
            self.mod.parse_positive_int("-5", "test")

    def test_parse_positive_int_non_numeric_exits(self):
        """Non-numeric exits."""
        with self.assertRaises(SystemExit):
            self.mod.parse_positive_int("abc", "test")

    def test_parse_amount_default(self):
        """Empty input returns default amount."""
        result = self.mod.parse_amount_micro_myr("")
        self.assertEqual(result, 100_000)

    def test_parse_amount_none_default(self):
        """None input returns default amount."""
        result = self.mod.parse_amount_micro_myr(None)
        self.assertEqual(result, 100_000)

    def test_parse_amount_valid(self):
        """Valid amount parsed correctly."""
        result = self.mod.parse_amount_micro_myr("500000")
        self.assertEqual(result, 500_000)

    def test_parse_amount_non_divisible_exits(self):
        """Amount not divisible by 10000 exits."""
        with self.assertRaises(SystemExit):
            self.mod.parse_amount_micro_myr("12345")

    def test_cleanup_disabled_by_default(self):
        """Cleanup is disabled when env var not set."""
        env_backup = os.environ.copy()
        os.environ.pop("SMOKE_TEST_DELETE_ORDER", None)
        result = self.mod.is_cleanup_enabled()
        self.assertFalse(result)
        os.environ.clear()
        os.environ.update(env_backup)

    def test_cleanup_enabled_when_yes(self):
        """Cleanup is enabled when SMOKE_TEST_DELETE_ORDER=YES."""
        env_backup = os.environ.copy()
        os.environ["SMOKE_TEST_DELETE_ORDER"] = "YES"
        result = self.mod.is_cleanup_enabled()
        self.assertTrue(result)
        os.environ.clear()
        os.environ.update(env_backup)

    def test_cleanup_requires_exact_uuid_and_company_id(self):
        """_delete_order requires both order_reference and company_id."""
        mod = self.mod
        env_backup = os.environ.copy()
        os.environ["SUPABASE_URL"] = "https://test.supabase.co"
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-key"
        try:
            with patch.object(mod, '_get_supabase') as mock_get:
                mod._delete_order('', 1)
                mock_get.assert_not_called()
                mod._delete_order('ref', 0)
                mock_get.assert_not_called()
                mod._delete_order('', 0)
                mock_get.assert_not_called()
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_no_unfiltered_delete_in_cleanup(self):
        """_delete_order filters by both order_reference and company_id."""
        mod = self.mod
        env_backup = os.environ.copy()
        os.environ["SUPABASE_URL"] = "https://test.supabase.co"
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-key"
        try:
            mock_supabase = MagicMock()
            mock_table = MagicMock()
            mock_supabase.table.return_value = mock_table
            mock_delete = MagicMock()
            mock_table.delete.return_value = mock_delete
            mock_eq = MagicMock()
            mock_delete.eq.return_value = mock_eq
            mock_eq.eq.return_value = mock_eq
            mock_eq.execute.return_value = MagicMock(data=[{'id': 1}])
            with patch.object(mod, '_get_supabase', return_value=mock_supabase):
                mod._delete_order('uuid-123', 42)
            mock_supabase.table.assert_called_once()
            mock_table.delete.assert_called_once()
            mock_delete.eq.assert_called_once_with('order_reference', 'uuid-123')
            mock_eq.eq.assert_called_once_with('company_id', 42)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_generate_claim_token_non_empty(self):
        """Generated claim token is non-empty."""
        token = self.mod.generate_claim_token()
        self.assertTrue(len(token) > 0)

    def test_generate_idempotency_key_contains_smoke_test(self):
        """Idempotency key contains smoke-test prefix."""
        key = self.mod.generate_idempotency_key()
        self.assertTrue(key.startswith('smoke-test-'))

    def test_balance_unchanged_passes(self):
        """compare_balance_unchanged passes when values match."""
        before = {'included_balance_micro_myr': 1000, 'topup_balance_micro_myr': 500}
        after = {'included_balance_micro_myr': 1000, 'topup_balance_micro_myr': 500}
        self.mod.compare_balance_unchanged(before, after)

    def test_balance_changed_exits(self):
        """compare_balance_unchanged exits when values differ."""
        before = {'included_balance_micro_myr': 1000, 'topup_balance_micro_myr': 500}
        after = {'included_balance_micro_myr': 2000, 'topup_balance_micro_myr': 500}
        with self.assertRaises(SystemExit):
            self.mod.compare_balance_unchanged(before, after)


    def test_script_never_calls_credit_apply(self):
        """Smoke script does not call credit application functions."""
        import inspect
        source = inspect.getsource(self.mod)
        self.assertNotIn('add_company_ai_credit_topup', source)
        self.assertNotIn('add_ai_credit_topup', source)
        self.assertNotIn('mark_order_paid', source)
        self.assertNotIn('mark_order_credited', source)

    def test_script_never_calls_complete_checkout(self):
        """Smoke script does not call complete_checkout_creation."""
        import inspect
        source = inspect.getsource(self.mod)
        self.assertNotIn('complete_checkout_creation', source)
        self.assertNotIn('update_topup_order_gateway_details', source)

    def test_script_imports_only_safe_functions(self):
        """Smoke script only imports order service and repo functions."""
        import inspect
        source = inspect.getsource(self.mod)
        self.assertIn('create_pending_topup_order', source)
        self.assertIn('claim_checkout_creation', source)
        self.assertIn('fail_checkout_creation', source)


if __name__ == "__main__":
    unittest.main()




