"""Source-contract tests for public landing pricing alignment."""

import ast
import os
import re
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


AUTHORITATIVE_PUBLIC_PLANS = {
    "free": {
        "name": "Free",
        "price": "0",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "channel_limit": 1,
        "description": "Basic plan for trying the chatbot platform.",
        "knowledge_file_limit": 3,
        "knowledge_storage_limit_bytes": 52428800,
        "model_access_label": "DeepSeek Only",
        "included_ai_credit_micro_myr": 1000000,
        "trial_only": True,
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "ai_assisted_menu_generation": False,
            "ai_generated_reports": False,
            "crm_lead_assignment": False,
        },
    },
    "essential": {
        "name": "Essential",
        "price": "39",
        "chatbot_limit": 1,
        "team_member_limit": 1,
        "channel_limit": 1,
        "description": "Essential plan - 1 chatbot, 1 channel, 5 knowledge files, 50 MB storage",
        "knowledge_file_limit": 5,
        "knowledge_storage_limit_bytes": 52428800,
        "model_access_label": "Economy Model Tier",
        "included_ai_credit_micro_myr": 5000000,
        "trial_only": False,
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "ai_assisted_menu_generation": False,
            "ai_generated_reports": False,
            "crm_lead_assignment": False,
        },
    },
    "advanced": {
        "name": "Advanced",
        "price": "89",
        "chatbot_limit": 2,
        "team_member_limit": 3,
        "channel_limit": 2,
        "description": "Advanced plan - 2 chatbots, 2 channels, 25 knowledge files, 250 MB storage",
        "knowledge_file_limit": 25,
        "knowledge_storage_limit_bytes": 262144000,
        "model_access_label": "Standard Model Tier",
        "included_ai_credit_micro_myr": 20000000,
        "trial_only": False,
        "feature_flags": {
            "single_website_scraping": True,
            "batch_website_scraping": False,
            "ai_assisted_menu_generation": True,
            "ai_generated_reports": False,
            "crm_lead_assignment": True,
        },
    },
    "pro": {
        "name": "Pro",
        "price": "169",
        "chatbot_limit": 3,
        "team_member_limit": 5,
        "channel_limit": 2,
        "description": "Premium plan for teams that need the highest published limits and full feature access.",
        "knowledge_file_limit": 75,
        "knowledge_storage_limit_bytes": 1073741824,
        "model_access_label": "Premium Model Tier",
        "included_ai_credit_micro_myr": 60000000,
        "trial_only": False,
        "feature_flags": {
            "single_website_scraping": True,
            "batch_website_scraping": True,
            "ai_assisted_menu_generation": True,
            "ai_generated_reports": True,
            "crm_lead_assignment": True,
        },
    },
}

RUNTIME_PLAN_DESCRIPTIONS = {
    "free": "Basic plan for trying the chatbot platform.",
    "essential": "Essential plan - 1 chatbot, 1 channel, 5 knowledge files, 50 MB storage",
    "advanced": "Advanced plan - 2 chatbots, 2 channels, 25 knowledge files, 250 MB storage",
    # Current database/API data still exposes this legacy description. Public
    # landing copy intentionally differs until a reviewed data migration fixes
    # subscription_plans.description at source.
    "pro": "Temporary example plan with unlimited resource limits.",
}


def _read(path):
    return path.read_text(encoding="utf-8")


def _catalogue_plans():
    source = _read(FRONTEND / "assets" / "js" / "plan-catalog.js")
    match = re.search(r"var plans = (\[.*?\]);", source, re.S)
    assert match, "plan-catalog.js must expose a literal plans array"
    literal = re.sub(r"\btrue\b", "True", match.group(1))
    literal = re.sub(r"\bfalse\b", "False", literal)
    literal = re.sub(r"(\s*)([a-zA-Z_][a-zA-Z0-9_]*):", r'\1"\2":', literal)
    plans = ast.literal_eval(literal)
    return {plan["code"]: plan for plan in plans}


def test_public_plan_catalog_matches_authoritative_subscription_contract():
    plans = _catalogue_plans()
    assert list(plans) == ["free", "essential", "advanced", "pro"]

    for code, expected in AUTHORITATIVE_PUBLIC_PLANS.items():
        plan = plans[code]
        for key, expected_value in expected.items():
            assert plan[key] == expected_value, f"{code}.{key}"
        assert plan["currency"] == "MYR"
        assert plan["billing_interval"] == "monthly"
        assert "id" not in plan

    assert "temporary example" not in plans["pro"]["description"].lower()
    assert "unlimited" not in plans["pro"]["description"].lower()
    assert plans["free"]["model_access_label"] == "DeepSeek Only"


