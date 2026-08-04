import unittest
from pathlib import Path


DOC = Path(__file__).resolve().parents[1] / "docs" / "PLATFORM_ADMIN_OPERATIONAL_ALERTS_CONTRACT.md"


class PlatformAdminOperationalAlertsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text(encoding="utf-8")

    def test_phase_one_and_response_contract_are_recorded(self):
        for phrase in [
            "subscription_past_due",
            "subscription_expired",
            "operational_alerts.alerts",
            "operational_alerts.summary",
            "operational_alerts.limits.max_alerts",
            "current 12-route platform-admin stack remains",
            "production remains blocked",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_all_phase_two_candidates_are_deferred(self):
        for alert_type in [
            "ai_credit_low",
            "ai_credit_depleted",
            "company_inactive",
            "no_current_chatbot",
            "billing_order_requires_attention",
            "no_subscription_recorded",
        ]:
            with self.subTest(alert_type=alert_type):
                self.assertIn(f"`{alert_type}`", self.text)
        self.assertIn("All candidates below are deferred.", self.text)

    def test_safety_exclusions_and_approval_gates_are_present(self):
        for phrase in [
            "No remediation buttons or write controls",
            "payment, reconciliation, checkout, manual credit",
            "No current cross-company",
            "[ ] Alert definition approved.",
            "[ ] False-positive and exclusion rule approved.",
            "[ ] Safe fields and redaction boundary approved.",
            "[ ] Bounded query and failure behavior reviewed.",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
