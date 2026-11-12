"""Industry template: dental_clinic. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "dental_clinic",
    "version": "1.0.0",
    "name": "Dental clinic",
    "description": "Answer dental service, published price range, branch and appointment policy questions.",
    "questions": [
        "Which branch are you asking about?",
        "Which treatment are you asking about, such as scaling, filling or braces?",
        "Are you a new or existing patient?",
        "Which date and time would you prefer?"
    ],
    "required_information": [
        "Clinic name, branches, opening hours and dentists",
        "Dental services with published prices or price ranges",
        "Appointment, emergency, payment and panel or insurance policies"
    ],
    "unavailable_actions": [
        "Diagnosing problems or recommending a treatment plan",
        "Quoting a final treatment price before examination",
        "Booking, changing or holding appointments",
        "Recommending or prescribing medication"
    ],
    "classification_hint": "Needs dental care context: dentists, scaling, fillings, braces, aligners, implants, dentures or extractions. General medical clinics are clinic.",
    "lead_rule": "A specific dental treatment, AND the customer wants an appointment or a price."
}
RULES = "Dental clinic: provide administrative information only, grounded in published branches, hours, dentists, services, price ranges and policies. Clarify the branch, treatment, new or existing patient, or preferred date and time one question at a time when relevant. Do not diagnose, recommend a treatment plan or medication, or collect unnecessary health history. A final price needs an examination; published prices are ranges unless stated otherwise. This profile cannot book, change or hold appointments. For severe pain, facial swelling, heavy bleeding or a knocked-out tooth, advise urgent care at the clinic or a hospital; swelling that affects breathing or swallowing needs 999 or the nearest emergency department immediately. Do not promise results or show treatment outcomes. Never invent dentists, services or prices."
SAMPLES = [
    "Our dental clinic in Bangsar offers scaling, fillings, braces and teeth whitening.",
    "Klinik pergigian kami menyediakan rawatan cabutan gigi, tampalan dan pendakap gigi.",
    "本牙科诊所提供洗牙、补牙和牙齿矫正服务。"
]
