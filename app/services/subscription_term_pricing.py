"""Server-authoritative prepaid subscription term pricing.

Omnexa currently sells Chatbot and GEO together, so these values mirror the
"Both products" table in the approved 2026-10-10 pricing brief.  All amounts
are integer sen; callers must never accept a client-supplied amount.
"""

VALID_BILLING_TERM_MONTHS = (1, 3, 6, 12)

_TERM_DISCOUNT_PERCENT = {
    1: 25,
    3: 30,
    6: 35,
    12: 50,
}

_TERM_PRICE_SEN = {
    "essential": {
        1: (13_350, 13_350),
        3: (37_380, 12_460),
        6: (69_420, 11_570),
        12: (106_800, 8_900),
    },
    "advanced": {
        1: (28_350, 28_350),
        3: (79_380, 26_460),
        6: (147_420, 24_570),
        12: (226_800, 18_900),
    },
    "pro": {
        1: (56_100, 56_100),
        3: (157_080, 52_360),
        6: (291_720, 48_620),
        12: (448_800, 37_400),
    },
}

PAID_PLAN_CODES = frozenset(_TERM_PRICE_SEN)


def normalize_billing_term_months(value, *, default=1) -> int:
    """Return a supported term, rejecting bools and coercion-prone values."""
    if value is None:
        value = default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("billing_term_months must be an integer")
    if value not in VALID_BILLING_TERM_MONTHS:
        allowed = ", ".join(str(months) for months in VALID_BILLING_TERM_MONTHS)
        raise ValueError(f"billing_term_months must be one of: {allowed}")
    return value


def get_subscription_term_price(plan_code: str, billing_term_months=1) -> dict:
    """Return the immutable server price for one plan and prepaid term."""
    normalized_code = plan_code.strip().lower() if isinstance(plan_code, str) else ""
    if normalized_code not in PAID_PLAN_CODES:
        raise ValueError("Invalid subscription plan code")
    term_months = normalize_billing_term_months(billing_term_months)
    amount_sen, monthly_equivalent_sen = _TERM_PRICE_SEN[normalized_code][term_months]
    return {
        "months": term_months,
        "amount_sen": amount_sen,
        "monthly_equivalent_sen": monthly_equivalent_sen,
        "discount_percent": _TERM_DISCOUNT_PERCENT[term_months],
    }


def list_subscription_terms(plan_code: str) -> list[dict]:
    """Return every supported term for a paid plan in display order."""
    return [
        get_subscription_term_price(plan_code, months)
        for months in VALID_BILLING_TERM_MONTHS
    ]
