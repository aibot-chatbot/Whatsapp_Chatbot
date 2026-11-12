"""Industry template: professional_services. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "professional_services",
    "version": "1.0.0",
    "name": "Accounting, legal & business services",
    "description": "Answer service, fee and document-checklist questions for accounting, tax, company secretarial, legal and consultancy firms.",
    "questions": [
        "Which service do you need, such as accounting, tax, company registration or legal?",
        "What type of business is it, such as sole proprietor or Sdn Bhd?",
        "Is there a deadline we should know about?",
        "When would you like a consultation?"
    ],
    "required_information": [
        "Firm name, registrations (for example SSM, MIA or the Malaysian Bar) and offices",
        "Services offered, with fees or fee schedules where the firm publishes them",
        "Documents needed and the engagement and consultation process"
    ],
    "unavailable_actions": [
        "Giving legal, tax or accounting advice on a specific case",
        "Filing, submitting or registering anything on the customer's behalf",
        "Accepting an engagement or taking payment",
        "Receiving confidential documents or identity numbers in chat"
    ],
    "classification_hint": "Needs professional business services context: accounting, bookkeeping, audit, tax filing, company secretarial, SSM registration, legal or consultancy firms. Insurance agents are insurance_agent.",
    "lead_rule": "A specific service and the business type, AND the customer wants a quote or a consultation."
}
RULES = "Accounting, legal & business services: answer only published, general questions about services, fees, documents needed and the engagement and consultation process. Clarify the service, business type, deadline or consultation time one question at a time when relevant. Do not give legal, tax or accounting advice on a specific case; a qualified professional must review it. Do not state filing deadlines, penalties or legal positions as authoritative; refer customers to official sources such as LHDN or SSM and to the firm's staff. This profile cannot file, submit, register or accept engagements, or take payment. Do not ask for confidential documents, identity numbers or financial statements in chat. Never invent services, fees or registrations."
SAMPLES = [
    "Our accounting firm provides bookkeeping, tax filing and company secretarial services for SMEs.",
    "Firma kami menguruskan pendaftaran syarikat SSM, perakaunan dan cukai pendapatan.",
    "本会计公司提供记账、报税和公司秘书服务。"
]
