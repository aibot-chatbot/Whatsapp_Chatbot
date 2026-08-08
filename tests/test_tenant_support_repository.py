import unittest
from unittest.mock import MagicMock, patch

from app.database import tenant_support_repository


class TenantSupportRepositoryTests(unittest.TestCase):
    def test_submission_calls_only_atomic_rpc_with_safe_parameters(self):
        response = MagicMock(data=31)
        with patch.object(tenant_support_repository.supabase, "rpc", return_value=MagicMock(execute=MagicMock(return_value=response))) as rpc:
            result = tenant_support_repository.create_tenant_support_request(
                company_id=100,
                requester_user_id=7,
                category="technical",
                title="Test",
                redacted_description="Test description",
            )
        self.assertEqual(result, 31)
        rpc.assert_called_once_with(
            "create_tenant_support_request",
            {
                "p_company_id": 100,
                "p_requester_user_id": 7,
                "p_category": "technical",
                "p_title": "Test",
                "p_redacted_description": "Test description",
            },
        )

    def test_invalid_rpc_returned_ids_fail_closed(self):
        for returned_id in (None, [], True, 0, "31"):
            with self.subTest(returned_id=returned_id):
                response = MagicMock(data=returned_id)
                with patch.object(
                    tenant_support_repository.supabase,
                    "rpc",
                    return_value=MagicMock(
                        execute=MagicMock(return_value=response)
                    ),
                ):
                    with self.assertRaises(RuntimeError):
                        tenant_support_repository.create_tenant_support_request(
                            company_id=100,
                            requester_user_id=7,
                            category="technical",
                            title="Test",
                            redacted_description="Test description",
                        )


if __name__ == "__main__":
    unittest.main()
