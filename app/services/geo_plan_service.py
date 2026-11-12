"""Stable, cost-bounded GEO product contract for each paid plan.

The unit charged against the monthly allowance is one provider execution:
one prompt sent to one AI-search platform.  Keeping that unit explicit avoids
calling a multi-platform analysis a single "prompt" when it can create several
billable provider requests.
"""

from copy import deepcopy

ALL_GEO_PLATFORMS = ("chatgpt", "gemini", "claude", "deepseek", "perplexity")

GEO_PLAN_ENTITLEMENTS = {
    "essential": {
        "plan_code": "essential",
        "label": "Essential",
        "monthly_executions": 10,
        "prompts_per_analysis": 2,
        "keywords_per_analysis": 2,
        "executions_per_analysis": 10,
        "monitoring_frequencies": ("monthly",),
        "platforms": ALL_GEO_PLATFORMS,
        "samples_per_prompt": 1,
        "history_limit": 10,
    },
    "advanced": {
        "plan_code": "advanced",
        "label": "Advanced",
        "monthly_executions": 40,
        "prompts_per_analysis": 5,
        "keywords_per_analysis": 5,
        "executions_per_analysis": 20,
        "monitoring_frequencies": ("weekly", "monthly"),
        "platforms": ALL_GEO_PLATFORMS,
        "samples_per_prompt": 1,
        "history_limit": 25,
    },
    "pro": {
        "plan_code": "pro",
        "label": "Pro",
        "monthly_executions": 120,
        "prompts_per_analysis": 10,
        "keywords_per_analysis": 10,
        "executions_per_analysis": 20,
        "monitoring_frequencies": ("weekly", "monthly"),
        "platforms": ALL_GEO_PLATFORMS,
        "samples_per_prompt": 1,
        "history_limit": 50,
    },
}


def get_geo_plan_entitlement(plan_code):
    """Return a mutable API-safe entitlement copy, or ``None`` for Free/unknown."""
    code = str(plan_code or "").strip().casefold()
    value = GEO_PLAN_ENTITLEMENTS.get(code)
    if value is None:
        return None
    result = deepcopy(value)
    result["platforms"] = list(result["platforms"])
    result["monitoring_frequencies"] = list(result["monitoring_frequencies"])
    return result