def test_plan_catalog_values_are_backed_by_existing_migration_contracts():
    paid_catalogue = _read(ROOT / "data" / "003_upsert_subscription_plans.sql")
    feature_flags = _read(ROOT / "data" / "004_add_subscription_plan_feature_flags.sql")
    commercial = _read(ROOT / "data" / "005_update_subscription_commercial_values.sql")
    free_credit = _read(ROOT / "data" / "019_set_trial_ai_credit.sql")
    free_team = _read(ROOT / "data" / "020_free_plan_owner_only_team_limit.sql")

    assert "Preserves the existing Free plan unchanged" in paid_catalogue
    assert "knowledge_file_limit" not in free_credit
    assert "knowledge_storage_limit_bytes" not in free_credit
    assert "knowledge_file_limit" not in free_team
    assert "knowledge_storage_limit_bytes" not in free_team
    assert "price = 39" in commercial
    assert "price = 89" in commercial
    assert "price = 169" in commercial
    assert "included_ai_credit_micro_myr = 5000000" in commercial
    assert "included_ai_credit_micro_myr = 20000000" in commercial
    assert "included_ai_credit_micro_myr = 60000000" in commercial
    assert "included_ai_credit_micro_myr = 1000000" in free_credit
    assert "team_member_limit = 1" in free_team

    for expected in [
        "chatbot_limit = 1",
        "knowledge_file_limit = 5",
        "knowledge_storage_limit_bytes = 52428800",
        "model_access_tier = 'economy'",
        "chatbot_limit = 2",
        "knowledge_file_limit = 25",
        "knowledge_storage_limit_bytes = 262144000",
        "model_access_tier = 'standard'",
        "chatbot_limit = 3",
        "knowledge_file_limit = 75",
        "knowledge_storage_limit_bytes = 1073741824",
        "model_access_tier = 'premium'",
    ]:
        assert expected in paid_catalogue

    for expected in [
        "'single_website_scraping', true",
        "'batch_website_scraping', true",
        "'ai_generated_reports', true",
        "'ai_assisted_menu_generation', true",
        "'crm_lead_assignment', true",
    ]:
        assert expected in feature_flags or expected in paid_catalogue


def test_public_catalog_matches_billing_service_serialization_shape():
    from app.services.billing_service import list_active_plans

    runtime_rows = []
    for plan in AUTHORITATIVE_PUBLIC_PLANS.values():
        row = {
            "name": plan["name"],
            "code": next(code for code, value in AUTHORITATIVE_PUBLIC_PLANS.items() if value is plan),
            "description": RUNTIME_PLAN_DESCRIPTIONS[next(code for code, value in AUTHORITATIVE_PUBLIC_PLANS.items() if value is plan)],
            "price": plan["price"],
            "currency": "MYR",
            "billing_interval": "monthly",
            "chatbot_limit": plan["chatbot_limit"],
            "team_member_limit": plan["team_member_limit"],
            "knowledge_file_limit": plan["knowledge_file_limit"],
            "knowledge_storage_limit_bytes": plan["knowledge_storage_limit_bytes"],
            "channel_limit": plan["channel_limit"],
            "feature_flags": plan["feature_flags"],
            "included_ai_credit_micro_myr": plan["included_ai_credit_micro_myr"],
            "model_access_tier": "economy" if plan["model_access_label"] in {"DeepSeek Only", "Economy Model Tier"} else plan["model_access_label"].split()[0].lower(),
        }
        runtime_rows.append(row)

    with patch("app.services.billing_service._get_active_plans", return_value=runtime_rows):
        serialized = list_active_plans()

    by_code = {plan["code"]: plan for plan in serialized}
    for code, expected in AUTHORITATIVE_PUBLIC_PLANS.items():
        plan = by_code[code]
        assert plan["description"] == RUNTIME_PLAN_DESCRIPTIONS[code]
        if code != "pro":
            assert plan["description"] == expected["description"]
        else:
            assert plan["description"] != expected["description"]
        assert plan["knowledge_file_limit"] == expected["knowledge_file_limit"]
        assert plan["knowledge_storage_limit_bytes"] == expected["knowledge_storage_limit_bytes"]
        assert plan["included_ai_credit_micro_myr"] == expected["included_ai_credit_micro_myr"]


def test_landing_uses_shared_catalog_and_removes_stale_pricing_claims():
    landing = _read(FRONTEND / "landing.html")
    pricing = _read(FRONTEND / "pricing.html")

    assert 'src="assets/js/plan-catalog.js"' in landing
    assert 'id="landing-pricing-grid"' in landing
    assert "/api/billing/plans" in pricing
    assert "authenticatedFetch" in pricing
    assert "grid.innerHTML" not in pricing
    assert ".textContent = desc" in pricing
    assert "OpenRouter" not in pricing
    assert "GPT-4.1" not in pricing
    assert "GPT-5.5" not in pricing

    for stale in [
        "RM 29.00",
        "RM 79.00",
        "RM 199.00",
        "Email Support",
        "Priority Email Support",
        "24/7 Dedicated Support",
        "Basic Support",
        "Temporary example plan",
        "unlimited resource limits",
    ]:
        assert stale not in landing

    assert "requireLogin()" not in landing
    assert "authenticatedFetch(" not in landing
    assert "register.html" in landing
    assert "pricing.html" in landing


def test_customer_facing_feature_labels_are_canonical():
    landing = _read(FRONTEND / "landing.html")
    pricing = _read(FRONTEND / "pricing.html")
    for label in [
        "AI-Assisted Menu Generation",
        "AI-Generated Reports",
        "CRM Lead Assignment",
        "Single Website Scraping",
        "Batch Website Scraping",
        "AI Credit",
    ]:
        assert label in landing
        assert label in pricing

    assert " Ai " not in landing


def test_authenticated_pricing_uses_explicit_customer_feature_allowlist():
    pricing = _read(FRONTEND / "pricing.html")

    assert "var CUSTOMER_FEATURE_FLAGS = [" in pricing
    assert pricing.index('"ai_assisted_menu_generation"') < pricing.index('"ai_generated_reports"')
    assert pricing.index('"ai_generated_reports"') < pricing.index('"crm_lead_assignment"')
    assert pricing.index('"crm_lead_assignment"') < pricing.index('"single_website_scraping"')
    assert pricing.index('"single_website_scraping"') < pricing.index('"batch_website_scraping"')
    assert "Object.keys(features)" not in pricing
    assert "key.replace(/_/g" not in pricing
    assert "features[key] === true" in pricing
