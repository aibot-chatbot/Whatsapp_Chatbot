import unittest
from unittest.mock import MagicMock, patch

from app.database import tenant_support_repository


class TenantSupportRepositoryTests(unittest.TestCase):
    def test_staff_details_use_legacy_projections_and_keep_priority_source(self):
        row = {"id": 31, "priority": "normal", "source": "tenant",
               "converted_platform_support_case_id": 7}
        query = MagicMock()
        query.eq.return_value = query
        query.limit.return_value = query

        def select(fields):
            self.assertNotIn("escalation_context", fields)
            return query

        query.select.side_effect = select
        query.execute.return_value = MagicMock(data=[row])
        with patch.object(tenant_support_repository.supabase, "table", return_value=query):
            detail = tenant_support_repository.get_tenant_support_request_for_platform_admin(31)
            query.select.assert_called_once_with(tenant_support_repository.REQUEST_DETAIL_FIELDS)
            self.assertEqual(detail, row)
            query.select.reset_mock()
            linked = tenant_support_repository.get_tenant_support_request_by_converted_case_id_for_platform_admin(7)
            query.select.assert_called_once_with(
                tenant_support_repository.REQUEST_FIELDS + ",converted_platform_support_case_id"
            )
            self.assertEqual(linked, row)

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

    def test_tenant_history_queries_are_scoped_to_company_and_requester(self):
        query = MagicMock()
        for method in ("select", "eq", "order", "range"):
            getattr(query, method).return_value = query
        query.execute.return_value = MagicMock(data=[{"id": 31}], count=1)
        with patch.object(tenant_support_repository.supabase, "table", return_value=query):
            rows, total = tenant_support_repository.list_tenant_support_requests_for_tenant(
                company_id=100, requester_user_id=7, limit=25, offset=0
            )
        self.assertEqual((rows, total), ([{"id": 31}], 1))
        query.eq.assert_any_call("company_id", 100)
        query.eq.assert_any_call("requester_user_id", 7)
        self.assertNotIn("converted_platform_support_case_id", tenant_support_repository.REQUEST_FIELDS)

    def test_tenant_reply_query_uses_safe_projection_and_visibility_filter(self):
        query = MagicMock()
        for method in ("select", "eq", "order"):
            getattr(query, method).return_value = query
        query.execute.return_value = MagicMock(data=[{"id": 44, "redacted_body": "Visible"}])
        with patch.object(tenant_support_repository.supabase, "table", return_value=query):
            replies = tenant_support_repository.list_tenant_support_replies_for_tenant(
                31, company_id=100
            )
        self.assertEqual(replies, [{"id": 44, "redacted_body": "Visible"}])
        query.select.assert_called_once_with(tenant_support_repository.TENANT_REPLY_FIELDS)
        query.eq.assert_any_call("request_id", 31)
        query.eq.assert_any_call("company_id", 100)
        query.eq.assert_any_call("visibility_status", "visible")
        self.assertNotIn("author_platform_admin_user_id", tenant_support_repository.TENANT_REPLY_FIELDS)
        self.assertNotIn("platform_support_case_id", tenant_support_repository.TENANT_REPLY_FIELDS)


if __name__ == "__main__":
    unittest.main()
