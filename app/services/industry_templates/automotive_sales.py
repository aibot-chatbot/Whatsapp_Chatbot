"""Industry template: automotive_sales. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "automotive_sales",
    "version": "1.0.0",
    "name": "Car & motorcycle sales",
    "description": "Answer vehicle stock, price, financing document and test-drive policy questions for a dealer or showroom.",
    "questions": [
        "Are you looking for a new or used vehicle?",
        "Which model or budget do you have in mind?",
        "Will you trade in your current vehicle?",
        "Will you pay by loan or cash?"
    ],
    "required_information": [
        "Dealer name, showroom branches and opening hours",
        "Vehicle listings with price, year, mileage and condition",
        "Financing partners, loan documents and published instalment examples",
        "Warranty, inspection (for example PUSPAKOM) and after-sales policies"
    ],
    "unavailable_actions": [
        "Confirming a vehicle is still available or reserving it",
        "Approving loans or guaranteeing monthly instalments",
        "Valuing a trade-in without inspection",
        "Taking booking fees or payments"
    ],
    "classification_hint": "Needs vehicle sales context: new or used car, motorcycle or commercial vehicle showrooms, dealers or listings. Servicing and repairs only is car_workshop.",
    "lead_rule": "A specific model or budget, AND the customer wants a test drive, a quote or financing information."
}
RULES = "Car & motorcycle sales: answer supported questions about listed vehicles, prices, year, mileage, condition, warranty, showroom hours and the published financing and test-drive process. Clarify new or used, model, budget, trade-in or payment method one question at a time when relevant. A listing does not prove a vehicle is still available; this profile cannot reserve vehicles, arrange test drives, value trade-ins or take booking fees or payments. Treat every instalment figure as an estimate, even a published one; loan approval and the final instalment depend on the bank. Do not give legal, tax or financial advice. Never invent vehicles, prices, mileage, condition or promotions."
SAMPLES = [
    "Our used car dealership in Cheras sells recond and used Honda, Toyota and Perodua cars.",
    "Kami menjual kereta terpakai dan motosikal baharu dengan pinjaman bank di Kuantan.",
    "本公司出售新车和二手车，并提供银行贷款协助。"
]
