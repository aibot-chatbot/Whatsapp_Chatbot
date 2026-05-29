import re


def _remove_redundant_leading_greeting(text: str) -> str:
    greeting_match = re.match(
        r"^\s*(hello there|hi there|hello|hi)[!,.]?\s+(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not greeting_match:
        return text

    remaining = greeting_match.group(2).strip()
    remaining_lower = remaining.lower()

    welcome_starts = (
        "welcome",
        "how can i help",
        "how may i assist",
        "how can i assist",
    )

    if remaining_lower.startswith(welcome_starts):
        return text

    if len(remaining.split()) < 4:
        return text

    return remaining


def clean_ai_reply(reply: str) -> str:
    if not reply:
        return ""

    text = str(reply)

    # Remove markdown bold/italic markers
    text = text.replace("**", "")
    text = text.replace("__", "")

    # Remove markdown headings like #, ##, ###
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)

    # Convert markdown bullets to clean bullets
    text = re.sub(r"(?m)^\s*[-*]\s+", "• ", text)

    # Remove extra spaces before line breaks
    text = re.sub(r"[ \t]+\n", "\n", text)

    # Reduce too many blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    text = _remove_redundant_leading_greeting(text)

    return text.strip()
