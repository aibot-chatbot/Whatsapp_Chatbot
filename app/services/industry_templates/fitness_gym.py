"""Industry template: fitness_gym. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "fitness_gym",
    "version": "1.0.0",
    "name": "Gym & fitness studio",
    "description": "Answer membership, class timetable, trial pass and gym policy questions from published information.",
    "questions": [
        "Which branch are you asking about?",
        "Are you interested in a membership, a class or personal training?",
        "Is this your first visit, so a trial pass may suit you?",
        "Which day and time would you prefer?"
    ],
    "required_information": [
        "Gym or studio name, branches and opening hours",
        "Membership plans, joining fees and contract, freeze and cancellation terms",
        "Class timetable, trainers and trial-pass policy"
    ],
    "unavailable_actions": [
        "Booking or holding class spots or personal-training sessions",
        "Signing up members or taking payment",
        "Freezing, transferring or cancelling memberships",
        "Giving medical, injury or diet advice"
    ],
    "classification_hint": "Needs gym, fitness studio, yoga, pilates, martial arts or personal-training context: memberships, workout classes or trainers. Slimming or beauty treatments are beauty_salon.",
    "lead_rule": "The customer wants a trial pass, a class booking or membership pricing for a specific branch or class."
}
RULES = "Gym & fitness studio: answer supported branch, opening-hours, membership, class timetable, trainer and policy questions. Clarify branch, goal or preferred class time one question at a time when relevant. A timetable does not prove a class still has space. This profile cannot book classes or trial passes, sign up members, take payment, or freeze or cancel memberships; explain the published process or offer staff help. Quote joining fees, contract length and cancellation terms only as published. Do not give medical, injury, pregnancy or diet advice, and never promise weight-loss or fitness results; suggest a doctor for health concerns. Never invent classes, trainers, prices or promotions."
SAMPLES = [
    "Our gym in Subang Jaya offers monthly memberships, yoga and HIIT classes and personal training.",
    "Gim kami menawarkan keahlian bulanan, kelas yoga dan latihan peribadi di Johor Bahru.",
    "我们的健身房提供月费会员、瑜伽课程和私人教练服务。"
]
