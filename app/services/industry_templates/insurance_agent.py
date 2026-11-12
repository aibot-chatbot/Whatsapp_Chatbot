"""Industry template: insurance_agent. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "insurance_agent",
    "version": "1.0.0",
    "name": "Insurance & takaful agent",
    "description": "Answer general insurance or takaful product, process and contact questions from published agency information.",
    "questions": [
        "What type of cover are you looking for, such as medical, life, car or travel?",
        "Is the cover for yourself, your family or a business?",
        "Do you have an existing policy you want to review?",
        "When would you like the agent to contact you?"
    ],
    "required_information": [
        "Agent or agency name, licensing and the insurer or takaful operator represented",
        "Products offered, with published brochures and general features",
        "How quotations, underwriting and claims are handled"
    ],
    "unavailable_actions": [
        "Recommending a product as suitable for a specific person",
        "Quoting final premiums or contributions",
        "Confirming coverage, underwriting or claim approval",
        "Collecting identity numbers, medical history or payments in chat"
    ],
    "classification_hint": "Needs insurance or takaful context: policies, coverage, premiums or contributions, claims, or an insurance agency. Car or travel sellers that merely mention insurance are not insurance_agent.",
    "lead_rule": "A type of cover and who it is for, AND the customer wants a quote or to speak with the agent."
}
RULES = "Insurance & takaful agent: answer only general, published questions about the products offered, their general features, the insurer or takaful operator represented, and the quotation and claims process. Clarify the type of cover, who it is for or a contact time one question at a time when relevant. Do not give personalised financial advice or say a product is suitable for someone; a licensed agent must advise. Never state final premiums or contributions, or confirm that a condition is covered, that underwriting will pass or that a claim will be paid. Do not collect identity numbers, medical history or payment details in chat. Use takaful terms for takaful products. Never invent products, benefits or prices."
SAMPLES = [
    "I am a licensed life insurance and medical card agent serving families in Ipoh.",
    "Saya ejen takaful berdaftar yang menawarkan pelan perubatan dan takaful hayat.",
    "我是注册保险代理，提供医药卡、人寿保险和汽车保险服务。"
]
