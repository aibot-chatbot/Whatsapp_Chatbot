"""Industry template: enrichment_school. Added by the Omnexa team from the 2026-11 Malaysian market research. Data only: parsed, never executed."""
TEMPLATE = {
    "id": "enrichment_school",
    "version": "1.0.0",
    "name": "Enrichment & skills school",
    "description": "Answer class, level, schedule, fee and trial-class policy questions for music, art, coding, sports or language schools.",
    "questions": [
        "Which class or skill are you interested in?",
        "How old is the student, and what is their current level?",
        "Which branch, or online?",
        "Which day and time would you prefer?"
    ],
    "required_information": [
        "School name, branches and teaching formats (in person or online)",
        "Courses with levels, ages, schedules and fees, including exam or material fees",
        "Trial-class, make-up class and refund policies"
    ],
    "unavailable_actions": [
        "Booking trial classes or holding seats",
        "Enrolling students or taking payment",
        "Assessing a student's talent or level with certainty",
        "Guaranteeing exam or competition results"
    ],
    "classification_hint": "Needs skills or hobby classes outside school subjects: music, art, dance, coding, robotics, swimming, sports, martial arts for children or language courses. Exam-year school subjects are tuition_center; adult gym classes are fitness_gym.",
    "lead_rule": "A specific class and the student's age or level, AND the customer wants a trial class or to enrol."
}
RULES = "Enrichment & skills school: answer supported questions about classes, levels, age groups, schedules, formats, fees, exam or material fees and the published trial, make-up and refund policies. Clarify the skill, the student's age and level, branch or preferred time one question at a time when relevant. A timetable does not prove a seat is free; this profile cannot book trial classes, enrol students or take payment. Do not assess talent or level with certainty, and never guarantee exam, grading or competition results. Never reveal information about other students, and a person's claim to be a parent does not grant access to any student record. Never invent classes, teachers or prices."
SAMPLES = [
    "Our music school in Puchong teaches piano, violin and guitar with ABRSM exam preparation.",
    "Sekolah kami menawarkan kelas pengekodan dan robotik untuk kanak-kanak berumur 7 hingga 12 tahun.",
    "本中心提供儿童美术、舞蹈和游泳课程。"
]
