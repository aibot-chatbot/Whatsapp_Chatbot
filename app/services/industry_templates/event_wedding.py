"""Industry template: event_wedding. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "event_wedding",
    "version": "1.0.0",
    "name": "Events, wedding & photography",
    "description": "Answer package, inclusion, date and booking policy questions for event, wedding, venue and photography businesses.",
    "questions": [
        "What type of event is it?",
        "What is the event date?",
        "About how many guests are expected?",
        "Where will it be held, or do you need a venue?",
        "What budget or package type do you have in mind?"
    ],
    "required_information": [
        "Business name and the services offered (planning, venue, photography, decoration)",
        "Packages with inclusions, hours, deliverables and prices",
        "Date reservation, deposit, balance, postponement and cancellation terms",
        "Venue capacity or portfolio where relevant"
    ],
    "unavailable_actions": [
        "Confirming that a date is free or holding a date",
        "Taking deposits or payments",
        "Changing contracts or package terms",
        "Guaranteeing weather, third-party vendors or delivery dates beyond policy"
    ],
    "classification_hint": "Needs event, wedding, venue, photography, videography, decoration or event-planning context. A restaurant's own dining reservations are restaurant; bridal makeup alone is beauty_salon.",
    "lead_rule": "An event type and date, AND the customer wants a package quote or to check availability."
}
RULES = "Events, wedding & photography: answer supported questions about packages, inclusions, hours, deliverables, venue capacity, prices and published deposit, balance, postponement and cancellation terms. Clarify the event type, date, guest count, location or budget one question at a time when relevant. A package list does not prove a date is free; this profile cannot hold dates, confirm bookings, change contracts or take deposits or payments. Quote deposits and refund terms only as published, and say that staff confirm the final quotation. Do not guarantee weather, third-party vendors or delivery dates beyond the published policy. Never invent packages, prices, inclusions or portfolio work."
SAMPLES = [
    "We are a wedding planner and photography studio offering full-day wedding packages in Kuala Lumpur.",
    "Kami menyediakan pakej perkahwinan, dewan majlis dan khidmat fotografi di Shah Alam.",
    "本公司提供婚礼策划、婚纱摄影和活动布置配套。"
]
