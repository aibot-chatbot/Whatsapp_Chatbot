from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.billing_period_service import (
    calculate_monthly_allowance_period,
    calculate_prepaid_term_end,
)
from app.services.subscription_term_pricing import (
    get_subscription_term_price,
    list_subscription_terms,
    normalize_billing_term_months,
)


@pytest.mark.parametrize(
    ("plan_code", "months", "amount_sen", "monthly_equivalent_sen"),
    [
        ("essential", 1, 13_350, 13_350),
        ("essential", 3, 37_380, 12_460),
        ("essential", 6, 69_420, 11_570),
        ("essential", 12, 106_800, 8_900),
        ("advanced", 1, 28_350, 28_350),
        ("advanced", 3, 79_380, 26_460),
        ("advanced", 6, 147_420, 24_570),
        ("advanced", 12, 226_800, 18_900),
        ("pro", 1, 56_100, 56_100),
        ("pro", 3, 157_080, 52_360),
        ("pro", 6, 291_720, 48_620),
        ("pro", 12, 448_800, 37_400),
    ],
)
def test_document_approved_bundled_prices(
    plan_code, months, amount_sen, monthly_equivalent_sen
):
    price = get_subscription_term_price(plan_code, months)
    assert price["amount_sen"] == amount_sen
    assert price["monthly_equivalent_sen"] == monthly_equivalent_sen


@pytest.mark.parametrize("value", [True, False, "3", 2, 24, 0, -1])
def test_term_validation_rejects_coercion_and_unsupported_values(value):
    with pytest.raises(ValueError, match="billing_term_months"):
        normalize_billing_term_months(value)


def test_every_paid_plan_exposes_terms_in_display_order():
    assert [item["months"] for item in list_subscription_terms("pro")] == [1, 3, 6, 12]


def test_twelve_month_contract_still_has_monthly_allowance_windows():
    start = datetime(2026, 1, 31, 10, 0, tzinfo=timezone.utc)
    contract_end = calculate_prepaid_term_end(start, 12)
    allowance_start, allowance_end = calculate_monthly_allowance_period(
        start,
        contract_end,
        now=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
    )
    assert allowance_start.isoformat() == "2026-02-28T10:00:00+00:00"
    assert allowance_end.isoformat() == "2026-03-31T10:00:00+00:00"
    assert contract_end.isoformat() == "2027-01-31T10:00:00+00:00"


def test_version_three_activation_uses_order_term_for_paid_through_date():
    from app.services.subscription_payment_callback_service import _activate_subscription_plan

    order = {
        "order_reference": "term-order",
        "company_id": 42,
        "new_plan_id": 2,
        "subscription_id": 9,
        "source_plan_id": 1,
        "source_period_start": "2026-01-01T00:00:00+00:00",
        "source_period_end": "2026-02-01T00:00:00+00:00",
        "source_status": "trialing",
        "activation_type": "initial_purchase",
        "activation_sequence_key": "company:42:initial",
        "order_schema_version": 3,
        "billing_term_months": 12,
        "status": "paid",
    }
    prefix = "app.services.subscription_payment_callback_service"
    with patch(prefix + ".get_plan_by_id", return_value={"code": "essential", "included_ai_credit_micro_myr": 5_000_000}), patch(
        prefix + "._claim_activation_sequence"
    ), patch(prefix + "._update_activation_state"), patch(
        prefix + ".conditional_activate_subscription", return_value={"id": 9}
    ) as activate, patch(prefix + "._ensure_company_ai_credit", return_value={"period_changed": True}), patch(
        prefix + ".convert_trial_ai_configuration"
    ), patch(prefix + "._mark_order_credited"):
        result = _activate_subscription_plan(order, "txn", "2026-01-01T00:00:00Z")

    assert result["billing_term_months"] == 12
    kwargs = activate.call_args.kwargs
    assert kwargs["billing_term_months"] == 12
    start = datetime.fromisoformat(kwargs["period_start_iso"])
    end = datetime.fromisoformat(kwargs["period_end_iso"])
    assert end == calculate_prepaid_term_end(start, 12)


def test_prepaid_term_migration_is_reviewable_and_service_role_only():
    sql = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "079_prepaid_subscription_terms.sql"
    ).read_text(encoding="utf-8")
    assert "billing_term_months smallint NOT NULL DEFAULT 1" in sql
    assert "monthly_equivalent_sen integer NOT NULL DEFAULT 0" in sql
    assert "price = 133.50" in sql
    assert "price = 283.50" in sql
    assert "price = 561.00" in sql
    assert "make_interval(months => v_month_index + 1)" in sql
    assert "REVOKE ALL ON FUNCTION public.ensure_company_ai_credit_period(bigint) FROM PUBLIC, anon, authenticated" in sql
    assert "GRANT EXECUTE ON FUNCTION public.ensure_company_ai_credit_period(bigint) TO service_role" in sql
