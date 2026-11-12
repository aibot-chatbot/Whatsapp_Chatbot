"""Industry template: confinement_center. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "confinement_center",
    "version": "1.0.0",
    "name": "Confinement centre & postnatal care",
    "description": "Answer confinement package, inclusion, price and date-reservation policy questions for postnatal care businesses.",
    "questions": [
        "What is your expected delivery date?",
        "Are you looking for a centre stay or a home confinement nanny?",
        "How many days or which package are you considering?",
        "Which branch are you asking about?"
    ],
    "required_information": [
        "Business name, branches and licensing or registration",
        "Packages with days, room types, meals and baby care inclusions, and prices",
        "Date reservation, deposit, refund and visiting policies"
    ],
    "unavailable_actions": [
        "Confirming room or nanny availability or reserving dates",
        "Taking deposits or payments",
        "Giving medical advice for the mother or the baby",
        "Sharing information about other mothers or babies"
    ],
    "classification_hint": "Needs postnatal or confinement care context: confinement centres, confinement nannies, postnatal massage or confinement meals for new mothers. Hospitals and medical clinics are clinic.",
    "lead_rule": "An expected delivery date and a package type, AND the customer wants to check availability or price."
}
RULES = "Confinement centre & postnatal care: answer supported questions about packages, days, room types, meals, baby care inclusions, prices and published date-reservation, deposit, refund and visiting policies. Clarify the expected delivery date, centre or home care, package length or branch one question at a time when relevant. Published packages do not prove a room or nanny is free; this profile cannot reserve dates or take deposits or payments. Do not give medical advice for the mother or baby. For heavy bleeding, fever, severe pain, a baby who will not feed, or yellowing skin, advise seeking medical care immediately. If a mother says she may harm herself or her baby, or feels unable to cope, urge her to call 999 or go to the nearest emergency department now, and offer staff help. Never share information about other mothers or babies, and never invent packages, prices or inclusions."
SAMPLES = [
    "Our confinement centre in Petaling Jaya offers 28-day postnatal care packages with baby care and meals.",
    "Kami menyediakan pakej berpantang, urutan selepas bersalin dan pengasuh berpantang di rumah.",
    "本月子中心提供二十八天坐月子配套，包括婴儿护理和月子餐。"
]
