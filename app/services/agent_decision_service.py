import re


ALLOWED_INTENTS = {
    "greeting",
    "general_question",
    "lead_interest",
    "handoff_request",
    "complaint",
    "knowledge_gap",
    "unknown",
}

ALLOWED_ACTIONS = {
    "answer",
    "ask_follow_up",
    "create_lead",
    "request_handoff",
    "log_knowledge_gap",
    "none",
}


def _safe_text(value, max_chars=600):
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _compact_history(conversation_history, max_items=4):
    compact = []

    for item in (conversation_history or [])[-max_items:]:
        if not isinstance(item, dict):
            continue

        compact.append({
            "role": _safe_text(item.get("role"), 20),
            "content": _safe_text(item.get("content"), 220),
        })

    return compact


def _extract_fields(message):
    name = ""
    contact = ""
    interest = ""

    name_match = re.search(
        r"\b(?:my name is|i am|i'm)\s+([A-Za-z][A-Za-z\s.'-]{1,50})",
        message,
        flags=re.IGNORECASE,
    )
    if name_match:
        possible_name = name_match.group(1).strip(" .")
        non_name_starters = {
            "unhappy",
            "not happy",
            "dissatisfied",
            "not satisfied",
            "angry",
            "upset",
            "disappointed",
        }
        if not any(possible_name.lower().startswith(term) for term in non_name_starters):
            name = possible_name

    email_match = re.search(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        message,
        flags=re.IGNORECASE,
    )
    phone_match = re.search(
        r"(?:\+?\d[\d\s().-]{7,}\d)",
        message,
    )

    if email_match:
        contact = email_match.group(0)
    elif phone_match:
        contact = phone_match.group(0).strip()

    interest_match = re.search(
        r"\b(?:interested in|want to buy|want to book|looking for|need|inquire about|enquire about)\s+(.{3,90})",
        message,
        flags=re.IGNORECASE,
    )
    if interest_match:
        interest = interest_match.group(1).strip(" .?!")

    return {
        "name": name,
        "contact": contact,
        "interest": interest,
    }


def _decision(intent, suggested_action, confidence, reason, extracted_fields=None):
    intent = intent if intent in ALLOWED_INTENTS else "unknown"
    suggested_action = suggested_action if suggested_action in ALLOWED_ACTIONS else "none"

    return {
        "intent": intent,
        "suggested_action": suggested_action,
        "confidence": round(float(confidence), 2),
        "reason": _safe_text(reason, 180),
        "extracted_fields": extracted_fields or {
            "name": "",
            "contact": "",
            "interest": "",
        },
    }


def build_safe_agent_action_payload(decision):
    extracted_fields = (decision or {}).get("extracted_fields") or {}

    return {
        "extracted_fields": {
            "has_name": bool(extracted_fields.get("name")),
            "has_contact": bool(extracted_fields.get("contact")),
            "has_interest": bool(extracted_fields.get("interest")),
        }
    }


def analyze_agent_intent(
    message,
    conversation_history=None,
    bot_profile=None,
    knowledge_context=None,
):
    """
    Passive agent-intent classifier.

    This first-step implementation does not execute tools or change replies. It
    classifies the message into a safe action category for logging/future use.
    """
    del bot_profile, knowledge_context

    text = _safe_text(message, 1000)
    if not text:
        return _decision("unknown", "none", 0.0, "Empty message.")

    lowered = text.lower()
    extracted_fields = _extract_fields(text)
    recent_history = _compact_history(conversation_history)

    greeting_terms = {
        "hi",
        "hello",
        "hey",
        "hai",
        "salam",
        "morning",
        "afternoon",
        "start",
        "menu",
        "main",
        "home",
    }

    if lowered in greeting_terms:
        return _decision(
            "greeting",
            "answer",
            0.9,
            "Customer sent a greeting or menu-start message.",
            extracted_fields,
        )

    handoff_terms = [
        "human",
        "agent",
        "staff",
        "representative",
        "real person",
        "talk to someone",
        "speak to someone",
        "customer service",
        "call me",
    ]
    complaint_terms = [
        "unhappy",
        "not happy",
        "dissatisfied",
        "not satisfied",
        "bad service",
        "poor service",
        "terrible",
        "disappointed",
        "complain",
        "complaint",
        "angry",
        "upset",
        "no one replied",
        "nobody replied",
        "service issue",
        "not working",
        "failed",
        "refund",
        "cancel",
        "problem",
        "issue",
    ]
    lead_terms = [
        "interested",
        "price",
        "pricing",
        "quote",
        "book",
        "booking",
        "buy",
        "purchase",
        "register",
        "sign up",
        "demo",
        "package",
        "plan",
        "contact me",
    ]
    knowledge_gap_terms = [
        "exact",
        "latest",
        "available",
        "availability",
        "deadline",
        "date",
        "policy",
        "guarantee",
        "terms",
        "requirements",
    ]

    if any(term in lowered for term in handoff_terms):
        return _decision(
            "handoff_request",
            "request_handoff",
            0.86,
            "Customer appears to request a human or staff follow-up.",
            extracted_fields,
        )

    if any(term in lowered for term in complaint_terms):
        return _decision(
            "complaint",
            "request_handoff",
            0.8,
            "Customer message may contain dissatisfaction or service issues.",
            extracted_fields,
        )

    has_contact = bool(extracted_fields.get("contact"))
    has_interest = bool(extracted_fields.get("interest"))
    if has_contact or has_interest or any(term in lowered for term in lead_terms):
        action = "create_lead" if has_contact and (has_interest or any(term in lowered for term in lead_terms)) else "ask_follow_up"
        confidence = 0.82 if action == "create_lead" else 0.68

        return _decision(
            "lead_interest",
            action,
            confidence,
            "Customer appears interested in a product, service, booking, registration, or pricing.",
            extracted_fields,
        )

    if any(term in lowered for term in knowledge_gap_terms) and "?" in lowered:
        return _decision(
            "knowledge_gap",
            "log_knowledge_gap",
            0.58,
            "Customer asks for specific business information that may need knowledge coverage.",
            extracted_fields,
        )

    if "?" in lowered:
        return _decision(
            "general_question",
            "answer",
            0.62,
            f"General customer question with {len(recent_history)} recent history item(s) available.",
            extracted_fields,
        )

    return _decision(
        "unknown",
        "none",
        0.35,
        "Message does not clearly map to a controlled agent action category.",
        extracted_fields,
    )
