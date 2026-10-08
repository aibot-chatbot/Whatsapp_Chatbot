"""Source-contract tests for public landing pricing alignment."""

import ast
import html
import json
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
        "model_access_label": "1 entry model",
        "included_ai_credit_micro_myr": 1000000,
        "trial_only": True,
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "availability_booking": False,
            "ai_assisted_menu_generation": False,
            "ai_generated_reports": False,
            "crm_lead_assignment": False,
            "knowledge_refinement": False,
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
        "model_access_label": "GPT-6 Luna, Gemini 3.8 Flash",
        "included_ai_credit_micro_myr": 5000000,
        "trial_only": False,
        "feature_flags": {
            "single_website_scraping": False,
            "batch_website_scraping": False,
            "availability_booking": False,
            "ai_assisted_menu_generation": False,
            "ai_generated_reports": False,
            "crm_lead_assignment": False,
            "knowledge_refinement": False,
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
        "model_access_label": "GPT-6 Luna, Gemini 3.8 Flash, Claude Haiku 4.5",
        "included_ai_credit_micro_myr": 20000000,
        "trial_only": False,
        "feature_flags": {
            "single_website_scraping": True,
            "batch_website_scraping": False,
            "availability_booking": False,
            "ai_assisted_menu_generation": True,
            "ai_generated_reports": False,
            "crm_lead_assignment": True,
            "knowledge_refinement": False,
        },
    },
    "pro": {
        "name": "Pro",
        "price": "169",
        "chatbot_limit": 3,
        "team_member_limit": 5,
        "channel_limit": 4,
        "description": "Premium plan for teams that need the highest published limits and full feature access.",
        "knowledge_file_limit": 75,
        "knowledge_storage_limit_bytes": 1073741824,
        "model_access_label": "GPT-6.1 Sol, Claude Sonnet 5.5, Gemini 3.1 Pro",
        "included_ai_credit_micro_myr": 60000000,
        "trial_only": False,
        "feature_flags": {
            "single_website_scraping": True,
            "batch_website_scraping": True,
            "availability_booking": True,
            "ai_assisted_menu_generation": True,
            "ai_generated_reports": True,
            "crm_lead_assignment": True,
            "knowledge_refinement": True,
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
    # Customer-facing labels never name the infrastructure provider (owner decision 2026-10-03).
    assert plans["free"]["model_access_label"] == "1 entry model"


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

    # The database tier is its own column; the public label only describes it (Free and Essential
    # are both "economy", matching the migration asserted above).
    model_tier_by_code = {"free": "economy", "essential": "economy", "advanced": "standard", "pro": "premium"}
    runtime_rows = []
    for code, plan in AUTHORITATIVE_PUBLIC_PLANS.items():
        row = {
            "name": plan["name"],
            "code": code,
            "description": RUNTIME_PLAN_DESCRIPTIONS[code],
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
            "model_access_tier": model_tier_by_code[code],
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
    # The pricing screen keeps its behaviour in assets/js/pricing.js now, so
    # the JS contracts below are asserted there rather than in the page source.
    landing = _read(FRONTEND / "landing.html")
    pricing = _read(FRONTEND / "pricing.html")
    pricing_js = _read(FRONTEND / "assets" / "js" / "pricing.js")

    assert 'id="landing-pricing-grid"' in landing
    assert 'src="assets/js/pricing.js"' in pricing
    assert "/api/billing/plans" in pricing_js
    assert "authenticatedFetch" in pricing_js

    # Plan text is attacker-controlled, so it is only ever written as text.
    # No innerHTML anywhere in the pricing behaviour is the strong form of
    # the old ".textContent = desc" assertion.
    assert ".innerHTML" not in pricing_js
    assert "innerHTML =" not in pricing_js

    # Stale model names and the retired DeepSeek-only claim stay banned.
    for banned in ["GPT-4.1", "GPT-5.5", "DeepSeek"]:
        assert banned not in pricing
        assert banned not in pricing_js

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


def test_customer_facing_feature_labels_are_canonical():
    # The authenticated pricing screen still sells the chatbot feature set, so
    # its canonical labels stay pinned. The public landing page was repositioned
    # around multi-channel publishing and no longer carries these names.
    pricing_js = _read(FRONTEND / "assets" / "js" / "pricing.js")
    for label in [
        "AI-Assisted Menu Generation",
        "AI-Generated Reports",
        "CRM Lead Assignment",
        "Single Website Scraping",
        "Batch Website Scraping",
        "AI Credit",
    ]:
        assert label in pricing_js


def test_landing_pricing_matches_the_billed_plan_catalogue():
    """The landing page may only quote money the billing system actually charges.

    Same intent as the old TBC guard, now that the tiers are signed off. The
    four rows below mirror `subscription_plans` in Supabase, which is what
    /api/billing/plans serves to the dashboard and the pricing page. If a price
    changes there, this test fails until the landing page is updated to match -
    which is the point. Marketing copy drifting away from what is billed is the
    exact failure this guards against.
    """
    landing = _read(FRONTEND / "landing.html")

    assert " Ai " not in landing

    catalogue = {"free": "RM 0", "essential": "RM 39",
                 "advanced": "RM 89", "pro": "RM 169"}
    for code, price in catalogue.items():
        assert f'data-plan-code="{code}"' in landing, f"{code} plan missing from landing"
        assert price in landing, f"{code} must advertise {price}"

    # The retired placeholder tiers must not reappear.
    for gone in ("starter", "growth", "business"):
        assert f'data-plan-code="{gone}"' not in landing
    assert "TBC" not in landing
    assert "Paid pricing is not final" not in landing

    # Every Ringgit figure on the page must be either a plan price or one of
    # the included AI credit allowances. Anything else is an invented number.
    allowed = {"RM 0", "RM 39", "RM 89", "RM 169",
               "RM 1", "RM 5", "RM 20", "RM 60"}
    amounts = set(re.findall(r"RM\s?\d+(?:[.,]\d+)*", landing))
    assert amounts <= allowed, f"unapproved amount on landing page: {amounts - allowed}"

    # Prices are billed in MYR; a foreign symbol means a stale figure returned.
    assert not re.findall(r"[$£€]\s?\d", landing), "non-MYR price on landing page"


def test_landing_discloses_the_enforced_geo_plan_contract():
    landing = _read(FRONTEND / "landing.html")

    for expected in [
        "GEO: 10 provider checks monthly",
        "1 prompt per GEO analysis",
        "ChatGPT Search, Gemini and Perplexity measurement",
        "GEO: 40 provider checks monthly",
        "Up to 2 prompts per GEO analysis",
        "GEO: 120 provider checks monthly",
        "Up to 4 prompts per GEO analysis",
        "ChatGPT Search, Gemini and Perplexity measurement",
        "one provider check means one prompt sent to one AI-search platform",
    ]:
        assert expected in landing

    assert "<li>4 channels</li>" in landing


def test_landing_does_not_overclaim_channels_or_customers():
    """WhatsApp/Telegram/Wasender ship; the rest must read as roadmap.

    The product has no customers yet, so testimonial and social-proof shapes
    must not appear at all.
    """
    landing = _read(FRONTEND / "landing.html")

    for live in ["WhatsApp", "Telegram", "Wasender"]:
        assert live in landing

    assert "in development" in landing.lower()
    for roadmap in ["Instagram", "Facebook", "LinkedIn"]:
        assert roadmap in landing

    for fabricated in ["Trusted by", "testimonial", "customers worldwide", "5-star"]:
        assert fabricated.lower() not in landing.lower()


# The plan flags a pricing card lists, in the order a plan first gains them, and the words a
# customer reads. LIVE_PLAN_FLAGS is what the live plans carry (queried from production on
# 2026-10-02); every flag here is enforced by the backend (billing_guard.PLAN_FEATURES).
FLAG_ORDER = [
    "ai_derived_persona", "conversation_memory", "crm_lead_assignment", "single_website_scraping",
    "ai_assisted_menu_generation", "unified_knowledge_ingestion", "ai_generated_reports",
    "automation_workflows", "knowledge_refinement", "batch_website_scraping", "availability_booking",
]
FLAG_LABELS = {
    "ai_derived_persona": "AI-Derived Bot Persona",
    "conversation_memory": "Conversation Memory",
    "crm_lead_assignment": "CRM Lead Assignment",
    "single_website_scraping": "Single Website Scraping",
    "ai_assisted_menu_generation": "AI-Assisted Menu Generation",
    "unified_knowledge_ingestion": "Guided Knowledge Ingestion",
    "ai_generated_reports": "AI-Generated Reports",
    "automation_workflows": "Automation Workflows",
    "knowledge_refinement": "Knowledge Refinement Q&A",
    "batch_website_scraping": "Batch Website Scraping",
    "availability_booking": "Availability Booking",
}
LIVE_PLAN_FLAGS = {
    "free": set(),
    "essential": {"ai_derived_persona", "conversation_memory"},
    "advanced": {"ai_derived_persona", "conversation_memory", "crm_lead_assignment",
                 "single_website_scraping", "ai_assisted_menu_generation", "unified_knowledge_ingestion"},
    "pro": set(FLAG_ORDER),
}


def test_authenticated_pricing_uses_explicit_customer_feature_allowlist():
    pricing_js = _read(FRONTEND / "assets" / "js" / "pricing.js")

    allowlist = re.search(r"var CUSTOMER_FEATURE_FLAGS = \[(.*?)\];", pricing_js, re.S)
    labels = re.search(r"var FLAG_LABELS = \{(.*?)\};", pricing_js, re.S)
    assert allowlist and labels, "pricing.js must keep an explicit allowlist and label table"
    assert re.findall(r'"([a-z_]+)"', allowlist.group(1)) == FLAG_ORDER
    assert dict(re.findall(r'([a-z_]+): "([^"]+)"', labels.group(1))) == FLAG_LABELS

    # Unknown flags must never leak into the plan table by enumeration.
    assert "Object.keys(features)" not in pricing_js
    assert "key.replace(/_/g" not in pricing_js
    assert "flags[key] === true" in pricing_js


def test_the_pricing_card_lists_every_flag_the_backend_enforces():
    from app.services.billing_guard import PLAN_FEATURES

    assert set(FLAG_ORDER) == set(PLAN_FEATURES), (
        "a plan flag was added or removed: decide whether customers should see it on the pricing card")


def test_flags_are_listed_in_the_order_a_plan_first_gains_them():
    rank = {"free": 0, "essential": 1, "advanced": 2, "pro": 3}
    first_plan = [min(rank[code] for code, flags in LIVE_PLAN_FLAGS.items() if flag in flags) for flag in FLAG_ORDER]

    assert first_plan == sorted(first_plan), "ticks should climb from Essential to Advanced to Pro"
    assert all(flag in LIVE_PLAN_FLAGS["pro"] for flag in FLAG_ORDER), "Pro has everything"


def test_the_pricing_card_always_lists_chat_booking_requests():
    pricing_js = _read(FRONTEND / "assets" / "js" / "pricing.js")

    # Bookings has no plan limit, so the row is always on and is not read from a flag.
    assert 'featureRow("chat_bookings", true)' in pricing_js
    assert "Chat Booking Requests" in pricing_js


def _landing_bullets():
    landing = _read(FRONTEND / "landing.html")
    cards = re.findall(r'<div class="plan[^"]*" data-plan-code="([a-z]+)">(.*?)</ul>', landing, re.S)
    return {code: [html.unescape(item).strip() for item in re.findall(r"<li>(.*?)</li>", body)]
            for code, body in cards}


def test_each_landing_card_lists_exactly_the_features_its_plan_has():
    bullets = _landing_bullets()
    assert list(bullets) == ["free", "essential", "advanced", "pro"]

    for code, items in bullets.items():
        lowered = [item.lower() for item in items]
        for flag, label in FLAG_LABELS.items():
            listed = label.lower() in lowered
            assert listed == (flag in LIVE_PLAN_FLAGS[code]), f"{code}: {label} should be {'listed' if flag in LIVE_PLAN_FLAGS[code] else 'absent'}"
        assert "chat booking requests" in lowered, f"{code}: bookings work on every plan"


def test_each_landing_card_names_the_same_ai_models_as_the_plan_catalogue():
    bullets = _landing_bullets()
    catalogue = _catalogue_plans()

    for code, items in bullets.items():
        assert f"AI models: {catalogue[code]['model_access_label']}" in items, code


def test_authenticated_pricing_redirects_only_for_valid_checkout_url():
    pricing_js = _read(FRONTEND / "assets" / "js" / "pricing.js")

    assert 'authenticatedFetch("/api/billing/subscription/checkout"' in pricing_js
    assert "body.data.checkout_url" in pricing_js

    # Only an absolute http(s) URL may be navigated to. A relative or
    # javascript: URL returned by a compromised backend must not be followed.
    assert "^https?:" in pricing_js
    assert "window.location.assign(url)" in pricing_js

    # A rejected URL surfaces an error instead of navigating.
    assert "showError(" in pricing_js
    assert "window.alert(" not in pricing_js


def test_customer_facing_pricing_never_names_the_ai_infrastructure_provider():
    # Owner decision 2026-10-03: plans name model tiers and model families, never the platform
    # that serves them. The privacy policy is where processors are disclosed, so it is not here.
    surfaces = [FRONTEND / "landing.html", FRONTEND / "assets" / "js" / "pricing.js",
                FRONTEND / "assets" / "js" / "plan-catalog.js", FRONTEND / "assets" / "js" / "billing.js"]
    for path in surfaces:
        source = _read(path)
        for provider in ("Cloudflare", "OpenRouter"):  # case-sensitive: CDN hostnames are lowercase
            assert provider not in source, f"{path.name} names {provider}"


def test_behaviour_studio_offers_models_by_name_without_a_provider_picker():
    # The provider is derived from the chosen model (option data-provider), never shown or chosen.
    page = _read(FRONTEND / "behaviour.html")
    script = _read(FRONTEND / "assets" / "js" / "behaviour.js")
    assert 'id="bh-provider"' not in page and 'id="bh-model"' in page
    assert "AI provider" not in script and "provider.label" not in script
    assert "option.dataset.provider = choice.provider;" in script


def _landing_structured_data():
    landing = _read(FRONTEND / "landing.html")
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', landing, re.S)
    assert block, "landing page must carry JSON-LD"
    return {node["@type"]: node for node in json.loads(block.group(1))["@graph"]}


def test_structured_data_offers_the_billed_plans_in_ringgit():
    offers = _landing_structured_data()["SoftwareApplication"]["offers"]
    assert {offer["priceCurrency"] for offer in offers} == {"MYR"}
    assert sorted(float(offer["price"]) for offer in offers) == [0, 39, 89, 169]
    assert "aggregateRating" not in _landing_structured_data()["SoftwareApplication"], "no real reviews exist"


def test_faq_structured_data_matches_the_visible_faq():
    # Search engines ignore (or penalise) FAQ markup that differs from what a reader sees.
    landing = _read(FRONTEND / "landing.html")
    faq = re.search(r'<section class="wrap" id="faq">(.*?)</section>', landing, re.S).group(1)
    visible = [(html.unescape(q), html.unescape(a)) for q, a in
               re.findall(r"<summary>(.*?)</summary>\s*<p>(.*?)</p>", faq, re.S)]
    marked = [(item["name"], item["acceptedAnswer"]["text"])
              for item in _landing_structured_data()["FAQPage"]["mainEntity"]]
    assert visible and visible == marked
    assert not any("two channels" in answer for _, answer in visible), "Free has one channel"
