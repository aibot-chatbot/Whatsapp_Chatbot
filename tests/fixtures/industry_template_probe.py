"""Industry template: ci_probe_industry. Proposed by @some-dev via industry-template-mcp. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "ci_probe_industry",
    "version": "1.0.0",
    "name": "Dental clinic",
    "description": "Answer dental service, price and appointment policy questions.",
    "questions": [
        "Which branch are you asking about?",
        "Which dental service do you need?"
    ],
    "required_information": [
        "Clinic name and branches",
        "Dental services and prices"
    ],
    "unavailable_actions": [
        "Booking or changing appointments",
        "Diagnosis or treatment advice"
    ],
    "classification_hint": "Needs dental services such as scaling, fillings, braces or dentures.",
    "lead_rule": "The customer wants a dental appointment or a treatment quotation."
}
RULES = "Dental clinic: answer supported questions about published dental services, prices and policies. Do not diagnose, give treatment advice or confirm appointment slots."
SAMPLES = [
    "Our dental clinic offers scaling and braces.",
    "Klinik gigi kami menawarkan cabutan dan pendakap.",
    "本牙科诊所提供洗牙和矫正服务。"
]
