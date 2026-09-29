"""Industry template: dryrun_pet_grooming. Proposed by @KagVince5 via industry-template-mcp. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "dryrun_pet_grooming",
    "version": "1.0.0",
    "name": "Pet grooming (dry run)",
    "description": "Answer pet grooming service, price and appointment policy questions.",
    "questions": [
        "Is your pet a dog or a cat?",
        "Which grooming service do you need?"
    ],
    "required_information": [
        "Shop name and branches",
        "Grooming services and prices"
    ],
    "unavailable_actions": [
        "Booking or changing grooming appointments",
        "Veterinary diagnosis or treatment advice"
    ],
    "classification_hint": "Offers dog or cat grooming such as bathing, haircuts and nail trimming; not a veterinary clinic or a pet food retail shop.",
    "lead_rule": "The customer wants a grooming appointment or a price quotation for their pet."
}
RULES = "Pet grooming shop: answer supported questions about published grooming services, prices and policies. Clarify pet type or size one question at a time when relevant. Do not diagnose illness, give veterinary advice or confirm appointment slots."
SAMPLES = [
    "Our pet salon offers dog bathing and haircuts.",
    "Kedai dandanan kami menawarkan mandian dan potongan bulu anjing.",
    "本宠物美容店提供狗狗洗澡和剪毛服务。"
]
