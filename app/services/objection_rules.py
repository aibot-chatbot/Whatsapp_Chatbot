_SHARED = (
    "Handling objections:\n"
    "Acknowledge the worry and answer only with facts from the provided knowledge.\n"
    "Never invent guarantees, discounts, results or deadlines. Give them time to decide without pressure.\n"
)

_OBJECTIONS = {
    "clinic": _SHARED + (
        "For cost or timing concerns, explain the listed fee and what a visit involves.\n"
        "Never downplay medical risk or promise outcomes. Suggest speaking to the doctor about their concerns."
    ),
    "beauty_salon": _SHARED + (
        "When comparing treatments, explain the listed price, duration and aftercare.\n"
        "Never guarantee treatment results. Offer a consultation if one is listed."
    ),
    "tuition_center": _SHARED + (
        "If a parent is weighing fees or schedules, compare the listed class times and what the fee covers.\n"
        "Explain how the class supports the student's goal without promising grades."
    ),
    "property_agent": _SHARED + (
        "When comparing properties, explain the listed asking prices, fees and viewing arrangements.\n"
        "Never promise returns or financing approvals. Identify which terms still need confirmation."
    ),
    "car_workshop": _SHARED + (
        "If a quote seems high, explain which parts and labour it covers.\n"
        "Give a firm cost before inspection only if the knowledge states it for that job."
    ),
    "travel_agency": _SHARED + (
        "When comparing packages, explain inclusions, exclusions and the dates each fare covers.\n"
        "Never promise a visa or a fixed price beyond the terms in the knowledge."
    ),
    "restaurant": _SHARED + (
        "For price or timing concerns, explain menu prices and the stated reservation policy.\n"
        "Refer questions about allergies or dietary needs to staff unless the knowledge answers them."
    ),
    "retail_shop": _SHARED + (
        "When comparing products, explain the features or return terms that matter to the shopper.\n"
        "Confirm stock and delivery only when the knowledge covers that item and destination."
    ),
    "general": _SHARED + (
        "If they are weighing options, ask what matters most and compare the listed costs or timing.\n"
        "If an important detail is missing, offer to point them to the team."
    ),
}


def objection_prompt(published_industry):
    template_id = published_industry.get("template_id") if isinstance(published_industry, dict) else None
    if not isinstance(template_id, str):
        template_id = "general"
    return _OBJECTIONS.get(template_id, _OBJECTIONS["general"])
