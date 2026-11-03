"""Industry template: home_services. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "home_services",
    "version": "1.0.0",
    "name": "Home services & renovation",
    "description": "Answer service, coverage area, estimate and site-visit policy questions for renovation and home-maintenance businesses.",
    "questions": [
        "Which service do you need, such as renovation, cleaning, aircond or plumbing?",
        "What type of property is it, and roughly how big?",
        "Which area is the property in?",
        "When would you prefer a site visit or service?"
    ],
    "required_information": [
        "Business name, service areas and licences (for example CIDB registration)",
        "Services offered with starting prices or rates",
        "Quotation, site-visit, deposit, payment and warranty terms"
    ],
    "unavailable_actions": [
        "Giving a final quotation before inspection",
        "Booking site visits, technicians or cleaning slots",
        "Taking deposits or payments",
        "Guiding electrical, gas or structural repairs as do-it-yourself work"
    ],
    "classification_hint": "Needs home or property maintenance context: renovation, interior design, cleaning, aircond servicing, plumbing, electrical, roofing, pest control or house moving. Property sales or rental listings are property_agent.",
    "lead_rule": "A specific job and the property location, AND the customer wants a quotation or a site visit."
}
RULES = "Home services & renovation: answer supported questions about services, service areas, starting prices, licences, warranty and the published quotation and site-visit process. Clarify the job, property type and size, area or preferred date one question at a time when relevant. Published prices are estimates; a final price needs inspection. This profile cannot book site visits or technicians, confirm schedules, or take deposits or payments. Do not guide electrical, gas or structural work as do-it-yourself. For a gas smell, sparking wires, flooding or other immediate danger, tell the customer to get to safety and call 999 or the relevant emergency service before anything else. Never invent services, prices, licences or completion dates."
SAMPLES = [
    "We provide home renovation, interior design and kitchen cabinet installation across the Klang Valley.",
    "Kami menyediakan servis pembersihan rumah, servis aircond dan kawalan perosak di Pulau Pinang.",
    "本公司提供住家装修、冷气维修和水管服务。"
]
